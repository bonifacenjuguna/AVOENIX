"""Offline data ingestion: external lexical/knowledge resources -> a separate processed SQLite store with provenance, licence and versioned imports.

Nothing here runs during a conversation. The conversation path only *reads* the processed store (read-only connection) through
``intelligence.meaning.lexicon.ConceptGraph.extend_from_store``; raw data and processed representations are kept apart, imports are reversible,
and an imported statement is a *candidate* with a capped confidence, never an accepted fact.
"""
from .manifest import SourceManifest, ManifestError
from .pipeline import ImportReport, import_source, revert_import, restore_import, list_imports
from .store import ProcessedStore

__all__ = ["SourceManifest", "ManifestError", "ImportReport", "import_source", "revert_import", "restore_import", "list_imports", "ProcessedStore"]
