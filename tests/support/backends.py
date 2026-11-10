"""Backend factories used by parametrised tests."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from intelligence.storage import MemoryBackend
from intelligence.storage.postgres_backend import PostgresBackend

PG_URL_ENV = "AVOENIX_TEST_PG"      # format: host:port:dbname[:user]   e.g. 127.0.0.1:54329:avoenix_test


def pg_params():
    raw = os.environ.get(PG_URL_ENV)
    if not raw:
        return None
    parts = raw.split(":")
    return parts[0], int(parts[1]), parts[2], (parts[3] if len(parts) > 3 else "postgres")


def pg_available() -> tuple[bool, str]:
    p = pg_params()
    if not p:
        return False, f"{PG_URL_ENV} not set (BLOCKED BY ENVIRONMENT: no PostgreSQL provided)"
    if not shutil.which("psql"):
        return False, "psql client not installed"
    r = subprocess.run(["pg_isready", "-h", p[0], "-p", str(p[1])], capture_output=True, text=True)
    return r.returncode == 0, r.stdout.strip() or "pg_isready failed"


def make_pg_backend() -> PostgresBackend:
    from tests.support.psql_database import PsqlDatabase
    host, port, db, user = pg_params()
    backend = PostgresBackend(PsqlDatabase(host, port, db, user))
    # clean slate for tests (children before parents)
    for t in ["audit_log", "knowledge_terms", "knowledge_facts", "learning_records", "feedback", "turn_traces", "messages", "conversations",
              "memories", "experiments", "evaluation_runs", "system_config", "api_keys", "sessions", "project_users", "projects", "users"]:
        backend.db.query(f'DELETE FROM "{t}" RETURNING 1 AS n', [])
    return backend


def backend_params():
    ok, why = pg_available()
    return [
        pytest.param("memory", id="memory"),
        pytest.param("postgres", id="postgres", marks=[pytest.mark.postgres, pytest.mark.skipif(not ok, reason=why)]),
    ]


def build(kind: str):
    return MemoryBackend() if kind == "memory" else make_pg_backend()
