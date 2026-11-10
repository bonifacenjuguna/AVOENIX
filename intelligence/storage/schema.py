"""Table specifications shared by every storage backend.

The spec is the *single* place where identifiers are whitelisted (so SQL is never built from caller input)
and where JSON columns are declared. ``tests/integration`` verifies that this spec matches the real
PostgreSQL schema (``database/schemas/0001_initial.sql``) column-for-column.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    json_columns: frozenset[str] = frozenset()
    pk: str = "id"
    scoped: bool = False                  # carries project_id + user_id and must be accessed through a ScopedRepo
    auto_pk: bool = False                 # database generates the primary key (bigserial)
    timestamps: frozenset[str] = frozenset()      # columns holding timestamptz (ISO strings in Python)


def _t(name, cols, *, json=(), pk="id", scoped=False, auto_pk=False, ts=()):
    return Table(name, tuple(cols.split()), frozenset(json), pk, scoped, auto_pk, frozenset(ts))


TABLES: dict[str, Table] = {t.name: t for t in [
    _t("schema_info", "key value updated_at", pk="key", ts=("updated_at",)),
    _t("users", "id email password_hash role display_name is_active created_at last_login_at failed_logins locked_until",
       ts=("created_at", "last_login_at", "locked_until")),
    _t("sessions", "id user_id token_hash created_at expires_at revoked_at ip user_agent", ts=("created_at", "expires_at", "revoked_at")),
    _t("projects", "id name description status owner_user_id created_at", ts=("created_at",)),
    _t("project_users", "project_id user_id display_name created_at", pk="project_id,user_id", ts=("created_at",)),
    _t("api_keys", "id project_id name prefix key_hash scopes created_at last_used_at revoked_at", json=("scopes",),
       ts=("created_at", "last_used_at", "revoked_at")),
    _t("conversations", "id project_id user_id title state archived created_at updated_at", json=("state",), scoped=True,
       ts=("created_at", "updated_at")),
    _t("messages", "id conversation_id project_id user_id role content turn_index latency_ms meta created_at", json=("meta",), scoped=True,
       ts=("created_at",)),
    _t("turn_traces", "id conversation_id message_id project_id user_id status total_ms trace summary created_at",
       json=("trace", "summary"), scoped=True, ts=("created_at",)),
    _t("memories", "id project_id user_id category key content data acr importance confidence source conversation_id status access_count "
       "created_at updated_at last_accessed_at expires_at", json=("data", "acr"), scoped=True,
       ts=("created_at", "updated_at", "last_accessed_at", "expires_at")),
    _t("knowledge_facts", "id project_id user_id conversation_id predicate args polarity quantifier qualifiers statement confidence "
       "source_type source_id status superseded_by version created_at updated_at", json=("args", "qualifiers"),
       ts=("created_at", "updated_at")),
    _t("knowledge_terms", "fact_id role term_key project_id", pk="fact_id,role"),
    _t("feedback", "id project_id user_id conversation_id message_id kind rating comment payload status created_at", json=("payload",),
       scoped=True, ts=("created_at",)),
    _t("learning_records", "id project_id user_id kind status proposal evaluation applied_change reason source_feedback_id created_at "
       "decided_at decided_by applied_at reverted_at", json=("proposal", "evaluation", "applied_change"),
       ts=("created_at", "decided_at", "applied_at", "reverted_at")),
    _t("evaluation_runs", "id suite platform_version label started_at finished_at summary results environment triggered_by",
       json=("summary", "results", "environment"), ts=("started_at", "finished_at")),
    _t("experiments", "id name description status config baseline_run_id candidate_run_id result created_at updated_at",
       json=("config", "result"), ts=("created_at", "updated_at")),
    _t("system_config", "key value version updated_at updated_by", json=("value",), pk="key", ts=("updated_at",)),
    _t("audit_log", "id at actor_id actor_type action target_type target_id project_id details ip", json=("details",), auto_pk=True,
       ts=("at",)),
]}
