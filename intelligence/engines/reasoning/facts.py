"""Fact base for one reasoning call: current-turn statements merged with stored knowledge.

Current-turn facts come straight from the ACR document (so reasoning never depends on whether the statement was
already persisted); stored facts come from the Knowledge Engine with the visibility rules of the caller's scope.
Duplicates are removed, preferring the current-turn copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.contracts import Evidence
from ...core.types import Scope
from ...representation import ACRDocument, Intention
from ..knowledge.engine import Fact, KnowledgeEngine
from ..knowledge.terms import render_term

ASSERTING_ACTS = {"assert", "inform", "correct", "confirm"}


def fact_key(f: Fact) -> tuple:
    return (f.predicate, f.polarity, f.quantifier, tuple(sorted((r, t.get("key")) for r, t in f.args.items())))


def describe(f: Fact) -> str:
    """Compact, readable rendering used inside evidence lists (user-facing prose is produced by the Response Engine)."""
    a = {r: render_term(t) for r, t in f.args.items()}
    neg = "NOT " if f.polarity == "negative" else ""
    q = f"[{f.quantifier}] " if f.quantifier else ""
    p = f.predicate
    if p == "rel.exceeds":
        return f"{q}{neg}{a.get('greater')} exceeds {a.get('lesser')} in {a.get('dimension')}"
    if p == "rel.equal_on":
        return f"{neg}{a.get('first')} equals {a.get('second')} in {a.get('dimension')}"
    if p == "rel.extreme":
        pole = "highest" if f.qualifiers.get("pole") == "high" else "lowest"
        return f"{neg}{a.get('subject')} is the {pole} in {a.get('dimension')}"
    if p == "rel.is_a":
        return f"{q}{a.get('subject')} {'is not' if neg else 'is'} a kind of {a.get('object')}"
    if p == "rel.located_in":
        return f"{neg}{a.get('figure')} located in {a.get('ground')}"
    if p == "rel.has_property":
        return f"{q}{a.get('subject')} {'lacks' if neg else 'has'} property {a.get('property')}"
    if p.startswith("attr."):
        return f"{neg}{p[5:]} of {a.get('owner')} is {a.get('value')}"
    return f"{neg}{p}({', '.join(f'{k}={v}' for k, v in a.items())})"


def fact_data(f: Fact) -> dict:
    """Language-neutral structured form of a fact: labels for entities/values, keys for dimensions/properties."""
    args = {}
    for r, t in f.args.items():
        if t.get("t") in ("concept",) or r in ("dimension",):
            args[r] = t.get("key")
        elif t.get("key") == "@user":
            args[r] = "you"
        else:
            args[r] = render_term(t)
    return {"predicate": f.predicate, "args": args, "polarity": f.polarity, "quantifier": f.quantifier, "pole": f.qualifiers.get("pole")}


def evidence_for(f: Fact) -> Evidence:
    kind = "user_statement" if f.level in ("turn", "user") else "knowledge"
    return Evidence(kind=kind, statement=describe(f), source=f.source_type, ref=f.id, confidence=round(f.confidence, 3), data=fact_data(f))


@dataclass
class FactBase:
    scope: Scope
    knowledge: KnowledgeEngine
    conversation_id: str | None
    current: list[Fact] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    _cache: dict[str, list[Fact]] = field(default_factory=dict)

    @classmethod
    def load(cls, scope: Scope, knowledge: KnowledgeEngine, doc: ACRDocument, conversation_id: str | None) -> "FactBase":
        fb = cls(scope, knowledge, conversation_id)
        n = 0
        for rid in doc.roots:
            node = doc.nodes[rid]
            if isinstance(node, Intention) and node.act in ASSERTING_ACTS:
                for pid in node.content:
                    facts, problems = knowledge.facts_from_proposition(doc, pid)
                    fb.skipped += problems
                    for pred, args, pol, quant, qual in facts:
                        n += 1
                        fb.current.append(Fact(id=f"turn:{n}", predicate=pred, args=args, polarity=pol, quantifier=quant,
                                               statement="", confidence=0.9, source_type="user_statement", source_id="turn", status="active",
                                               level="turn", conversation_id=conversation_id, qualifiers=qual))
        return fb

    def get(self, predicate: str) -> list[Fact]:
        if predicate not in self._cache:
            stored = self.knowledge.query(self.scope, predicate, conversation_id=self.conversation_id)
            merged: dict[tuple, Fact] = {fact_key(f): f for f in stored}
            for f in self.current:
                if f.predicate == predicate:
                    merged[fact_key(f)] = f
            self._cache[predicate] = list(merged.values())
        return self._cache[predicate]

    def disputed(self, predicate: str) -> list[Fact]:
        return self.knowledge.query(self.scope, predicate, conversation_id=self.conversation_id, statuses=("disputed",), include_self=False)
