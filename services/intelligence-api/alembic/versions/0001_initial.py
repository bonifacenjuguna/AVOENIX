"""initial schema (executes database/schemas/0001_initial.sql)

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None

SQL = Path(__file__).resolve().parents[4] / "database" / "schemas" / "0001_initial.sql"


def upgrade() -> None:
    op.execute(SQL.read_text())


def downgrade() -> None:
    raise NotImplementedError("v0.0.0 provides no automated downgrade; restore from backup (see docs/DEPLOYMENT.md)")
