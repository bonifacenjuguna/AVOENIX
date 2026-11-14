# Versioning policy

- **Platform version:** `v0.1.0` (initial release `v0.0.0`; single source: `VERSION`; mirrored in `intelligence/version.py`, `pyproject.toml`, `apps/studio/package.json`). Semantic Versioning 2.0.0.
- `0.y.z`: initial development; any minor bump may break compatibility. `1.0.0` will be declared only when the public API and ACR schema are considered stable.
- **API version** (`/v1`) is independent of the platform version. It changes only on breaking HTTP changes.
- **ACR schema** (`acr/1.0`) is versioned separately; `representation/serialization.register_migration` upgrades older documents.
- **Claim schema** (`claim/1.0`) is versioned separately (`intelligence/representation/claims.py`).
- **Database schema** (`0002`) is versioned by migration number (`schema_info`); `0002` is additive and idempotent and ships a tested rollback script (`0002_knowledge_integrity_down.sql`).
- Every release updates `CHANGELOG.md`. No component may claim a version other than the platform version except the three independent versions above.
