-- AVOENIX database schema, revision 0001 (platform v0.0.0)
-- PostgreSQL 14+. Applied by services/intelligence-api/migrate.py (idempotent).
-- or directly:  psql "$DATABASE_URL" -f database/schemas/0001_initial.sql
--
-- Isolation model: every user-owned row carries (project_id, user_id). The application layer ALWAYS
-- filters on both (intelligence/storage/scoped.py); Row-Level Security below is defence in depth and is
-- enforced when the application connects as a non-owner role and sets avoenix.project_id / avoenix.user_id.

CREATE TABLE IF NOT EXISTS schema_info (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- identity & access
CREATE TABLE IF NOT EXISTS users (
    id               text PRIMARY KEY,
    email            text NOT NULL,
    password_hash    text NOT NULL,
    role             text NOT NULL DEFAULT 'admin' CHECK (role IN ('admin', 'member')),
    display_name     text,
    is_active        boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_login_at    timestamptz,
    failed_logins    integer NOT NULL DEFAULT 0 CHECK (failed_logins >= 0),
    locked_until     timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_uq ON users (lower(email));

CREATE TABLE IF NOT EXISTS sessions (
    id           text PRIMARY KEY,
    user_id      text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    ip           text,
    user_agent   text
);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_token_hash_uq ON sessions (token_hash);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, expires_at);

CREATE TABLE IF NOT EXISTS projects (
    id              text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9._:-]{1,128}$'),
    name            text NOT NULL,
    description     text,
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    owner_user_id   text REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_users (
    project_id    text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id       text NOT NULL CHECK (user_id ~ '^[A-Za-z0-9._:-]{1,128}$'),
    display_name  text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id)
);

-- Prepared for future project-specific API keys (not exposed by the v1 API in v0.0.0).
CREATE TABLE IF NOT EXISTS api_keys (
    id            text PRIMARY KEY,
    project_id    text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name          text NOT NULL,
    prefix        text NOT NULL,
    key_hash      text NOT NULL,
    scopes        jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    revoked_at    timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS api_keys_hash_uq ON api_keys (key_hash);

-- ---------------------------------------------------------------- conversations
CREATE TABLE IF NOT EXISTS conversations (
    id          text PRIMARY KEY,
    project_id  text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     text NOT NULL,
    title       text,
    state       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- serialised Context Engine state
    archived    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_scope_idx ON conversations (project_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id               text PRIMARY KEY,
    conversation_id  text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    project_id       text NOT NULL,
    user_id          text NOT NULL,
    role             text NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content          text NOT NULL,
    turn_index       integer NOT NULL CHECK (turn_index >= 0),
    latency_ms       double precision,
    meta             jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_conv_idx ON messages (conversation_id, turn_index, created_at);
CREATE INDEX IF NOT EXISTS messages_scope_idx ON messages (project_id, user_id);

CREATE TABLE IF NOT EXISTS turn_traces (
    id               text PRIMARY KEY,
    conversation_id  text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id       text,
    project_id       text NOT NULL,
    user_id          text NOT NULL,
    status           text NOT NULL,
    total_ms         double precision NOT NULL,
    trace            jsonb NOT NULL,       -- per-engine stage timings (measured)
    summary          jsonb NOT NULL,       -- understanding / reasoning / confidence summaries
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS turn_traces_scope_idx ON turn_traces (project_id, created_at DESC);

-- ---------------------------------------------------------------- memory
CREATE TABLE IF NOT EXISTS memories (
    id               text PRIMARY KEY,
    project_id       text NOT NULL,
    user_id          text NOT NULL,
    category         text NOT NULL CHECK (category IN ('working', 'conversational', 'episodic', 'semantic', 'preference', 'learned')),
    key              text,
    content          text NOT NULL,
    data             jsonb NOT NULL DEFAULT '{}'::jsonb,
    acr              jsonb,
    importance       double precision NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    confidence       double precision NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    source           text NOT NULL DEFAULT 'user_statement',
    conversation_id  text,
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'deleted')),
    access_count     integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_accessed_at timestamptz,
    expires_at       timestamptz
);
CREATE INDEX IF NOT EXISTS memories_scope_cat_idx ON memories (project_id, user_id, category, status);
CREATE INDEX IF NOT EXISTS memories_key_idx ON memories (project_id, user_id, category, key) WHERE key IS NOT NULL;

-- ---------------------------------------------------------------- knowledge
-- project_id = '*' marks curated global knowledge shipped with AVOENIX (read-only for applications).
CREATE TABLE IF NOT EXISTS knowledge_facts (
    id               text PRIMARY KEY,
    project_id       text NOT NULL,
    user_id          text,                    -- NULL = project-wide knowledge
    conversation_id  text,
    predicate        text NOT NULL,
    args             jsonb NOT NULL,          -- role -> normalised term
    polarity         text NOT NULL DEFAULT 'positive' CHECK (polarity IN ('positive', 'negative')),
    quantifier       text,
    qualifiers       jsonb NOT NULL DEFAULT '{}'::jsonb,
    statement        text NOT NULL,           -- rendered text, used for lexical retrieval and inspection
    confidence       double precision NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    source_type      text NOT NULL CHECK (source_type IN ('user_statement', 'external_verified', 'seed_curated', 'derived', 'learned', 'system')),
    source_id        text,
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'retracted', 'disputed')),
    superseded_by    text,
    version          integer NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_scope_pred_idx ON knowledge_facts (project_id, user_id, predicate, status);
CREATE INDEX IF NOT EXISTS knowledge_args_gin ON knowledge_facts USING gin (args jsonb_path_ops);

CREATE TABLE IF NOT EXISTS knowledge_terms (
    fact_id     text NOT NULL REFERENCES knowledge_facts(id) ON DELETE CASCADE,
    role        text NOT NULL,
    term_key    text NOT NULL,
    project_id  text NOT NULL,
    PRIMARY KEY (fact_id, role)
);
CREATE INDEX IF NOT EXISTS knowledge_terms_lookup_idx ON knowledge_terms (project_id, term_key);

-- ---------------------------------------------------------------- feedback & learning
CREATE TABLE IF NOT EXISTS feedback (
    id               text PRIMARY KEY,
    project_id       text NOT NULL,
    user_id          text NOT NULL,
    conversation_id  text,
    message_id       text,
    kind             text NOT NULL CHECK (kind IN ('rating', 'correction', 'report', 'comment')),
    rating           integer CHECK (rating IS NULL OR rating BETWEEN -1 AND 1),
    comment          text,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    status           text NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded', 'processed', 'ignored')),
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_scope_idx ON feedback (project_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS learning_records (
    id            text PRIMARY KEY,
    project_id    text NOT NULL,
    user_id       text,
    kind          text NOT NULL CHECK (kind IN ('preference', 'fact_correction', 'strategy_adjustment', 'general_knowledge')),
    status        text NOT NULL CHECK (status IN ('proposed', 'approved', 'applied', 'rejected', 'reverted', 'failed')),
    proposal      jsonb NOT NULL,
    evaluation    jsonb,               -- regression check / validation outcome (measured)
    applied_change jsonb,              -- exactly what was written, so it can be reverted
    reason        text,
    source_feedback_id text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz,
    decided_by    text,
    applied_at    timestamptz,
    reverted_at   timestamptz
);
CREATE INDEX IF NOT EXISTS learning_scope_idx ON learning_records (project_id, status, created_at DESC);

-- ---------------------------------------------------------------- evaluation
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id            text PRIMARY KEY,
    suite         text NOT NULL,
    platform_version text NOT NULL,
    label         text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    summary       jsonb NOT NULL DEFAULT '{}'::jsonb,
    results       jsonb NOT NULL DEFAULT '[]'::jsonb,
    environment   jsonb NOT NULL DEFAULT '{}'::jsonb,
    triggered_by  text
);
CREATE INDEX IF NOT EXISTS evaluation_runs_suite_idx ON evaluation_runs (suite, started_at DESC);

CREATE TABLE IF NOT EXISTS experiments (
    id                 text PRIMARY KEY,
    name               text NOT NULL,
    description        text,
    status             text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'completed', 'failed')),
    config             jsonb NOT NULL DEFAULT '{}'::jsonb,
    baseline_run_id    text REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    candidate_run_id   text REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    result             jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- configuration & audit
CREATE TABLE IF NOT EXISTS system_config (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    version     integer NOT NULL DEFAULT 1,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor_id    text,
    actor_type  text NOT NULL DEFAULT 'user',
    action      text NOT NULL,
    target_type text,
    target_id   text,
    project_id  text,
    details     jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip          text
);
CREATE INDEX IF NOT EXISTS audit_at_idx ON audit_log (at DESC);
CREATE INDEX IF NOT EXISTS audit_action_idx ON audit_log (action, at DESC);

-- ---------------------------------------------------------------- defence in depth: row level security
-- Enabled for the user-owned tables. The application role must NOT be the table owner (owners bypass RLS
-- unless FORCE is set). The app sets  SET LOCAL avoenix.project_id = '...'; SET LOCAL avoenix.user_id = '...';
-- per transaction when running with RLS (see docs/security/). Policies are permissive for the maintenance
-- role 'avoenix_admin' only if it exists.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['conversations', 'messages', 'turn_traces', 'memories', 'feedback']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS avoenix_scope ON %I', t);
    EXECUTE format($p$CREATE POLICY avoenix_scope ON %I USING (
        current_setting('avoenix.bypass', true) = 'on' OR
        (project_id = current_setting('avoenix.project_id', true) AND user_id = current_setting('avoenix.user_id', true)))$p$, t);
  END LOOP;
END $$;

INSERT INTO schema_info (key, value) VALUES ('schema_revision', '0001'), ('platform_version', 'v0.0.0')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
