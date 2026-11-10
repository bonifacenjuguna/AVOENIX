"""In-memory backend (tests, local experiments, isolated development).

It mirrors PostgreSQL semantics closely enough for the repositories: unique primary keys, JSON deep-copy
isolation, ordering and the where-operators. It is NOT the online store; PostgreSQL is. An optional JSON-file
snapshot makes "restart" tests possible without a database.
"""

from __future__ import annotations

import copy
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..core.errors import ConflictError, StorageError
from .backend import Backend, Row, Where, check_columns, table_spec


def _subset(needle: Any, hay: Any) -> bool:
    if isinstance(needle, dict):
        return isinstance(hay, dict) and all(k in hay and _subset(v, hay[k]) for k, v in needle.items())
    if isinstance(needle, list):
        return isinstance(hay, list) and all(any(_subset(n, h) for h in hay) for n in needle)
    return needle == hay


def _match(row: Row, where: Where | None) -> bool:
    if not where:
        return True
    for col, cond in where.items():
        val = row.get(col)
        if isinstance(cond, tuple):
            op, *args = cond
            arg = args[0] if args else None
            if op == "ne" and not (val != arg):
                return False
            if op == "lt" and not (val is not None and val < arg):
                return False
            if op == "lte" and not (val is not None and val <= arg):
                return False
            if op == "gt" and not (val is not None and val > arg):
                return False
            if op == "gte" and not (val is not None and val >= arg):
                return False
            if op == "in" and val not in arg:
                return False
            if op == "like":
                import re
                pat = "^" + re.escape(arg).replace("%", ".*").replace("_", ".") + "$"
                if val is None or not re.match(pat, str(val), re.I | re.S):
                    return False
            if op == "null" and val is not None:
                return False
            if op == "notnull" and val is None:
                return False
            if op == "contains" and not _subset(arg, val):
                return False
        elif val != cond:
            return False
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryBackend(Backend):
    name = "memory"

    def __init__(self, snapshot_path: str | Path | None = None) -> None:
        self._tables: dict[str, list[Row]] = {}
        self._seq: dict[str, int] = {}
        self._lock = threading.RLock()
        self._snapshot = Path(snapshot_path) if snapshot_path else None
        if self._snapshot and self._snapshot.exists():
            data = json.loads(self._snapshot.read_text())
            self._tables, self._seq = data["tables"], data["seq"]

    def _rows(self, table: str) -> list[Row]:
        return self._tables.setdefault(table, [])

    def _pk_values(self, spec, row: Row) -> tuple:
        return tuple(row.get(c) for c in spec.pk.split(","))

    def insert(self, table: str, row: Row) -> Row:
        spec = table_spec(table)
        check_columns(spec, row.keys())
        with self._lock:
            new = {c: None for c in spec.columns}
            new.update(copy.deepcopy(row))
            if spec.auto_pk and new.get(spec.pk) is None:
                self._seq[table] = self._seq.get(table, 0) + 1
                new[spec.pk] = self._seq[table]
            for col in ("created_at", "updated_at", "at"):
                if col in spec.columns and new.get(col) is None:
                    new[col] = _now_iso()
            defaults = {"status": None}
            for pkv in [self._pk_values(spec, new)]:
                if any(self._pk_values(spec, r) == pkv for r in self._rows(table)):
                    raise ConflictError(f"duplicate primary key in {table}: {pkv}")
            self._apply_unique(table, new)
            self._rows(table).append(new)
            self._persist()
            return copy.deepcopy(new)

    def _apply_unique(self, table: str, new: Row) -> None:
        uniques = {"users": ("email_lower",), "sessions": ("token_hash",), "api_keys": ("key_hash",)}
        if table == "users":
            if any(r["email"].lower() == new["email"].lower() for r in self._rows(table)):
                raise ConflictError("email already registered")
        elif table in uniques:
            col = uniques[table][0]
            if any(r.get(col) == new.get(col) for r in self._rows(table)):
                raise ConflictError(f"duplicate {col} in {table}")

    def select(self, table: str, where: Where | None = None, *, order: list[str] | None = None, limit: int | None = None,
               offset: int = 0) -> list[Row]:
        spec = table_spec(table)
        if where:
            check_columns(spec, where.keys())
        with self._lock:
            rows = [r for r in self._rows(table) if _match(r, where)]
            for spec_o in reversed(order or []):
                desc = spec_o.startswith("-")
                col = spec_o.lstrip("-")
                check_columns(spec, [col])
                rows.sort(key=lambda r, c=col: (r.get(c) is None, r.get(c)), reverse=desc)
            if offset:
                rows = rows[offset:]
            if limit is not None:
                rows = rows[:limit]
            return copy.deepcopy(rows)

    def update(self, table: str, where: Where, values: Row) -> int:
        spec = table_spec(table)
        check_columns(spec, values.keys())
        check_columns(spec, where.keys())
        with self._lock:
            n = 0
            for r in self._rows(table):
                if _match(r, where):
                    r.update(copy.deepcopy(values))
                    n += 1
            if n:
                self._persist()
            return n

    def delete(self, table: str, where: Where) -> int:
        spec = table_spec(table)
        check_columns(spec, where.keys())
        with self._lock:
            keep, gone = [], 0
            for r in self._rows(table):
                if _match(r, where):
                    gone += 1
                else:
                    keep.append(r)
            self._tables[table] = keep
            if gone:
                self._cascade(table, gone and where)
                self._persist()
            return gone

    def _cascade(self, table: str, where: Where) -> None:
        """Emulate the ON DELETE CASCADE relations that matter for isolation tests."""
        if table == "conversations":
            ids = {r["id"] for r in self._rows("messages")} - {r["conversation_id"] for r in self._rows("conversations")}
            self._tables["messages"] = [r for r in self._rows("messages") if r["conversation_id"] in
                                        {c["id"] for c in self._rows("conversations")}]
            self._tables["turn_traces"] = [r for r in self._rows("turn_traces") if r["conversation_id"] in
                                           {c["id"] for c in self._rows("conversations")}]
        if table == "knowledge_facts":
            live = {r["id"] for r in self._rows("knowledge_facts")}
            self._tables["knowledge_terms"] = [r for r in self._rows("knowledge_terms") if r["fact_id"] in live]

    def count(self, table: str, where: Where | None = None) -> int:
        spec = table_spec(table)
        if where:
            check_columns(spec, where.keys())
        with self._lock:
            return sum(1 for r in self._rows(table) if _match(r, where))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            before = copy.deepcopy((self._tables, self._seq))
            try:
                yield
            except BaseException:
                self._tables, self._seq = before
                raise

    def _persist(self) -> None:
        if self._snapshot is None:
            return
        tmp = self._snapshot.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tables": self._tables, "seq": self._seq}))
        tmp.replace(self._snapshot)
