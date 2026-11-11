-- AVOENIX database schema, revision 0002 (platform v0.0.1): Knowledge Integrity.
-- Additive and idempotent. Existing rows are preserved and back-filled; nothing is dropped except one CHECK constraint that is
-- re-created with a wider value list. Rollback: 0002_knowledge_integrity_down.sql.
-- Applied by services/intelligence-api/migrate.py (after 0001), or directly:  psql "$DATABASE_URL" -f database/schemas/0002_knowledge_integrity.sql

-- ---------------------------------------------------------------- knowledge_facts: provenance, claim type, verification, assessment
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS provenance   text  NOT NULL DEFAULT 'unresolved'
    CHECK (provenance IN ('user_provided', 'system_inference', 'internal_knowledge', 'independently_verified', 'imported', 'unresolved'));
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS claim_type   text  NOT NULL DEFAULT 'premise'
    CHECK (claim_type IN ('world', 'personal', 'premise'));
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS verification text  NOT NULL DEFAULT 'unverified'
    CHECK (verification IN ('verified', 'curated', 'supported', 'unverified', 'contradicted', 'conflicting', 'not_applicable'));
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS assessment   jsonb NOT NULL DEFAULT '{}'::jsonb;   -- explainable evidence assessment (claim/1.0)
ALTER TABLE knowledge_facts ADD COLUMN IF NOT EXISTS memory_id    text;                                      -- memory record of the *statement* (memory != knowledge)

-- 'imported' becomes a legal source_type (constraint re-created; the name is PostgreSQL's default for the inline CHECK in 0001)
ALTER TABLE knowledge_facts DROP CONSTRAINT IF EXISTS knowledge_facts_source_type_check;
ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_source_type_check
    CHECK (source_type IN ('user_statement', 'external_verified', 'seed_curated', 'derived', 'learned', 'system', 'imported'));

-- Back-fill legacy rows exactly once (rows already carrying an assessment are left alone).
UPDATE knowledge_facts SET
    provenance = CASE source_type
        WHEN 'user_statement' THEN 'user_provided' WHEN 'derived' THEN 'system_inference'
        WHEN 'seed_curated' THEN 'internal_knowledge' WHEN 'system' THEN 'internal_knowledge' WHEN 'learned' THEN 'internal_knowledge'
        WHEN 'external_verified' THEN 'independently_verified' WHEN 'imported' THEN 'imported' ELSE 'unresolved' END,
    claim_type = CASE
        WHEN args::text LIKE '%"key": "@user"%' THEN 'personal'
        WHEN predicate IN ('attr.capital', 'attr.currency', 'attr.president', 'attr.population', 'rel.located_in') THEN 'world'
        WHEN predicate = 'rel.is_a' AND args->'subject'->>'t' = 'kind' THEN 'world'
        ELSE 'premise' END,
    verification = CASE
        WHEN source_type = 'external_verified' THEN 'verified'
        WHEN source_type IN ('seed_curated', 'system', 'learned') THEN 'curated'
        WHEN args::text LIKE '%"key": "@user"%' THEN 'not_applicable'
        WHEN status = 'disputed' THEN 'conflicting'
        ELSE 'unverified' END,
    assessment = jsonb_build_object(
        'schema', 'claim/1.0', 'level', CASE
            WHEN source_type IN ('external_verified', 'seed_curated', 'system', 'learned') THEN 'established'
            WHEN args::text LIKE '%"key": "@user"%' THEN 'self_reported'
            WHEN status = 'disputed' THEN 'conflicting' ELSE 'unverified' END,
        'verification', 'backfilled', 'interpretation_confidence', confidence, 'support', NULL,
        'basis', jsonb_build_array('back-filled by migration 0002 from source_type; not re-validated'), 'evidence', '[]'::jsonb)
WHERE assessment = '{}'::jsonb;

CREATE INDEX IF NOT EXISTS knowledge_verification_idx ON knowledge_facts (project_id, user_id, verification, status);

-- ---------------------------------------------------------------- conflicts: preserved, never silently resolved
CREATE TABLE IF NOT EXISTS knowledge_conflicts (
    id           text PRIMARY KEY,
    project_id   text NOT NULL,
    user_id      text,
    kind         text NOT NULL CHECK (kind IN ('negation', 'functional', 'taxonomic', 'ordering', 'location')),
    fact_a       text NOT NULL,                    -- the established or earlier claim
    fact_b       text NOT NULL,                    -- the claim that triggered detection
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    resolution   text CHECK (resolution IS NULL OR resolution IN ('established_precedence', 'revised', 'manual_choice', 'dismissed')),
    note         text,
    details      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at  timestamptz,
    resolved_by  text
);
CREATE INDEX IF NOT EXISTS knowledge_conflicts_scope_idx ON knowledge_conflicts (project_id, user_id, status);
CREATE INDEX IF NOT EXISTS knowledge_conflicts_fact_a_idx ON knowledge_conflicts (fact_a);
CREATE INDEX IF NOT EXISTS knowledge_conflicts_fact_b_idx ON knowledge_conflicts (fact_b);

-- ---------------------------------------------------------------- revisions: history is append-only
CREATE TABLE IF NOT EXISTS knowledge_revisions (
    id            text PRIMARY KEY,
    project_id    text NOT NULL,
    user_id       text,
    fact_id       text NOT NULL,                   -- the claim that was revised (kept, marked superseded)
    new_fact_id   text,                            -- the replacement claim
    previous      jsonb NOT NULL,                  -- snapshot of the previous claim
    updated       jsonb NOT NULL,                  -- snapshot of the replacement
    source        text NOT NULL,                   -- who/what made the correction (e.g. user_statement)
    reason        text,
    verified      boolean NOT NULL DEFAULT false,  -- true only when the replacement itself was verified
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_revisions_fact_idx ON knowledge_revisions (fact_id, created_at);
CREATE INDEX IF NOT EXISTS knowledge_revisions_scope_idx ON knowledge_revisions (project_id, user_id, created_at DESC);

INSERT INTO schema_info (key, value) VALUES ('schema_revision', '0002'), ('platform_version', 'v0.0.1')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
