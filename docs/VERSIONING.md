# Versioning policy

- **Platform version:** `v0.0.0` (single source: `VERSION`; mirrored in `intelligence/version.py`, `pyproject.toml`, `apps/studio/package.json`). Semantic Versioning 2.0.0.
- `0.y.z`: initial development; any minor bump may break compatibility. `1.0.0` will be declared only when the public API and ACR schema are considered stable.
- **API version** (`/v1`) is independent of the platform version. It changes only on breaking HTTP changes.
- **ACR schema** (`acr/1.0`) is versioned separately; `representation/serialization.register_migration` upgrades older documents.
- **Database schema** (`0001`) is versioned by migration number; migrations are forward-only in v0.0.0.
- Every release updates `CHANGELOG.md`. No component may claim a version other than the platform version except the three independent versions above.
