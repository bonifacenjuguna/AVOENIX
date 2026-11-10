"""Shared lightweight types used across engines."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .errors import ScopeError

_SCOPE_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def new_id() -> str:
    """Opaque unique identifier (UUID4 string)."""
    return str(uuid.uuid4())


@dataclass(frozen=True)
class Scope:
    """Data-isolation scope. Every persistent read/write is bound to one.

    ``project_id`` isolates one integrating application from another.
    ``user_id`` isolates end users inside a project. Both are mandatory: there is no
    "global" scope that could accidentally leak data between applications.
    """

    project_id: str
    user_id: str

    def __post_init__(self) -> None:
        for name in ("project_id", "user_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SCOPE_RE.match(value):
                raise ScopeError(f"{name} must match {_SCOPE_RE.pattern}", details={"field": name})

    @property
    def key(self) -> str:
        return f"{self.project_id}/{self.user_id}"


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """Deterministic clock for tests and reproducible evaluation."""

    def __init__(self, moment: datetime):
        self._moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._moment

    def advance(self, **kwargs) -> None:
        from datetime import timedelta

        self._moment = self._moment + timedelta(**kwargs)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()
