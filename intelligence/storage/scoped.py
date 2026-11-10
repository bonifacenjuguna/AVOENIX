"""Scoped repository: the single choke point that enforces project/user data isolation.

Every engine that touches user-owned data does so through a ``ScopedRepo`` bound to a ``Scope``. The wrapper
adds ``project_id`` and ``user_id`` to every WHERE clause and stamps them on every INSERT, so a bug in an
engine cannot read or write another user's rows by forgetting a filter. Updating/deleting rows of another
scope simply matches zero rows.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import ScopeError, StorageError
from ..core.types import Scope
from .backend import Backend, Row, Where, table_spec


class ScopedRepo:
    def __init__(self, backend: Backend, scope: Scope):
        self.backend = backend
        self.scope = scope

    def _where(self, table: str, where: Where | None) -> Where:
        spec = table_spec(table)
        if not spec.scoped:
            raise StorageError(f"table {table} is not a scoped table")
        out = dict(where or {})
        for key, expected in (("project_id", self.scope.project_id), ("user_id", self.scope.user_id)):
            if key in out and out[key] != expected:
                raise ScopeError(f"attempt to override {key} outside the bound scope")
            out[key] = expected
        return out

    def insert(self, table: str, row: Row) -> Row:
        spec = table_spec(table)
        if not spec.scoped:
            raise StorageError(f"table {table} is not a scoped table")
        for key, expected in (("project_id", self.scope.project_id), ("user_id", self.scope.user_id)):
            if row.get(key) not in (None, expected):
                raise ScopeError(f"row {key} does not match the bound scope")
        return self.backend.insert(table, {**row, "project_id": self.scope.project_id, "user_id": self.scope.user_id})

    def select(self, table: str, where: Where | None = None, **kw: Any) -> list[Row]:
        return self.backend.select(table, self._where(table, where), **kw)

    def get(self, table: str, where: Where) -> Row | None:
        rows = self.select(table, where, limit=1)
        return rows[0] if rows else None

    def update(self, table: str, where: Where, values: Row) -> int:
        values = {k: v for k, v in values.items() if k not in ("project_id", "user_id")}
        return self.backend.update(table, self._where(table, where), values)

    def delete(self, table: str, where: Where) -> int:
        return self.backend.delete(table, self._where(table, where))

    def count(self, table: str, where: Where | None = None) -> int:
        return self.backend.count(table, self._where(table, where))
