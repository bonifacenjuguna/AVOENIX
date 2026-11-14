"""Concept graph: lemma -> concept clusters with typed relations (synonym / hypernym / antonym / related) and provenance per edge.

The graph is built from (1) the shipped seed lexicon and (2) any imported resources in a processed SQLite store (``intelligence/ingest``).
Imported synonym sets *extend* the seed: an unseen lemma that shares a synset with a seed lemma is mapped to that seed concept with the
edge's confidence, so coverage grows with data rather than with code. Similarity is never equivalence: only ``synonym`` / ``same`` edges
make two lemmas interchangeable; ``related`` and distributional similarity do not.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
EQUIVALENT = ("same", "synonym")


@dataclass(frozen=True)
class ConceptMatch:
    concept: str
    confidence: float
    via: str            # "seed" | "imported:<source>"


class ConceptGraph:
    def __init__(self) -> None:
        self.lemma_index: dict[str, dict[str, ConceptMatch]] = {}       # lemma -> {concept: match}
        self.concepts: dict[str, dict] = {}
        self.edges: dict[str, list[tuple[str, str, float, str]]] = {}   # concept -> [(rel, other, confidence, source)]

    # ---- building -------------------------------------------------------------------------------------------------------------------------
    def add_concept(self, cid: str, pos: str, lemmas: list[str], source: str = "seed", confidence: float = 1.0) -> None:
        self.concepts.setdefault(cid, {"pos": pos, "lemmas": []})
        for lem in lemmas:
            lem = lem.lower()
            if lem not in self.concepts[cid]["lemmas"]:
                self.concepts[cid]["lemmas"].append(lem)
            cur = self.lemma_index.setdefault(lem, {})
            if cid not in cur or cur[cid].confidence < confidence:
                cur[cid] = ConceptMatch(cid, confidence, source)

    def add_edge(self, a: str, rel: str, b: str, confidence: float = 1.0, source: str = "seed") -> None:
        self.edges.setdefault(a, []).append((rel, b, confidence, source))
        inverse = {"antonym": "antonym", "synonym": "synonym", "related": "related", "same": "same", "hypernym": "hyponym", "hyponym": "hypernym"}.get(rel)
        if inverse:
            self.edges.setdefault(b, []).append((inverse, a, confidence, source))

    @classmethod
    def from_seed(cls, path: Path | None = None) -> "ConceptGraph":
        g = cls()
        data = json.loads((path or DATA / "seed_lexicon.json").read_text(encoding="utf-8"))
        for cid, c in data["concepts"].items():
            g.add_concept(cid, c["pos"], c["lemmas"])
        for a, rel, b in data["relations"]:
            g.add_edge(a, rel, b)
        return g

    def extend_from_store(self, db_path: Path, min_confidence: float = 0.5) -> int:
        """Map imported lemmas onto seed concepts through shared synsets. Returns the number of lemma->concept links added."""
        if not Path(db_path).exists():
            return 0
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            added = 0
            rows = con.execute("SELECT s.synset_id, s.lemma, s.pos, s.source FROM synset_lemmas s JOIN imports i ON i.id = s.import_id WHERE i.status = 'active'").fetchall()
            by_synset: dict[str, list[tuple[str, str, str]]] = {}
            for sid, lemma, pos, src in rows:
                by_synset.setdefault(sid, []).append((lemma.lower(), pos, src))
            for members in by_synset.values():
                known = {c.concept for lem, _, _ in members for c in self.lemma_index.get(lem, {}).values() if c.via == "seed"}
                for lem, pos, src in members:
                    for cid in known:
                        if cid in self.lemma_index.get(lem, {}):
                            continue
                        if self.concepts[cid]["pos"][:1] != pos[:1]:
                            continue                                  # never cross parts of speech
                        conf = 0.7 if len(known) == 1 else 0.5        # a synset touching several seed concepts is ambiguous: lower confidence
                        if conf >= min_confidence:
                            self.lemma_index.setdefault(lem, {})[cid] = ConceptMatch(cid, conf, f"imported:{src}")
                            added += 1
            for a, rel, b, w, src in con.execute("SELECT r.src, r.rel, r.dst, r.weight, r.source FROM relations r JOIN imports i ON i.id = r.import_id WHERE i.status = 'active'"):
                ca, cb = self.lemma_index.get(a.lower()), self.lemma_index.get(b.lower())
                if ca and cb and rel in ("antonym", "synonym", "hypernym", "related"):
                    for x in ca:
                        for y in cb:
                            if x != y:
                                self.add_edge(x, rel, y, min(1.0, float(w)), f"imported:{src}")
            return added
        finally:
            con.close()

    # ---- queries --------------------------------------------------------------------------------------------------------------------------
    def concepts_of(self, lemma: str, pos: str | None = None, strict: bool = False) -> list[ConceptMatch]:
        """Concepts a lemma can express. With ``pos`` the matching part of speech is preferred; ``strict`` drops the others instead of falling back."""
        out = list(self.lemma_index.get((lemma or "").lower(), {}).values())
        if pos:
            p = pos[:1].lower()
            same = [m for m in out if self.concepts[m.concept]["pos"][:1] == p]
            out = same if (same or strict) else out
        return sorted(out, key=lambda m: -m.confidence)

    def is_a(self, concept: str, ancestor: str, depth: int = 4) -> bool:
        if concept == ancestor:
            return True
        frontier, seen = [concept], {concept}
        for _ in range(depth):
            nxt = []
            for c in frontier:
                for rel, other, _, _ in self.edges.get(c, []):
                    if rel == "hypernym" and other not in seen:
                        if other == ancestor:
                            return True
                        seen.add(other); nxt.append(other)
            frontier = nxt
        return False

    def relation(self, a: str, b: str) -> tuple[str, float]:
        """Relation between two *lemmas*: same / synonym / hypernym / hyponym / antonym / related / unrelated, with a confidence.
        Equivalence needs a lexical edge or a shared seed concept; nothing else is reported as equivalent."""
        a, b = a.lower(), b.lower()
        if a == b:
            return "same", 1.0
        ca, cb = self.lemma_index.get(a, {}), self.lemma_index.get(b, {})
        shared = set(ca) & set(cb)
        if shared:
            return "synonym", max(min(ca[c].confidence, cb[c].confidence) for c in shared)
        best = ("unrelated", 0.0)
        for x in ca.values():
            for rel, other, w, _ in self.edges.get(x.concept, []):
                if other in cb:
                    score = w * min(x.confidence, cb[other].confidence)
                    if score > best[1]:
                        best = (rel, score)
        return best


_STORE: Path | None = None


@lru_cache(maxsize=1)
def default_graph() -> ConceptGraph:
    g = ConceptGraph.from_seed()
    if _STORE is not None:
        g.extend_from_store(_STORE)
    return g


def use_store(path: str | Path | None) -> None:
    """Attach (or detach with None) a processed lexical store; rebuilds the shared graph and the language engine's spelling vocabulary."""
    global _STORE
    _STORE = Path(path) if path else None
    default_graph.cache_clear()
    try:
        from ..engines.language.en import pipeline as _p
        _p.vocabulary.cache_clear(); _p._by_length.cache_clear()
    except Exception:                                                          # language engine caches are an optimisation, not a requirement
        pass
