"""Engine base class, metadata and real runtime metrics.

Metrics are measured, never simulated: ``EngineMetrics`` is updated by the ``@traced``
decorator on the engines' public operations, and Studio shows exactly these numbers.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class EngineStatus(str, Enum):
    IMPLEMENTED = "implemented"          # foundation works and is tested
    PARTIAL = "partial"                  # works for a deliberately narrow scope
    EXPERIMENTAL = "experimental"        # works but behaviour is unproven
    NOT_IMPLEMENTED = "not_implemented"


@dataclass(frozen=True)
class EngineInfo:
    key: str
    name: str
    status: EngineStatus
    summary: str
    depends_on: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    version: str = "0.0.0"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "status": self.status.value,
            "summary": self.summary,
            "depends_on": list(self.depends_on),
            "capabilities": list(self.capabilities),
            "limitations": list(self.limitations),
            "version": self.version,
        }


@dataclass
class EngineMetrics:
    calls: int = 0
    errors: int = 0
    total_ms: float = 0.0
    last_ms: float | None = None
    max_ms: float = 0.0
    last_error: str | None = None
    per_operation: dict[str, dict[str, float]] = field(default_factory=dict)

    def record(self, op: str, ms: float, error: BaseException | None) -> None:
        self.calls += 1
        self.total_ms += ms
        self.last_ms = ms
        self.max_ms = max(self.max_ms, ms)
        slot = self.per_operation.setdefault(op, {"calls": 0, "errors": 0, "total_ms": 0.0})
        slot["calls"] += 1
        slot["total_ms"] += ms
        if error is not None:
            self.errors += 1
            slot["errors"] += 1
            self.last_error = f"{type(error).__name__}: {error}"

    def to_dict(self) -> dict:
        avg = (self.total_ms / self.calls) if self.calls else None
        return {
            "calls": self.calls,
            "errors": self.errors,
            "avg_ms": round(avg, 3) if avg is not None else None,
            "last_ms": round(self.last_ms, 3) if self.last_ms is not None else None,
            "max_ms": round(self.max_ms, 3) if self.calls else None,
            "last_error": self.last_error,
            "per_operation": {
                k: {
                    "calls": int(v["calls"]),
                    "errors": int(v["errors"]),
                    "avg_ms": round(v["total_ms"] / v["calls"], 3) if v["calls"] else None,
                }
                for k, v in self.per_operation.items()
            },
        }


@dataclass
class EngineHealth:
    key: str
    status: str            # "ok" | "degraded" | "failed"
    detail: str
    metrics: dict

    def to_dict(self) -> dict:
        return {"key": self.key, "status": self.status, "detail": self.detail, "metrics": self.metrics}


def traced(operation: str | None = None) -> Callable[[F], F]:
    """Record real timing/error metrics for an engine method."""

    def decorator(fn: F) -> F:
        op = operation or fn.__name__

        @functools.wraps(fn)
        def wrapper(self: "Engine", *args: Any, **kwargs: Any):
            start = time.perf_counter()
            error: BaseException | None = None
            try:
                return fn(self, *args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - recorded then re-raised
                error = exc
                raise
            finally:
                self.metrics.record(op, (time.perf_counter() - start) * 1000.0, error)

        return wrapper  # type: ignore[return-value]

    return decorator


class Engine:
    """Base class for the twelve engines."""

    info: EngineInfo

    def __init__(self) -> None:
        self.metrics = EngineMetrics()

    def self_check(self) -> tuple[bool, str]:
        """Cheap functional probe. Engines override to exercise real code paths."""
        return True, "no self-check defined"

    def health(self) -> EngineHealth:
        try:
            ok, detail = self.self_check()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"self-check raised {type(exc).__name__}: {exc}"
        status = "ok" if ok else "failed"
        if ok and self.metrics.calls and self.metrics.errors / max(1, self.metrics.calls) > 0.2:
            status = "degraded"
            detail += " (error rate above 20% of recorded calls)"
        return EngineHealth(self.info.key, status, detail, self.metrics.to_dict())
