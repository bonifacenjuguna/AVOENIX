"""Error hierarchy. Every failure the core raises is an ``AvoenixError``."""

from __future__ import annotations


class AvoenixError(Exception):
    """Base class for all AVOENIX errors."""

    code = "avoenix_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class InputError(AvoenixError):
    """The incoming input is invalid (empty, too long, wrong type...)."""

    code = "invalid_input"


class UnsupportedLanguageError(InputError):
    """Input does not look like English, the only supported language in v0.0.0."""

    code = "unsupported_language"


class RepresentationError(AvoenixError):
    """An ACR structure is malformed or cannot be (de)serialised."""

    code = "invalid_representation"


class ScopeError(AvoenixError):
    """Missing or malformed data-isolation scope (project/user)."""

    code = "invalid_scope"


class StorageError(AvoenixError):
    code = "storage_error"


class NotFoundError(AvoenixError):
    code = "not_found"


class ConflictError(AvoenixError):
    code = "conflict"


class EngineError(AvoenixError):
    """An engine failed while performing an operation."""

    code = "engine_error"

    def __init__(self, engine: str, operation: str, message: str, *, cause: BaseException | None = None):
        super().__init__(
            f"{engine}.{operation}: {message}",
            details={"engine": engine, "operation": operation},
        )
        self.engine = engine
        self.operation = operation
        self.cause = cause


class LearningRejected(AvoenixError):
    """A proposed learning update was rejected by a safeguard."""

    code = "learning_rejected"
