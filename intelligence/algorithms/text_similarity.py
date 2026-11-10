"""Traditional text-similarity and retrieval algorithms implemented from first principles.

No pretrained model, embedding or neural component is involved: edit distance,
Jaro-Winkler, character n-gram Jaccard, and an Okapi BM25 ranker over a small in-memory
corpus.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Sequence

_WORD = re.compile(r"[a-z0-9']+")
STOPWORDS = frozenset(
    "a an the of to in on at for and or but is are was were be been am do does did i you he she it we they "
    "my your his her its our their me him them this that these those with from by as so if then than".split()
)


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS]


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def damerau(a: str, b: str) -> int:
    """Optimal-string-alignment distance: Levenshtein plus adjacent transposition as one edit."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def edit_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    matches = 0
    for i, ca in enumerate(a):
        lo, hi = max(0, i - window), min(lb, i + window + 1)
        for j in range(lo, hi):
            if not mb[j] and b[j] == ca:
                ma[i] = mb[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t, k = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            if a[i] != b[k]:
                t += 1
            k += 1
    t //= 2
    return (matches / la + matches / lb + (matches - t) / matches) / 3


def jaro_winkler(a: str, b: str, p: float = 0.1) -> float:
    j = jaro(a, b)
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return j + prefix * p * (1 - j)


def ngrams(text: str, n: int = 3) -> set[str]:
    t = f" {text.lower()} "
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def fuzzy_match(a: str, b: str) -> float:
    """Blend of Jaro-Winkler and trigram overlap; robust to typos in names."""
    a, b = a.lower().strip(), b.lower().strip()
    return 0.6 * jaro_winkler(a, b) + 0.4 * jaccard(ngrams(a), ngrams(b))


class BM25:
    """Okapi BM25 over a list of documents (token lists)."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = [list(d) for d in docs]
        self.k1, self.b = k1, b
        self.N = len(self.docs)
        self.avgdl = (sum(len(d) for d in self.docs) / self.N) if self.N else 0.0
        self.df: Counter[str] = Counter()
        for d in self.docs:
            self.df.update(set(d))
        self.tf = [Counter(d) for d in self.docs]

    def idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def scores(self, query: Iterable[str]) -> list[float]:
        q = list(query)
        out = []
        for i, d in enumerate(self.docs):
            dl = len(d) or 1
            s = 0.0
            for term in q:
                f = self.tf[i].get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                s += self.idf(term) * f * (self.k1 + 1) / denom
            out.append(s)
        return out
