"""Apply every database/schemas/NNNN_*.sql migration in order (idempotent: IF NOT EXISTS / guarded blocks; ``*_down.sql`` files are never applied).
Each file is sent as one multi-statement simple query, which PostgreSQL runs in a single implicit transaction. Run before the API starts.

    DATABASE_URL=postgresql://... python services/intelligence-api/migrate.py

Exit code 0 on success, 1 on failure (so a deploy stops instead of starting against a missing schema).
NOT executed in the build sandbox (psycopg not installable there); the SQL itself was applied to a real PostgreSQL 16 server in tests.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[2] / "database" / "schemas"


def migration_files(directory: Path = SCHEMAS) -> list[Path]:
    """Forward migrations in numeric order; rollback scripts (``*_down.sql``) are excluded."""
    return sorted(p for p in directory.glob("[0-9][0-9][0-9][0-9]_*.sql") if not p.stem.endswith("_down"))


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("migrate: DATABASE_URL is not set", file=sys.stderr)
        return 1
    import psycopg

    last = None
    for attempt in range(1, 16):                      # the database service may still be starting
        try:
            with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
                for f in migration_files():
                    conn.execute(f.read_text())
                    print(f"migrate: applied {f.name}")
            return 0
        except psycopg.OperationalError as exc:
            last = exc
            print(f"migrate: database not reachable yet (attempt {attempt}/15): {type(exc).__name__}", file=sys.stderr)
            time.sleep(2)
        except Exception as exc:  # noqa: BLE001
            print(f"migrate: FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    print(f"migrate: gave up: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
