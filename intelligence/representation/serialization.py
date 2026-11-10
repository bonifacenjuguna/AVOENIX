"""JSON (de)serialisation and schema migration for ACR documents.

Persisted ACR documents carry ``schema_version``. When the schema changes, a migration
function from the old version to the next is registered here; ``loads`` applies the chain
automatically so stored representations remain readable (safe evolution).
"""

from __future__ import annotations

import json
from typing import Callable

from ..core.errors import RepresentationError
from ..version import ACR_SCHEMA_VERSION
from .document import ACRDocument

Migration = Callable[[dict], dict]
_MIGRATIONS: dict[str, tuple[str, Migration]] = {}   # from_version -> (to_version, fn)


def register_migration(from_version: str, to_version: str, fn: Migration) -> None:
    if from_version in _MIGRATIONS:
        raise RepresentationError(f"migration from {from_version} already registered")
    _MIGRATIONS[from_version] = (to_version, fn)


def unregister_migration(from_version: str) -> None:
    """Test helper."""
    _MIGRATIONS.pop(from_version, None)


def migrate_dict(data: dict, *, target: str = ACR_SCHEMA_VERSION) -> dict:
    version = data.get("schema_version")
    if not version:
        raise RepresentationError("document has no schema_version")
    hops = 0
    while version != target:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise RepresentationError(
                f"no migration path from {version!r} to {target!r}",
                details={"from": version, "to": target},
            )
        next_version, fn = step
        data = fn(dict(data))
        data["schema_version"] = next_version
        version = next_version
        hops += 1
        if hops > 50:
            raise RepresentationError("migration chain too long (cycle?)")
    return data


def dumps(doc: ACRDocument, *, indent: int | None = None) -> str:
    return json.dumps(doc.to_dict(), ensure_ascii=False, indent=indent, sort_keys=False)


def loads(text: str, *, strict: bool = True) -> ACRDocument:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RepresentationError(f"invalid JSON: {exc}") from exc
    return from_dict(data, strict=strict)


def from_dict(data: dict, *, strict: bool = True) -> ACRDocument:
    data = migrate_dict(data)
    return ACRDocument.from_dict(data, strict=strict)
