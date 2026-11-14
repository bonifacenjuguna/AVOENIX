"""Processed store (SQLite). Raw files are preserved byte-for-byte under ``raw/<sha256>``; processed rows live in the database and always carry their
import id, so an import can be inspected, excluded (revert) or restored without touching raw data."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (source_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, first_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, version TEXT NOT NULL, input_name TEXT NOT NULL, input_sha256 TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL CHECK (status IN ('running','active','reverted','failed','skipped')),
  counts_json TEXT, report_json TEXT, code_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raw_files (import_id INTEGER NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, raw_path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS synset_lemmas (import_id INTEGER NOT NULL, synset_id TEXT NOT NULL, lemma TEXT NOT NULL, pos TEXT NOT NULL, source TEXT NOT NULL,
  UNIQUE (import_id, synset_id, lemma));
CREATE TABLE IF NOT EXISTS synset_relations (import_id INTEGER NOT NULL, src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, UNIQUE (import_id, src, rel, dst));
CREATE TABLE IF NOT EXISTS relations (import_id INTEGER NOT NULL, src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, weight REAL NOT NULL, source TEXT NOT NULL,
  license TEXT NOT NULL, UNIQUE (import_id, src, rel, dst));
CREATE TABLE IF NOT EXISTS statements (import_id INTEGER NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL, confidence REAL NOT NULL,
  source TEXT NOT NULL, license TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', UNIQUE (import_id, subject, predicate, object));
CREATE TABLE IF NOT EXISTS sentences (import_id INTEGER NOT NULL, sha TEXT NOT NULL, text TEXT NOT NULL, UNIQUE (sha));
CREATE INDEX IF NOT EXISTS ix_lemmas_lemma ON synset_lemmas (lemma);
CREATE INDEX IF NOT EXISTS ix_relations_src ON relations (src);
CREATE INDEX IF NOT EXISTS ix_statements_sp ON statements (subject, predicate);
"""


class ProcessedStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        self.db_path = self.root / "processed.sqlite"
        self.con = sqlite3.connect(self.db_path)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "ProcessedStore":
        return self

    def __exit__(self, *a) -> None:
        self.close()
