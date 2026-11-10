"""Storage backend interface and the shared where-clause vocabulary.

Where-clause values are either a plain value (equality) or an operator tuple:

    ("ne", v) ("lt", v) ("lte", v) ("gt", v) ("gte", v) ("in", [..]) ("like", "%x%") ("null",) ("notnull",)
    ("contains", {...})        # jsonb containment: column @> value   (in-memory: recursive subset test)

All identifiers (tables, columns) are validated against ``schema.TABLES`` by the backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterator

from ..core.errors import StorageError
from .schema import TABLES, Table

Row = dict[str, Any]
Where = dict[str, Any]


def table_spec(name: str) -> Table:
    try:
        return TABLES[name]
    except KeyError:
        raise StorageError(f"unknown table {name!r}") from None


def check_columns(table: Table, cols) -> None:
    bad = [c for c in cols if c not in table.columns]
    if bad:
        raise StorageError(f"unknown column(s) {bad} for table {table.name}")


class Backend(ABC):
    """Minimal relational interface used by all repositories."""

    name = "abstract"

    @abstractmethod
    def insert(self, table: str, row: Row) -> Row: ...

    @abstractmethod
    def select(self, table: str, where: Where | None = None, *, order: list[str] | None = None, limit: int | None = None,
               offset: int = 0) -> list[Row]: ...

    @abstractmethod
    def update(self, table: str, where: Where, values: Row) -> int: ...

    @abstractmethod
    def delete(self, table: str, where: Where) -> int: ...

    @abstractmethod
    def count(self, table: str, where: Where | None = None) -> int: ...

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def get(self, table: str, where: Where) -> Row | None:
        rows = self.select(table, where, limit=1)
        return rows[0] if rows else None

    def ping(self) -> tuple[bool, str]:
        return True, f"{self.name} backend"

    def close(self) -> None:
        return None
