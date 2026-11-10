"""AVOENIX intelligence core.

Framework-independent: nothing in this package imports FastAPI, a web framework or
a database driver at import time. The core can run locally, in tests, or be embedded
in another application.
"""

from .version import PLATFORM_VERSION, SEMVER, API_VERSION, ACR_SCHEMA_VERSION

__version__ = SEMVER
__all__ = ["PLATFORM_VERSION", "SEMVER", "API_VERSION", "ACR_SCHEMA_VERSION", "__version__"]
