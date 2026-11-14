"""Co-occurrence counting, PPMI weighting and truncated eigen-decomposition (orthogonal subspace iteration) in pure Python.

Why this and not neural embeddings: PPMI + low-rank factorisation is a classical, deterministic, inspectable method; the vectors are a function of the
corpus counts alone (reproducible), counts can be updated incrementally per document, and the whole pipeline needs no dependency or training run.

Pipeline (offline):  sentences -> windowed co-occurrence counts (incremental, SQLite) -> PPMI (context-distribution smoothing, alpha=0.75)
                     -> top-k subspace of the symmetric PPMI matrix -> L2-normalised word vectors in a ``VectorStore``.
Conversation time:   ``VectorStore.nearest`` / ``similarity`` read single rows; the whole matrix is never loaded.

Similarity is not equivalence. ``typed_relation`` combines the lexical graph (authoritative for synonym / antonym / hypernym) with distributional
similarity (evidence for *relatedness only*): two antonyms are distributionally close and must not be reported as equivalent.
"""
from __future__ import annotations

import array
import math
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

STOP = frozenset("a an the of to in on at for and or but is are was were be been am it its this that these those with as by from i you he she we they my your his her our their".split())


def tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z]+", s.lower())


class CoocBuilder:
    """Incremental windowed co-occurrence counts persisted in SQLite. ``add_document`` is idempotent per document hash."""

    def __init__(self, path: str | Path, window: int = 4):
        self.path = Path(path)
        self.window = window
        self.con = sqlite3.connect(self.path)
        self.con.executescript("""CREATE TABLE IF NOT EXISTS cooc (w1 TEXT, w2 TEXT, n INTEGER, PRIMARY KEY (w1, w2));
                                  CREATE TABLE IF NOT EXISTS docs (sha TEXT PRIMARY KEY);
                                  CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);""")

    def add_sentences(self, sentences, doc_id: str) -> bool:
        if self.con.execute("SELECT 1 FROM docs WHERE sha=?", (doc_id,)).fetchone():
            return False
        local: Counter = Counter()
        for s in sentences:
            toks = [t for t in tokenize(s) if t not in STOP and len(t) > 1]
            for i, w in enumerate(toks):
                for j in range(max(0, i - self.window), i):
                    if toks[j] != w:
                        local[(w, toks[j])] += 1
                        local[(toks[j], w)] += 1
        self.con.executemany("INSERT INTO cooc VALUES (?,?,?) ON CONFLICT(w1,w2) DO UPDATE SET n = n + excluded.n", [(a, b, n) for (a, b), n in local.items()])
        self.con.execute("INSERT INTO docs VALUES (?)", (doc_id,))
        self.con.commit()
        return True

    def counts(self, min_count: int = 2):
        return self.con.execute("SELECT w1, w2, n FROM cooc WHERE n >= ?", (min_count,))

    def close(self) -> None:
        self.con.close()


def ppmi_rows(triples, alpha: float = 0.75):
    """PPMI with context-distribution smoothing. Returns (vocab list, sparse rows: list[dict[int, float]])."""
    trip = list(triples)
    vocab = sorted({w for w, _, _ in trip})
    ix = {w: i for i, w in enumerate(vocab)}
    total = sum(n for _, _, n in trip)
    rowsum: dict[str, float] = defaultdict(float)
    colsum: dict[str, float] = defaultdict(float)
    for a, b, n in trip:
        rowsum[a] += n
        colsum[b] += n
    csm = sum(c ** alpha for c in colsum.values())
    rows: list[dict[int, float]] = [dict() for _ in vocab]
    for a, b, n in trip:
        if b not in ix:
            continue
        pa = rowsum[a] / total
        pb = (colsum[b] ** alpha) / csm
        v = math.log((n / total) / (pa * pb))
        if v > 0:
            rows[ix[a]][ix[b]] = v
    return vocab, rows


def _matvec(rows, x: list[float]) -> list[float]:
    return [sum(v * x[j] for j, v in r.items()) for r in rows]


def top_subspace(rows: list[dict[int, float]], k: int, iters: int = 12, seed: int = 7) -> tuple[list[list[float]], list[float]]:
    """Orthogonal (subspace) iteration for the dominant eigenpairs of the symmetric matrix given as sparse rows. Deterministic for a fixed seed."""
    n = len(rows)
    k = min(k, n)
    rng = random.Random(seed)
    Q = [[rng.gauss(0, 1) for _ in range(n)] for _ in range(k)]

    def orth(vs):
        out: list[list[float]] = []
        for v in vs:
            for u in out:
                d = sum(a * b for a, b in zip(v, u))
                v = [a - d * b for a, b in zip(v, u)]
            norm = math.sqrt(sum(a * a for a in v)) or 1.0
            out.append([a / norm for a in v])
        return out

    Q = orth(Q)
    for _ in range(iters):
        Q = orth([_matvec(rows, q) for q in Q])
    eig = [sum(a * b for a, b in zip(q, _matvec(rows, q))) for q in Q]
    return Q, eig


class VectorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.con = sqlite3.connect(self.path)
        self.con.executescript("CREATE TABLE IF NOT EXISTS vectors (word TEXT PRIMARY KEY, dim INTEGER, vec BLOB); CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);")

    def put_all(self, words: list[str], vecs: list[list[float]], meta: dict) -> None:
        self.con.execute("DELETE FROM vectors")
        self.con.executemany("INSERT INTO vectors VALUES (?,?,?)", [(w, len(v), array.array("f", v).tobytes()) for w, v in zip(words, vecs)])
        self.con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
        self.con.commit()

    def vector(self, word: str) -> list[float] | None:
        r = self.con.execute("SELECT vec FROM vectors WHERE word=?", (word.lower(),)).fetchone()
        if not r:
            return None
        a = array.array("f"); a.frombytes(r[0])
        return list(a)

    def similarity(self, a: str, b: str) -> float | None:
        va, vb = self.vector(a), self.vector(b)
        if va is None or vb is None:
            return None
        return sum(x * y for x, y in zip(va, vb))          # vectors are L2-normalised

    def nearest(self, word: str, k: int = 5, candidates: set[str] | None = None) -> list[tuple[str, float]]:
        v = self.vector(word)
        if v is None:
            return []
        best: list[tuple[float, str]] = []
        for w, blob in self.con.execute("SELECT word, vec FROM vectors"):          # streamed row by row
            if w == word.lower() or (candidates is not None and w not in candidates):
                continue
            a = array.array("f"); a.frombytes(blob)
            s = sum(x * y for x, y in zip(v, a))
            best.append((s, w))
        best.sort(reverse=True)
        return [(w, round(s, 4)) for s, w in best[:k]]


def build_vectors(cooc: CoocBuilder, out: VectorStore, dims: int = 24, min_count: int = 2) -> dict:
    vocab, rows = ppmi_rows(cooc.counts(min_count))
    if len(vocab) < 3:
        raise ValueError("not enough co-occurrence data to build vectors")
    Q, eig = top_subspace(rows, dims)
    vecs = []
    for i in range(len(vocab)):
        v = [Q[d][i] * math.sqrt(abs(eig[d])) for d in range(len(Q))]
        norm = math.sqrt(sum(a * a for a in v)) or 1.0
        vecs.append([a / norm for a in v])
    meta = {"dims": len(Q), "vocab": len(vocab), "method": "ppmi+subspace-iteration", "min_count": min_count}
    out.put_all(vocab, vecs, meta)
    return meta


def typed_relation(graph, store: VectorStore | None, a: str, b: str, related_threshold: float = 0.5) -> dict:
    """Relation of two lemmas: lexical edges decide equivalence/opposition; distributional similarity can only say "related"."""
    rel, conf = graph.relation(a, b)
    sim = store.similarity(a, b) if store is not None else None
    if rel in ("same", "synonym"):
        return {"relation": "equivalent", "basis": "lexical", "confidence": round(conf, 3), "similarity": sim}
    if rel == "antonym":
        return {"relation": "opposite", "basis": "lexical", "confidence": round(conf, 3), "similarity": sim}
    if rel in ("hypernym", "hyponym"):
        return {"relation": rel, "basis": "lexical", "confidence": round(conf, 3), "similarity": sim}
    if sim is not None and sim >= related_threshold:
        return {"relation": "related", "basis": "distributional", "confidence": round(min(0.55, sim * 0.6), 3), "similarity": round(sim, 3), "note": "similar contexts; not interchangeable"}
    return {"relation": "unrelated", "basis": "none", "confidence": 0.0, "similarity": sim}
