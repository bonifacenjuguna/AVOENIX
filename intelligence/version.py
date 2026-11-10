"""Single source of truth for AVOENIX version metadata.

The official initial release label is ``v0.0.0``. Ecosystem metadata (PEP 440 in
``pyproject.toml`` and semver in ``package.json``) cannot carry the leading ``v``,
so the machine form is ``0.0.0``. The two forms always describe the same release;
``tests/unit/test_version.py`` enforces that every place agrees.

Three independent version axes exist:

* PLATFORM_VERSION  - the AVOENIX platform release (MAJOR.MINOR.PATCH).
* API_VERSION       - the public HTTP API contract (``/v1``), versioned independently.
* ACR_SCHEMA_VERSION - the stored cognitive-representation schema, versioned independently
                       so persisted representations can be migrated safely.
"""

PLATFORM_VERSION = "v0.0.0"
SEMVER = "0.0.0"
API_VERSION = "v1"
ACR_SCHEMA_VERSION = "acr/1.0"
DATABASE_SCHEMA_VERSION = "0001"

__all__ = [
    "PLATFORM_VERSION",
    "SEMVER",
    "API_VERSION",
    "ACR_SCHEMA_VERSION",
    "DATABASE_SCHEMA_VERSION",
]
