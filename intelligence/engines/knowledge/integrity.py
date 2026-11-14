"""Knowledge Integrity: claim classification, validation and explainable epistemic assessment.

The central rule: **remembering a statement and believing it are separate operations.** ``validate`` evaluates an incoming claim against what is
already established and returns a ``Validation`` — an ``Assessment`` (level, verification, support, basis, evidence items), the conflicts found,
and the list of checks that ran. It never writes anything; ``KnowledgeEngine.assert_fact`` decides what to store from it.

What the checks cover (and do not cover) is documented in docs/KNOWLEDGE_INTEGRITY.md. In short:

* internal-knowledge comparison  exact-match agreement with established facts
* entailment                      is-a chains and located-in chains over established facts
* contradiction                   negation, single-valued attributes, taxonomic disjointness (direct or inherited), country-level containment, order cycles
* temporal consistency            facts carrying different time qualifiers do not conflict
* source reliability / evidence   user statements carry a reliability *prior* that is shown but never counts as evidence of truth

No external service is consulted. When there is no evidence the claim stays ``unverified`` with support 0.0 — verification is never invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

from ...algorithms.confidence import SOURCE_RELIABILITY, noisy_or
from ...algorithms.partial_order import PartialOrder
from ...representation.claims import (
    Assessment, ClaimType, ConflictKind, ESTABLISHED_VERIFICATIONS, EpistemicLevel, EvidenceItem, PROVENANCE_OF_SOURCE, Verification,
)
from .terms import SELF_USER

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Fact

WORLD_PREDICATES = {"attr.capital", "attr.currency", "attr.president", "attr.population", "rel.located_in"}
ESTABLISHED_SOURCES = ("external_verified", "seed_curated", "system", "learned")
FUNCTIONAL_PREDICATES = {"attr.name", "attr.age", "attr.birthday", "attr.height", "attr.weight", "attr.address", "attr.job", "attr.capital",
                         "attr.president", "attr.population", "attr.currency", "attr.color", "attr.colour", "attr.favorite", "attr.language", "attr.residence"}


def provenance_of(source_type: str) -> str:
    return PROVENANCE_OF_SOURCE.get(source_type, "unresolved")


def classify_claim(predicate: str, args: dict[str, dict]) -> str:
    """world / personal / premise. Structure-based (predicate and term types), not keyword-based."""
    if any((t or {}).get("key") == SELF_USER or str((t or {}).get("key", "")).startswith(SELF_USER + "/") for t in args.values()):
        return ClaimType.PERSONAL.value
    if predicate in WORLD_PREDICATES:
        return ClaimType.WORLD.value
    if predicate == "rel.is_a" and (args.get("subject") or {}).get("t") == "kind":
        return ClaimType.WORLD.value
    return ClaimType.PREMISE.value


def is_established(f: "Fact") -> bool:
    return f.verification in ESTABLISHED_VERIFICATIONS and f.status == "active"


@dataclass
class Conflict:
    kind: str
    other: "Fact"
    note: str
    other_standing: str            # "established" | "claim"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "with": self.other.to_dict(), "note": self.note, "other_standing": self.other_standing, **self.extra}


@dataclass
class Validation:
    assessment: Assessment
    conflicts: list[Conflict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    same: list["Fact"] = field(default_factory=list)             # facts stating exactly the same thing (same polarity)

    @property
    def contradicted_by_established(self) -> bool:
        return any(c.other_standing == "established" for c in self.conflicts)

    def to_dict(self) -> dict:
        return {"assessment": self.assessment.to_dict(), "conflicts": [c.to_dict() for c in self.conflicts], "checks": self.checks}


def _same_args(f: "Fact", args: dict[str, dict]) -> bool:
    return set(f.args) == set(args) and all((f.args[r] or {}).get("key") == t["key"] for r, t in args.items())


def _time_of(qualifiers: dict | None) -> str | None:
    t = (qualifiers or {}).get("time")
    return None if not t else repr(sorted(t.items())) if isinstance(t, dict) else str(t)


class _Graph:
    """Directed closure over established facts of one predicate (is-a over kinds, located-in over entities)."""

    def __init__(self, facts: list["Fact"], child: str, parent: str):
        self.up: dict[str, list[tuple[str, "Fact"]]] = {}
        for f in facts:
            if f.polarity == "positive" and is_established(f):
                a, b = f.key_of(child), f.key_of(parent)
                if a and b:
                    self.up.setdefault(a, []).append((b, f))

    def path(self, src: str, dst: str) -> list["Fact"] | None:
        """Shortest chain of established facts from src up to dst (excluding src == dst)."""
        seen = {src}
        frontier: list[tuple[str, list["Fact"]]] = [(src, [])]
        while frontier:
            nxt = []
            for node, trail in frontier:
                for parent, fact in self.up.get(node, []):
                    if parent == dst:
                        return trail + [fact]
                    if parent not in seen:
                        seen.add(parent)
                        nxt.append((parent, trail + [fact]))
            frontier = nxt
        return None

    def ancestors(self, src: str) -> dict[str, list["Fact"]]:
        out: dict[str, list["Fact"]] = {}
        seen = {src}
        frontier: list[tuple[str, list["Fact"]]] = [(src, [])]
        while frontier:
            nxt = []
            for node, trail in frontier:
                for parent, fact in self.up.get(node, []):
                    if parent not in seen:
                        seen.add(parent)
                        out[parent] = trail + [fact]
                        nxt.append((parent, trail + [fact]))
            frontier = nxt
        return out


def _chain_weight(chain: list["Fact"]) -> float:
    w = 1.0
    for f in chain:
        w *= SOURCE_RELIABILITY.get(f.source_type, 0.5) * min(1.0, f.confidence if f.source_type not in ESTABLISHED_SOURCES else 1.0)
    return round(w, 3)


def validate(*, predicate: str, args: dict[str, dict], polarity: str, quantifier: str | None, qualifiers: dict | None, source_type: str,
             claim_type: str, interpretation_confidence: float, conversation_id: str | None,
             visible: Callable[[str], list["Fact"]]) -> Validation:
    """Evaluate one incoming claim. ``visible(predicate)`` returns the facts the caller may see (active and disputed) for that predicate."""
    checks: list[dict] = []
    conflicts: list[Conflict] = []
    evidence: list[EvidenceItem] = []
    basis: list[str] = []
    same_pred = visible(predicate)
    same = [f for f in same_pred if _same_args(f, args) and f.polarity == polarity and f.quantifier == quantifier]
    established_source = source_type in ESTABLISHED_SOURCES
    my_time = _time_of(qualifiers)

    # --- source reliability (a prior: shown, never counted as evidence of truth) ------------------------------------------------------------
    prior = SOURCE_RELIABILITY.get(source_type, 0.5)
    evidence.append(EvidenceItem("context", "source_prior", f"source type '{source_type}' has a reliability prior of {prior:.2f}; a prior is not evidence that this claim is true",
                                 weight=prior))
    checks.append({"check": "source_reliability", "outcome": "recorded", "detail": f"{source_type} prior {prior:.2f}"})

    # --- contradiction checks ---------------------------------------------------------------------------------------------------------------
    def standing(f: "Fact") -> str:
        return "established" if is_established(f) else "claim"

    for f in same_pred:
        if f.status not in ("active", "disputed") or _same_args(f, args) and f.polarity == polarity and f.quantifier == quantifier:
            continue
        if _same_args(f, args) and f.polarity != polarity and f.quantifier == quantifier:
            conflicts.append(Conflict(ConflictKind.NEGATION.value, f, "the same statement is held with the opposite polarity", standing(f)))
    if predicate in FUNCTIONAL_PREDICATES and "owner" in args and "value" in args:
        for f in same_pred:
            if f.polarity == "positive" and polarity == "positive" and f.status in ("active", "disputed") and f.key_of("owner") == args["owner"]["key"] \
                    and f.key_of("value") != args["value"]["key"]:
                if (_time_of(f.qualifiers) or my_time) and _time_of(f.qualifiers) != my_time:
                    checks.append({"check": "temporal_consistency", "outcome": "not_in_conflict", "detail": "the facts carry different time qualifiers"})
                    continue
                conflicts.append(Conflict(ConflictKind.FUNCTIONAL.value, f, f"{predicate} normally has a single value", standing(f)))
    if predicate == "rel.is_a":
        graph = _Graph(visible("rel.is_a"), "subject", "object")
        sub, obj = args["subject"]["key"], args["object"]["key"]
        negatives = [f for f in visible("rel.is_a") if f.polarity == "negative" and is_established(f)]
        if polarity == "positive":
            lineage = {sub: []} | graph.ancestors(sub)
            for n in negatives:
                if n.key_of("object") == obj and n.key_of("subject") in lineage:
                    conflicts.append(Conflict(ConflictKind.TAXONOMIC.value, n, "established knowledge says this is not the case", "established",
                                              {"inherited_from": n.key_of("subject")} if n.key_of("subject") != sub else {}))
            sup_lineage = {obj: []} | graph.ancestors(obj)
            for n in negatives:                      # e.g. claim "dog is a bird"; established "mammal is not a bird" and dog is-a mammal
                if n.key_of("subject") == sub and n.key_of("object") in sup_lineage and n.key_of("object") != obj:
                    conflicts.append(Conflict(ConflictKind.TAXONOMIC.value, n, "established knowledge excludes a more general kind", "established"))
        else:
            chain = graph.path(sub, obj)
            if chain:
                conflicts.append(Conflict(ConflictKind.TAXONOMIC.value, chain[0], "established knowledge entails the opposite through an is-a chain", "established",
                                          {"chain": [c.id for c in chain]}))
    if predicate == "rel.located_in" and polarity == "positive":
        graph = _Graph(visible("rel.located_in"), "figure", "ground")
        fig, gro = args["figure"]["key"], args["ground"]["key"]
        containers = graph.ancestors(fig)
        countries = {f.key_of("owner") for f in visible("attr.capital") if is_established(f)}
        if gro in countries:
            for z, chain in containers.items():
                if z in countries and z != gro and gro not in graph.ancestors(z) and z not in graph.ancestors(gro):
                    conflicts.append(Conflict(ConflictKind.LOCATION.value, chain[-1], f"established knowledge places it inside a different country ({z})", "established"))
                    break
    if predicate == "rel.exceeds" and polarity == "positive" and "dimension" in args:
        dim = args["dimension"]["key"]
        po = PartialOrder()
        for f in same_pred:
            if f.key_of("dimension") == dim and f.polarity == "positive" and f.status == "active" and (conversation_id is None or f.conversation_id in (None, conversation_id)):
                po.add_greater(f.key_of("greater"), f.key_of("lesser"), f.id)
        po.add_greater(args["greater"]["key"], args["lesser"]["key"], "new")
        cyc = po.find_cycle()
        checks.append({"check": "logical_consistency", "outcome": "inconsistent" if cyc else "consistent", "detail": "order cycle: " + " > ".join(str(c) for c in cyc) if cyc else "no cycle"})
        if cyc:
            # report the stored comparison facts that participate in the cycle
            involved = [f for f in same_pred if f.key_of("dimension") == dim and f.polarity == "positive" and f.status == "active"
                        and f.key_of("greater") in cyc and f.key_of("lesser") in cyc]
            for f in involved[:1] or []:
                conflicts.append(Conflict(ConflictKind.ORDERING.value, f, "adding this comparison would make the ordering circular", standing(f), {"cycle": [str(c) for c in cyc]}))
            if not involved:
                conflicts.append(Conflict(ConflictKind.ORDERING.value, same_pred[0], "adding this comparison would make the ordering circular", standing(same_pred[0]), {"cycle": [str(c) for c in cyc]}))
    checks.append({"check": "contradiction", "outcome": "conflicts_found" if conflicts else "none_found",
                   "detail": "; ".join(f"{c.kind} with {c.other.id} ({c.other_standing})" for c in conflicts) or "no contradiction with visible knowledge"})

    # --- agreement / entailment with established knowledge ---------------------------------------------------------------------------------
    supports: list[tuple[float, EvidenceItem]] = []
    for f in same:
        if is_established(f) and not established_source:
            w = SOURCE_RELIABILITY.get(f.source_type, 0.5)
            supports.append((w, EvidenceItem("supports", "established_fact", f"agrees with {f.source_type.replace('_', ' ')} knowledge ({f.id})", f.id, w)))
    if not supports and polarity == "positive" and not established_source:
        if predicate == "rel.is_a":
            chain = _Graph(visible("rel.is_a"), "subject", "object").path(args["subject"]["key"], args["object"]["key"])
            if chain:
                w = _chain_weight(chain)
                supports.append((w, EvidenceItem("supports", "entailment", "entailed by an is-a chain of established facts: " + " → ".join(c.statement or c.id for c in chain), chain[-1].id, w)))
        elif predicate == "rel.located_in":
            chain = _Graph(visible("rel.located_in"), "figure", "ground").path(args["figure"]["key"], args["ground"]["key"])
            if chain:
                w = _chain_weight(chain)
                supports.append((w, EvidenceItem("supports", "entailment", "entailed by a located-in chain of established facts", chain[-1].id, w)))
    checks.append({"check": "internal_knowledge_comparison", "outcome": "supported" if supports else ("contradicted" if any(c.other_standing == "established" for c in conflicts) else "no_evidence"),
                   "detail": supports[0][1].note if supports else "no established fact agrees with or entails this claim"})
    evidence += [e for _, e in supports]
    for c in conflicts:
        evidence.append(EvidenceItem("contradicts", "contradiction", f"{c.kind}: {c.note} ({c.other.id}, {c.other_standing})", c.other.id,
                                     SOURCE_RELIABILITY.get(c.other.source_type, 0.5) if c.other_standing == "established" else None))
    support = round(noisy_or([w for w, _ in supports]), 3) if supports else 0.0
    refutation = None
    est_conflicts = [c for c in conflicts if c.other_standing == "established"]
    if supports and not est_conflicts and not established_source:
        # Established knowledge agrees with this claim, so a clash with some *other claim* is already settled by it: that other claim is the
        # one contradicted. Keep it out of this claim's conflicts (it is recorded against the other claim when that one was validated).
        conflicts = []
        checks.append({"check": "contradiction", "outcome": "settled_by_established_knowledge", "detail": "peer claims that differ are contradicted by established knowledge"})
    if est_conflicts:
        refutation = round(max(SOURCE_RELIABILITY.get(c.other.source_type, 0.5) for c in est_conflicts), 3)
    checks.append({"check": "evidence_availability", "outcome": "available" if supports or est_conflicts else "none", "detail": f"{len(supports)} supporting, {len(est_conflicts)} established contradicting"})

    # --- verdict ----------------------------------------------------------------------------------------------------------------------------
    if claim_type == ClaimType.PERSONAL.value:
        verification, level, support = Verification.NOT_APPLICABLE.value, EpistemicLevel.SELF_REPORTED.value, None
        basis.append("a statement about the speaker; the speaker is the best available authority, so there is nothing to verify against")
    elif established_source:
        verification = Verification.VERIFIED.value if source_type == "external_verified" else Verification.CURATED.value
        level = EpistemicLevel.ESTABLISHED.value
        support = round(prior, 3)
        basis.append("curated internal knowledge — authored and reviewed by the AVOENIX project, not independently verified" if verification == Verification.CURATED.value
                     else "from an independently verified source")
    elif source_type == "derived":
        verification, level = Verification.SUPPORTED.value, EpistemicLevel.SUPPORTED.value
        support = round(min(interpretation_confidence, 0.9), 3)
        basis.append("derived by inference from other facts; its support is bounded by the support of its premises")
    elif est_conflicts:
        verification, level, support = Verification.CONTRADICTED.value, EpistemicLevel.CONFLICTING.value, 0.0
        basis.append(f"contradicts established knowledge (refutation weight {refutation})")
    elif conflicts:
        verification, level, support = Verification.CONFLICTING.value, EpistemicLevel.CONFLICTING.value, 0.0
        basis.append("conflicts with another claim of comparable standing; neither is established")
    elif supports:
        verification, level = Verification.SUPPORTED.value, EpistemicLevel.SUPPORTED.value
        basis.append("agrees with or follows from established knowledge")
    elif claim_type == ClaimType.PREMISE.value:
        verification, level, support = Verification.UNVERIFIED.value, EpistemicLevel.INSUFFICIENT.value, None
        basis.append("a scenario premise about arbitrary individuals: usable for reasoning inside the conversation, but nothing exists to check it against")
    else:
        verification, level, support = Verification.UNVERIFIED.value, EpistemicLevel.UNVERIFIED.value, 0.0
        basis.append("no established knowledge about this; it rests only on the user's statement and is not independently established")
    if conflicts and not est_conflicts and verification not in (Verification.CONFLICTING.value, Verification.NOT_APPLICABLE.value) and not established_source:
        verification, level = Verification.CONFLICTING.value, EpistemicLevel.CONFLICTING.value
        basis.append("also conflicts with another claim")
    assessment = Assessment(level=level, verification=verification, interpretation_confidence=round(float(interpretation_confidence), 3),
                            support=support, refutation=refutation, basis=basis, evidence=evidence)
    return Validation(assessment, conflicts, checks, same)
