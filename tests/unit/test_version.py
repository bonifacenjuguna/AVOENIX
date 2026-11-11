"""Every place that states the platform version must agree on v0.0.1 (machine form 0.0.0 where the ecosystem forbids the 'v')."""
import json
import re
from pathlib import Path

from intelligence.version import PLATFORM_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_version_sources_agree():
    assert PLATFORM_VERSION == "v0.0.1"
    assert (ROOT / "VERSION").read_text().strip() == "v0.0.1"
    assert re.search(r'^version = "0\.0\.1"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert json.loads((ROOT / "apps/studio/package.json").read_text())["version"] == "0.0.1"


def test_docs_state_version():
    for f in ("README.md", "CHANGELOG.md", "docs/VERSIONING.md"):
        assert "v0.0.1" in (ROOT / f).read_text(), f
