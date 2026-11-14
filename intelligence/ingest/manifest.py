"""Source manifest: what a dataset is, where it came from, under which licence, and what we are allowed to do with it."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

FORMATS = ("wordnet_wndb", "conceptnet_csv", "wikidata_jsonl", "text_corpus")
# Licences the project knows how to describe. Unknown licences are refused unless the operator accepts them explicitly.
KNOWN_LICENSES = {
    "CC0-1.0": {"redistribute": True, "share_alike": False, "attribution": False},
    "CC-BY-4.0": {"redistribute": True, "share_alike": False, "attribution": True},
    "CC-BY-SA-4.0": {"redistribute": True, "share_alike": True, "attribution": True},
    "WordNet-3.0": {"redistribute": True, "share_alike": False, "attribution": True},   # Princeton WordNet licence: permissive with notice
    "MIT": {"redistribute": True, "share_alike": False, "attribution": True},
    "Apache-2.0": {"redistribute": True, "share_alike": False, "attribution": True},
    "ODbL-1.0": {"redistribute": True, "share_alike": True, "attribution": True},
}


class ManifestError(ValueError):
    pass


@dataclass
class SourceManifest:
    source_id: str
    name: str
    version: str
    format: str
    license: str
    license_url: str = ""
    attribution: str = ""
    homepage: str = ""
    language: str = "en"
    redistributable: bool | None = None
    confidence_cap: float = 0.6                       # imported statements never exceed this, whatever the source claims
    options: dict = field(default_factory=dict)

    def validate(self, accept_unknown_license: bool = False) -> "SourceManifest":
        for f in ("source_id", "name", "version", "format", "license"):
            if not getattr(self, f):
                raise ManifestError(f"manifest field '{f}' is required")
        if self.format not in FORMATS:
            raise ManifestError(f"unsupported format '{self.format}' (supported: {', '.join(FORMATS)})")
        info = KNOWN_LICENSES.get(self.license)
        if info is None and not accept_unknown_license:
            raise ManifestError(f"licence '{self.license}' is not in the known list; pass accept_unknown_license=True after reading it")
        if info and info["attribution"] and not self.attribution:
            raise ManifestError(f"licence '{self.license}' requires attribution text in the manifest")
        if not 0.0 < self.confidence_cap <= 0.8:
            raise ManifestError("confidence_cap must be in (0, 0.8]: imported data may not be treated as established")
        if self.redistributable is None:
            self.redistributable = bool(info and info["redistribute"])
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str | Path) -> "SourceManifest":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
