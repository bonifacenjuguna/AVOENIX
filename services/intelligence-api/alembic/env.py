"""Alembic environment. Uses a plain psycopg connection and raw SQL migrations (no SQLAlchemy models; the schema is SQL-first)."""
import os

import psycopg
from alembic import context

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set")


def run_migrations_online() -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        context.configure(connection=conn, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
