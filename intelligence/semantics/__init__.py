"""Distributional semantics (offline build, read-only at conversation time). Standard library only."""
from .distributional import CoocBuilder, VectorStore, build_vectors, typed_relation

__all__ = ["CoocBuilder", "VectorStore", "build_vectors", "typed_relation"]
