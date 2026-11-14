"""Import pipeline: validate manifest -> hash and preserve raw input -> stream, normalise, deduplicate, cap confidence -> quality gate -> report."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from ..version import PLATFORM_VERSION
from .manifest import SourceManifest
from .readers import READERS
from .store import ProcessedStore

MAX_TERM_LEN = 64
_TERM_OK = re.compile(r"^[a-z][a-z0-9 '\-]*$")


@dataclass
class ImportReport:
    import_id: int
    source_id: str
    version: str
    status: str                       # active | skipped | failed
    input_sha256: str
    license: str
    redistributable: bool
    counts: dict = field(default_factory=dict)
    rejects: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        c = self.counts
        lines = [f"# Import report — {self.source_id} {self.version}", "", f"- status: **{self.status}**", f"- import id: {self.import_id}", f"- input sha256: `{self.input_sha256}`",
                 f"- licence: {self.license} (redistributable: {self.redistributable})", f"- records read: {c.get('read', 0)}, accepted: {c.get('accepted', 0)}, duplicates: {c.get('duplicates', 0)}, rejected: {c.get('rejected', 0)}"]
        if self.rejects:
            lines.append("- reject reasons: " + ", ".join(f"{k} ×{v}" for k, v in sorted(self.rejects.items())))
        for k, v in self.quality.items():
            lines.append(f"- quality/{k}: {v}")
        lines += [f"- note: {n}" for n in self.notes]
        return "\n".join(lines) + "\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalise_term(t: str) -> str | None:
    t = unicodedata.normalize("NFKC", t).strip().lower()
    t = re.sub(r"\s+", " ", t)
    if not t or len(t) > MAX_TERM_LEN or not _TERM_OK.match(t):
        return None
    return t


def import_source(manifest: SourceManifest, input_path: str | Path, store: ProcessedStore, *, accept_unknown_license: bool = False, max_reject_rate: float = 0.2,
                  min_records: int = 1) -> ImportReport:
    manifest.validate(accept_unknown_license)
    path = Path(input_path)
    sha = _sha256(path)
    con = store.con
    row = con.execute("SELECT id FROM imports WHERE source_id=? AND version=? AND input_sha256=? AND status='active'", (manifest.source_id, manifest.version, sha)).fetchone()
    if row:
        return ImportReport(row[0], manifest.source_id, manifest.version, "skipped", sha, manifest.license, bool(manifest.redistributable), notes=["identical input already imported; nothing changed"])
    con.execute("INSERT OR IGNORE INTO sources (source_id, manifest_json, first_seen) VALUES (?,?,?)", (manifest.source_id, json.dumps(manifest.to_dict(), sort_keys=True), _now()))
    cur = con.execute("INSERT INTO imports (source_id, version, input_name, input_sha256, started_at, status, code_version) VALUES (?,?,?,?,?,'running',?)",
                      (manifest.source_id, manifest.version, path.name, sha, _now(), PLATFORM_VERSION))
    import_id = cur.lastrowid
    raw_dest = store.root / "raw" / sha
    if not raw_dest.exists():
        shutil.copyfile(path, raw_dest)                                    # raw data preserved unmodified, separate from processed rows
    con.execute("INSERT INTO raw_files VALUES (?,?,?,?,?)", (import_id, path.name, sha, path.stat().st_size, str(raw_dest.relative_to(store.root))))
    con.commit()
    counts = {"read": 0, "accepted": 0, "duplicates": 0, "rejected": 0}
    rejects: dict[str, int] = {}
    reader = READERS[manifest.format]
    cap = manifest.confidence_cap
    try:
        for rec in reader(path, manifest.options):
            counts["read"] += 1
            kind = rec[0]
            ins = 0
            if kind == "reject":
                counts["rejected"] += 1
                key = re.sub(r"\d+", "N", rec[1])[:80]
                rejects[key] = rejects.get(key, 0) + 1
                continue
            if kind == "lemma":
                lem = normalise_term(rec[2])
                if lem is None:
                    counts["rejected"] += 1; rejects["invalid lemma"] = rejects.get("invalid lemma", 0) + 1; continue
                ins = con.execute("INSERT OR IGNORE INTO synset_lemmas VALUES (?,?,?,?,?)", (import_id, rec[1], lem, rec[3], manifest.source_id)).rowcount
            elif kind == "synset_relation":
                ins = con.execute("INSERT OR IGNORE INTO synset_relations VALUES (?,?,?,?)", (import_id, rec[1], rec[2], rec[3])).rowcount
            elif kind == "relation":
                a, b = normalise_term(rec[1]), normalise_term(rec[3])
                if a is None or b is None:
                    counts["rejected"] += 1; rejects["invalid term"] = rejects.get("invalid term", 0) + 1; continue
                ins = con.execute("INSERT OR IGNORE INTO relations VALUES (?,?,?,?,?,?,?)", (import_id, a, rec[2], b, min(cap, float(rec[4])), manifest.source_id, manifest.license)).rowcount
            elif kind == "statement":
                s, o = rec[1].strip(), rec[3].strip()
                if not s or not o or len(s) > 128 or len(o) > 128:
                    counts["rejected"] += 1; rejects["invalid statement"] = rejects.get("invalid statement", 0) + 1; continue
                ins = con.execute("INSERT OR IGNORE INTO statements VALUES (?,?,?,?,?,?,?,'candidate')", (import_id, s, rec[2], o, min(cap, float(rec[4])), manifest.source_id, manifest.license)).rowcount
            elif kind == "sentence":
                sent = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", rec[1])).strip()
                ins = con.execute("INSERT OR IGNORE INTO sentences VALUES (?,?,?)", (import_id, hashlib.sha1(sent.lower().encode()).hexdigest(), sent)).rowcount
            counts["accepted" if ins else "duplicates"] += 1
            if counts["read"] % 20000 == 0:
                con.commit()
        # lemma-level relations from synset pointers (bounded cross product)
        con.execute("""INSERT OR IGNORE INTO relations
                       SELECT r.import_id, a.lemma, r.rel, b.lemma, 0.8, ?, ? FROM synset_relations r
                       JOIN synset_lemmas a ON a.import_id=r.import_id AND a.synset_id=r.src
                       JOIN synset_lemmas b ON b.import_id=r.import_id AND b.synset_id=r.dst
                       WHERE r.import_id=? AND a.lemma<>b.lemma""", (manifest.source_id, manifest.license, import_id))
        total = max(1, counts["read"])
        reject_rate = counts["rejected"] / total
        quality = {"reject_rate": round(reject_rate, 4), "max_reject_rate": max_reject_rate, "min_records": min_records}
        if counts["accepted"] < min_records:
            raise ValueError(f"quality gate: only {counts['accepted']} usable records (minimum {min_records})")
        if reject_rate > max_reject_rate:
            raise ValueError(f"quality gate: reject rate {reject_rate:.1%} exceeds {max_reject_rate:.0%}")
        report = ImportReport(import_id, manifest.source_id, manifest.version, "active", sha, manifest.license, bool(manifest.redistributable), counts, rejects, quality,
                              [f"statements are stored as candidates with confidence <= {cap}; none is treated as true"] if con.execute("SELECT 1 FROM statements WHERE import_id=? LIMIT 1", (import_id,)).fetchone() else [])
        con.execute("UPDATE imports SET status='active', finished_at=?, counts_json=?, report_json=? WHERE id=?", (_now(), json.dumps(counts), json.dumps(report.to_dict()), import_id))
        con.commit()
        return report
    except Exception as e:
        con.rollback()
        for t in ("synset_lemmas", "synset_relations", "relations", "statements", "sentences"):
            con.execute(f"DELETE FROM {t} WHERE import_id=?", (import_id,))
        report = ImportReport(import_id, manifest.source_id, manifest.version, "failed", sha, manifest.license, bool(manifest.redistributable), counts, rejects, {}, [str(e)])
        con.execute("UPDATE imports SET status='failed', finished_at=?, counts_json=?, report_json=? WHERE id=?", (_now(), json.dumps(counts), json.dumps(report.to_dict()), import_id))
        con.commit()
        return report


def revert_import(store: ProcessedStore, import_id: int) -> bool:
    """Exclude an import from every query. Rows and raw data are kept for audit; ``restore_import`` undoes it."""
    cur = store.con.execute("UPDATE imports SET status='reverted' WHERE id=? AND status='active'", (import_id,))
    store.con.commit()
    return cur.rowcount == 1


def restore_import(store: ProcessedStore, import_id: int) -> bool:
    cur = store.con.execute("UPDATE imports SET status='active' WHERE id=? AND status='reverted'", (import_id,))
    store.con.commit()
    return cur.rowcount == 1


def list_imports(store: ProcessedStore) -> list[dict]:
    cols = ["id", "source_id", "version", "input_name", "input_sha256", "started_at", "finished_at", "status"]
    return [dict(zip(cols, r)) for r in store.con.execute(f"SELECT {', '.join(cols)} FROM imports ORDER BY id")]
