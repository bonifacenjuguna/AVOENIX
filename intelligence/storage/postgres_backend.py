"""PostgreSQL backend.

SQL is generated only from the whitelisted table/column spec; values are always bound parameters. The
backend talks to PostgreSQL through a tiny ``Database`` adapter so the same SQL generation can be used with
psycopg 3 (production, ``PsycopgDatabase``) and with other adapters (e.g. the psql-subprocess adapter that
``tests/integration`` uses when psycopg is not installable).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator, Protocol, Sequence

from ..core.errors import ConflictError, StorageError
from .backend import Backend, Row, Where, check_columns, table_spec
from .schema import Table


class Database(Protocol):
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Run one statement and return rows (empty list when the statement returns none)."""

    def transaction(self): ...   # context manager

    def close(self) -> None: ...


class PsycopgDatabase:
    """Production adapter: psycopg 3 + psycopg_pool (``pip install "psycopg[binary,pool]"``)."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8, connect_timeout: int = 10):
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - exercised only where psycopg is installed
            raise StorageError("psycopg and psycopg_pool are required for PostgreSQL: pip install 'psycopg[binary,pool]'") from exc
        self._psycopg = psycopg
        self._pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, kwargs={"row_factory": dict_row, "connect_timeout": connect_timeout,
                                                                                         "autocommit": True}, open=True)
        self._local = __import__("threading").local()

    def _conn(self):
        return getattr(self._local, "conn", None)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:  # pragma: no cover
        conn = self._conn()
        try:
            if conn is not None:
                cur = conn.execute(sql, params)
                return cur.fetchall() if cur.description else []
            with self._pool.connection() as c:
                cur = c.execute(sql, params)
                return cur.fetchall() if cur.description else []
        except self._psycopg.errors.UniqueViolation as exc:
            raise ConflictError("unique constraint violated", details={"constraint": getattr(exc.diag, "constraint_name", None)}) from exc
        except self._psycopg.Error as exc:
            raise StorageError(f"database error: {exc.__class__.__name__}") from exc

    @contextmanager
    def transaction(self):  # pragma: no cover
        with self._pool.connection() as conn:
            self._local.conn = conn
            try:
                with conn.transaction():
                    yield
            finally:
                self._local.conn = None

    def close(self) -> None:  # pragma: no cover
        self._pool.close()


def _norm_value(spec: Table, col: str, value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if col in spec.json_columns and isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class PostgresBackend(Backend):
    name = "postgresql"

    def __init__(self, db: Database):
        self.db = db

    # ---- SQL generation -----------------------------------------------------------------------------
    @staticmethod
    def _bind(spec: Table, col: str, value: Any) -> tuple[str, Any]:
        if col in spec.json_columns:
            return "%s::jsonb", (None if value is None else json.dumps(value))
        if col in spec.timestamps and value is not None:
            return "%s::timestamptz", value if isinstance(value, str) else value.isoformat()
        return "%s", value

    def _where(self, spec: Table, where: Where | None) -> tuple[str, list[Any]]:
        if not where:
            return "", []
        check_columns(spec, where.keys())
        clauses, params = [], []
        for col, cond in where.items():
            if isinstance(cond, tuple):
                op, *args = cond
                arg = args[0] if args else None
                if op in ("ne", "lt", "lte", "gt", "gte"):
                    sym = {"ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[op]
                    ph, val = self._bind(spec, col, arg)
                    if op == "ne":
                        clauses.append(f'("{col}" IS DISTINCT FROM {ph})')
                    else:
                        clauses.append(f'"{col}" {sym} {ph}')
                    params.append(val)
                elif op == "in":
                    if not arg:
                        clauses.append("false")
                    else:
                        clauses.append(f'"{col}" IN ({", ".join(["%s"] * len(arg))})')
                        params.extend(arg)
                elif op == "like":
                    clauses.append(f'"{col}" ILIKE %s')
                    params.append(arg)
                elif op == "null":
                    clauses.append(f'"{col}" IS NULL')
                elif op == "notnull":
                    clauses.append(f'"{col}" IS NOT NULL')
                elif op == "contains":
                    clauses.append(f'"{col}" @> %s::jsonb')
                    params.append(json.dumps(arg))
                else:
                    raise StorageError(f"unknown where operator {op!r}")
            elif cond is None:
                clauses.append(f'"{col}" IS NULL')
            else:
                ph, val = self._bind(spec, col, cond)
                clauses.append(f'"{col}" = {ph}')
                params.append(val)
        return " WHERE " + " AND ".join(clauses), params

    def _norm_row(self, spec: Table, row: dict[str, Any]) -> Row:
        return {k: _norm_value(spec, k, v) for k, v in row.items()}

    # ---- interface ---------------------------------------------------------------------------------------
    def insert(self, table: str, row: Row) -> Row:
        spec = table_spec(table)
        check_columns(spec, row.keys())
        cols = [c for c, v in row.items() if v is not None]
        if not cols:
            raise StorageError("nothing to insert")
        phs, params = [], []
        for c in cols:
            ph, val = self._bind(spec, c, row[c])
            phs.append(ph)
            params.append(val)
        sql = f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({", ".join(phs)}) RETURNING *'
        rows = self.db.query(sql, params)
        return self._norm_row(spec, rows[0]) if rows else {}

    def select(self, table: str, where: Where | None = None, *, order: list[str] | None = None, limit: int | None = None,
               offset: int = 0) -> list[Row]:
        spec = table_spec(table)
        wsql, params = self._where(spec, where)
        sql = f'SELECT * FROM "{table}"{wsql}'
        if order:
            parts = []
            for o in order:
                col = o.lstrip("-")
                check_columns(spec, [col])
                parts.append(f'"{col}" {"DESC" if o.startswith("-") else "ASC"} NULLS LAST')
            sql += " ORDER BY " + ", ".join(parts)
        if limit is not None:
            sql += " LIMIT %s"
            params.append(int(limit))
        if offset:
            sql += " OFFSET %s"
            params.append(int(offset))
        return [self._norm_row(spec, r) for r in self.db.query(sql, params)]

    def update(self, table: str, where: Where, values: Row) -> int:
        spec = table_spec(table)
        check_columns(spec, values.keys())
        if not values:
            return 0
        sets, params = [], []
        for c, v in values.items():
            ph, val = self._bind(spec, c, v)
            sets.append(f'"{c}" = {ph}')
            params.append(val)
        wsql, wparams = self._where(spec, where)
        sql = f'UPDATE "{table}" SET {", ".join(sets)}{wsql} RETURNING 1 AS n'
        return len(self.db.query(sql, params + wparams))

    def delete(self, table: str, where: Where) -> int:
        spec = table_spec(table)
        wsql, params = self._where(spec, where)
        return len(self.db.query(f'DELETE FROM "{table}"{wsql} RETURNING 1 AS n', params))

    def count(self, table: str, where: Where | None = None) -> int:
        spec = table_spec(table)
        wsql, params = self._where(spec, where)
        rows = self.db.query(f'SELECT count(*) AS n FROM "{table}"{wsql}', params)
        return int(rows[0]["n"]) if rows else 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.db.transaction():
            yield

    def ping(self) -> tuple[bool, str]:
        try:
            rows = self.db.query("SELECT 1 AS ok", [])
            ver = self.db.query("SELECT value FROM schema_info WHERE key = %s", ["schema_revision"])
            return bool(rows), f"postgresql reachable; schema_revision={ver[0]['value'] if ver else 'not installed'}"
        except Exception as exc:  # noqa: BLE001
            return False, f"postgresql unreachable: {type(exc).__name__}"

    def close(self) -> None:
        self.db.close()
