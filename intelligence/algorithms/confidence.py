"""Evidence-combination helpers with *defined* semantics.

AVOENIX confidence values are **evidence-support scores in [0, 1]**. They are not
calibrated probabilities. They are built from the following rules:

* ``noisy_or``: independent supporting evidence accumulates: ``1 - prod(1 - p_i)``.
* ``chain``: a conclusion derived through several uncertain steps is no stronger than
  the product of its steps (independence assumed; conservative).
* ``weighted_geometric``: one weak component drags the aggregate down
  (a single serious problem should not be averaged away).
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping

#: Base reliability of each provenance class (policy constants, documented in docs/).
SOURCE_RELIABILITY = {
    "external_verified": 0.95,
    "seed_curated": 0.90,
    "learned": 0.80,
    "user_statement": 0.70,
    "derived": 0.60,   # replaced by the derivation's own score; this is only a floor
    "system": 0.90,
}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def noisy_or(ps: Iterable[float]) -> float:
    prod = 1.0
    for p in ps:
        prod *= 1.0 - clamp(p)
    return clamp(1.0 - prod)


def chain(ps: Iterable[float]) -> float:
    out = 1.0
    for p in ps:
        out *= clamp(p)
    return clamp(out)


def weighted_geometric(components: Mapping[str, float], weights: Mapping[str, float]) -> float:
    total_w = sum(weights.get(k, 0.0) for k in components)
    if total_w <= 0:
        return 0.0
    acc = 0.0
    for key, val in components.items():
        w = weights.get(key, 0.0)
        acc += w * math.log(max(clamp(val), 1e-6))
    return clamp(math.exp(acc / total_w))


def laplace(successes: int, trials: int) -> float:
    """Rule of succession: (s + 1) / (n + 2). Used for inductive generalisation support."""
    return (successes + 1) / (trials + 2)


def band(score: float | None) -> str:
    if score is None:
        return "not_evaluated"
    if score >= 0.80:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"
