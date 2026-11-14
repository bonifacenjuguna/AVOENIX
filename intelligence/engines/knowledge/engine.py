"""Knowledge Engine: structured, provenance-aware, contradiction-aware fact storage and retrieval.

Visibility model (``project_id`` / ``user_id`` columns of ``knowledge_facts``):

* ``project_id = '*'``              curated global knowledge shipped with AVOENIX (read-only for applications)
* ``project_id = P, user_id NULL``  knowledge shared inside project P (written by administrators)
* ``project_id = P, user_id = U``   what user U told the system (never visible to other users or projects)

Information supplied by users, curated seed knowledge, externally verified knowledge and internally derived
conclusions are kept apart by ``source_type`` and ranked by reliability when they conflict. A user statement can
never silently overwrite curated knowledge: it is stored as *disputed* and reported back.

Knowledge Integrity (v0.0.1): every fact is also an epistemic *claim* (see ``integrity.py`` and ``representation/claims.py``). It carries a provenance
kind, a claim type (world / personal / premise), a verification state and an explainable assessment. A user statement is **recorded** but not
**believed**: it starts ``unverified`` and becomes ``supported`` only when established knowledge agrees with it. Conflicting claims are preserved
with conflict records; corrections create append-only revision records; nothing is overwritten silently.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ...algorithms.confidence import SOURCE_RELIABILITY
from ...algorithms.partial_order import PartialOrder
from ...algorithms.text_similarity import BM25, damerau, fuzzy_match, words
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import InputError, NotFoundError, ScopeError, StorageError
from ...core.types import Scope
from ...representation import ACRDocument, Logical, Proposition
from ...representation.claims import (
    Assessment, Claim, ESTABLISHED_VERIFICATIONS, Verification, triple_of,
)
from ...storage.backend import Backend
from ...version import PLATFORM_VERSION
from . import integrity, seed
from .terms import (
    SELF_SYSTEM, SELF_USER, concept_term, entity_term, is_storable_term, kind_term, norm_key, render_statement, render_term, term_from_node,
)

RANK = {"external_verified": 5, "seed_curated": 4, "system": 4, "learned": 3, "user_statement": 2, "derived": 1}
FUNCTIONAL_PREDICATES = {"attr.name", "attr.age", "attr.birthday", "attr.height", "attr.weight", "attr.address", "attr.job", "attr.capital",
                         "attr.president", "attr.population", "attr.currency", "attr.color", "attr.colour", "attr.favorite", "attr.language", "attr.residence"}
VISIBLE_STATUSES = ("active",)


@dataclass
class Fact:
    id: str
    predicate: str
    args: dict[str, dict]
    polarity: str
    quantifier: str | None
    statement: str
    confidence: float
    source_type: str
    source_id: str | None
    status: str
    level: str                       # global | project | user | system
    conversation_id: str | None = None
    qualifiers: dict = field(default_factory=dict)
    created_at: str | None = None
    version: int = 1
    provenance: str = "unresolved"
    claim_type: str = "premise"
    verification: str = "unverified"
    assessment: dict = field(default_factory=dict)
    memory_id: str | None = None
    updated_at: str | None = None

    @property
    def established(self) -> bool:
        """Usable as established knowledge: curated or independently verified, and still active."""
        return self.verification in ESTABLISHED_VERIFICATIONS and self.status == "active"

    def to_claim(self, conflicts: list[str] | None = None) -> Claim:
        subj, pred, obj = triple_of(self.predicate, self.args)
        return Claim(id=self.id, subject=subj, predicate=pred, object=obj, polarity=self.polarity, claim_type=self.claim_type, provenance=self.provenance,
                     source=self.source_type, source_ref=self.source_id, verification=self.verification, status=self.status,
                     assessment=Assessment.from_dict(self.assessment), statement=self.statement, conversation_id=self.conversation_id,
                     created_at=self.created_at, updated_at=self.updated_at, conflicts=conflicts or [], memory_id=self.memory_id)

    def key_of(self, role: str) -> str | None:
        t = self.args.get(role)
        return t.get("key") if t else None

    def to_dict(self) -> dict:
        return {"id": self.id, "predicate": self.predicate, "args": self.args, "polarity": self.polarity, "quantifier": self.quantifier,
                "statement": self.statement, "confidence": self.confidence, "source_type": self.source_type, "source_id": self.source_id,
                "status": self.status, "level": self.level, "conversation_id": self.conversation_id, "qualifiers": self.qualifiers,
                "created_at": self.created_at, "version": self.version, "provenance": self.provenance, "claim_type": self.claim_type,
                "verification": self.verification, "assessment": self.assessment, "memory_id": self.memory_id, "updated_at": self.updated_at}

    @property
    def reliability(self) -> float:
        return SOURCE_RELIABILITY.get(self.source_type, 0.5) * self.confidence


@dataclass
class AssertResult:
    status: str                       # stored | duplicate | superseded | disputed | rejected
    fact: Fact | None = None
    contradictions: list[dict] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    reason: str | None = None
    verification: str | None = None
    assessment: dict | None = None
    conflict_ids: list[str] = field(default_factory=list)
    revision_id: str | None = None
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "fact": self.fact.to_dict() if self.fact else None, "contradictions": self.contradictions,
                "superseded": self.superseded, "reason": self.reason, "verification": self.verification, "assessment": self.assessment,
                "conflict_ids": self.conflict_ids, "revision_id": self.revision_id, "checks": self.checks}


def _fact_from_row(row: dict, scope: Scope | None = None) -> Fact:
    level = "global" if row["project_id"] == "*" else ("user" if row.get("user_id") else "project")
    return Fact(id=row["id"], predicate=row["predicate"], args=row["args"], polarity=row["polarity"], quantifier=row.get("quantifier"),
                statement=row["statement"], confidence=float(row["confidence"]), source_type=row["source_type"], source_id=row.get("source_id"),
                status=row["status"], level=level, conversation_id=row.get("conversation_id"), qualifiers=row.get("qualifiers") or {},
                created_at=row.get("created_at"), version=row.get("version") or 1,
                provenance=row.get("provenance") or integrity.provenance_of(row["source_type"]), claim_type=row.get("claim_type") or "premise",
                verification=row.get("verification") or "unverified", assessment=row.get("assessment") or {}, memory_id=row.get("memory_id"),
                updated_at=row.get("updated_at"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SelfModel:
    """Runtime self-knowledge. Generated from live engine metadata, so it can never claim an unbuilt capability."""

    def __init__(self, engine_infos_provider=None):
        self.provider = engine_infos_provider or (lambda: [])

    def facts(self) -> list[Fact]:
        out: list[Fact] = []

        def add(pred, args, polarity="positive", statement=None):
            out.append(Fact(id=f"self:{pred}:{len(out)}", predicate=pred, args=args, polarity=polarity, quantifier=None,
                            statement=statement or render_statement(pred, args, polarity), confidence=1.0, source_type="system", source_id="self_model",
                            status="active", level="system", provenance="internal_knowledge", claim_type="world", verification="curated",
                            assessment=KnowledgeEngine._curated_assessment(pred, args, "system")))

        me = entity_term("AVOENIX")
        add("attr.name", {"owner": me, "value": entity_term("AVOENIX")})
        add("attr.version", {"owner": me, "value": {"t": "literal", "key": f"lit:{PLATFORM_VERSION}", "value": PLATFORM_VERSION}})
        add("rel.is_a", {"subject": me, "object": kind_term("kind.algorithmic_intelligence_system", "algorithmic intelligence system")})
        add("rel.is_a", {"subject": me, "object": kind_term("kind.large_language_model", "large language model")}, "negative")
        add("rel.is_a", {"subject": me, "object": kind_term("kind.neural_network", "neural network")}, "negative")
        add("rel.is_a", {"subject": me, "object": kind_term("kind.chatbot", "scripted chatbot")}, "negative")
        add("attr.language", {"owner": me, "value": entity_term("English")})
        for info in self.provider():
            add("rel.has_engine", {"subject": me, "engine": {"t": "concept", "key": f"engine.{info['key']}", "label": info["name"]}},
                statement=f"AVOENIX has the {info['name']} [{info['status']}]: {info['summary']}")
        return out


class KnowledgeEngine(Engine):
    info = EngineInfo(
        key="knowledge", name="Knowledge Engine", status=EngineStatus.IMPLEMENTED,
        summary="Typed fact store with provenance, scoping, contradiction handling, fuzzy entity lookup and lexical retrieval.",
        depends_on=("storage",),
        capabilities=("facts over typed terms (entities, kinds, concepts, quantities)", "three-level visibility (global/project/user)",
                      "provenance and reliability ranking", "duplicate, negation, functional and ordering-cycle contradiction detection",
                      "supersession with history", "fuzzy entity lookup", "BM25 lexical retrieval over statements", "runtime self-model",
                      "curated seed knowledge (small, labelled unverified)"),
        limitations=("World knowledge is tiny (≈90 curated facts); anything else must come from users or administrators.",
                     "Contradiction detection covers direct negation, functional predicates and order cycles — not arbitrary logical inconsistency.",
                     "No ontology alignment or entity linking beyond normalised-label matching and fuzzy suggestion."),
    )

    def __init__(self, backend: Backend, *, self_model: SelfModel | None = None):
        super().__init__()
        self.backend = backend
        self.self_model = self_model or SelfModel()

    def self_check(self) -> tuple[bool, str]:
        ok, detail = self.backend.ping()
        n = self.backend.count("knowledge_facts", {"project_id": "*"}) if ok else 0
        return ok and True, f"{detail}; curated global facts: {n}" + ("" if n else " (run seeding)")

    # ---- seeding -------------------------------------------------------------------------------------------
    @traced("seed")
    def seed(self) -> dict:
        """Idempotent: facts have deterministic ids, so re-running never duplicates. Existing curated rows get label refreshes (same keys)."""
        added = refreshed = 0
        def put(pred, args, polarity="positive", quantifier=None):
            nonlocal added, refreshed
            fid = "seed:" + uuid.uuid5(uuid.NAMESPACE_URL, f"{pred}|{polarity}|{sorted((r, t['key']) for r, t in args.items())}").hex
            row = self.backend.get("knowledge_facts", {"id": fid})
            if row:
                if row["args"] != args:                                   # same keys, improved labels (e.g. "Washington" -> "Washington, D.C.")
                    self.backend.update("knowledge_facts", {"id": fid}, {"args": args, "statement": render_statement(pred, args, polarity, quantifier), "updated_at": _now()})
                    for role, term in args.items():
                        self.backend.update("knowledge_terms", {"fact_id": fid, "role": role}, {"term_key": term["key"]})
                    refreshed += 1
                if not row.get("assessment") or row.get("verification") not in ESTABLISHED_VERIFICATIONS:        # legacy row: classify as curated knowledge
                    self.backend.update("knowledge_facts", {"id": fid}, {"provenance": "internal_knowledge", "verification": "curated",
                                                                         "claim_type": integrity.classify_claim(pred, args), "assessment": self._curated_assessment(pred, args)})
                return
            self._insert(fid, "*", None, None, pred, args, polarity, quantifier, {}, 1.0, "seed_curated", "avoenix-seed-0.0.1", "active")
            added += 1
        for country, cap in seed.CAPITALS:
            put("attr.capital", {"owner": entity_term(country, "class.place"), "value": entity_term(cap, "class.place")})
        for a, b in seed.LOCATED_IN:
            put("rel.located_in", {"figure": entity_term(a, "class.place"), "ground": entity_term(b, "class.place")})
        for kind, parent in seed.TAXONOMY:
            put("rel.is_a", {"subject": kind_term(f"kind.{kind}", kind), "object": kind_term(f"kind.{parent}", parent)}, quantifier="all")
        for kind, parent in seed.NEGATIVE_TAXONOMY:
            put("rel.is_a", {"subject": kind_term(f"kind.{kind}", kind), "object": kind_term(f"kind.{parent}", parent)}, "negative", "all")
        return {"added": added, "refreshed": refreshed, "total_global": self.backend.count("knowledge_facts", {"project_id": "*"})}

    @staticmethod
    def _curated_assessment(pred: str, args: dict, source_type: str = "seed_curated") -> dict:
        ver = Verification.VERIFIED.value if source_type == "external_verified" else Verification.CURATED.value
        return Assessment(level="established", verification=ver, interpretation_confidence=1.0, support=round(SOURCE_RELIABILITY.get(source_type, 0.9), 3),
                          basis=["curated internal knowledge — authored by the AVOENIX project, not independently verified" if ver == "curated"
                                 else "independently verified source"]).to_dict()

    # ---- writing -------------------------------------------------------------------------------------------
    def _insert(self, fid, project_id, user_id, conversation_id, pred, args, polarity, quantifier, qualifiers, confidence, source_type,
                source_id, status, *, claim_type: str | None = None, verification: str | None = None, assessment: dict | None = None,
                memory_id: str | None = None) -> Fact:
        statement = render_statement(pred, args, polarity, quantifier)
        claim_type = claim_type or integrity.classify_claim(pred, args)
        if verification is None:                    # direct inserts (seed, tests, imports) classify by source; user claims go through validation
            verification = ("verified" if source_type == "external_verified" else "curated" if source_type in integrity.ESTABLISHED_SOURCES
                            else "not_applicable" if claim_type == "personal" else "unverified")
            assessment = assessment or self._curated_assessment(pred, args, source_type) if verification in ESTABLISHED_VERIFICATIONS else assessment
        row = self.backend.insert("knowledge_facts", {
            "id": fid, "project_id": project_id, "user_id": user_id, "conversation_id": conversation_id, "predicate": pred, "args": args,
            "polarity": polarity, "quantifier": quantifier, "qualifiers": qualifiers, "statement": statement, "confidence": float(confidence),
            "source_type": source_type, "source_id": source_id, "status": status, "version": 1, "created_at": _now(), "updated_at": _now(),
            "superseded_by": None, "provenance": integrity.provenance_of(source_type), "claim_type": claim_type, "verification": verification,
            "assessment": assessment or {}, "memory_id": memory_id})
        for role, term in args.items():
            self.backend.insert("knowledge_terms", {"fact_id": fid, "role": role, "term_key": term["key"], "project_id": project_id})
        return _fact_from_row(row)

    def facts_from_proposition(self, doc: ACRDocument, prop_id: str) -> tuple[list[tuple[str, dict, str, str | None, dict]], list[str]]:
        """ACR proposition -> list of (predicate, args, polarity, quantifier, qualifiers); groups are distributed. Returns (facts, problems)."""
        prop = doc.nodes[prop_id]
        problems: list[str] = []
        if isinstance(prop, Logical) and prop.op == "and":
            out = []
            for o in prop.operands:
                f, p = self.facts_from_proposition(doc, o)
                out += f
                problems += p
            return out, problems
        if not isinstance(prop, Proposition):
            return [], [f"{prop.KIND} nodes cannot be stored as knowledge"]
        args: dict[str, dict] = {}
        for role, ref in prop.args.items():
            term = term_from_node(doc, ref)
            if term is None or not is_storable_term(term) and term.get("t") != "group":
                reason = "an unresolved reference" if term and term.get("t") == "unresolved" else "a specific instance rather than a named entity or kind"
                problems.append(f"argument '{role}' is {reason}")
                return [], problems
            args[role] = term
        qualifiers: dict[str, Any] = {}
        if prop.time and (t := doc.maybe(prop.time)):
            qualifiers["time"] = {k: v for k, v in t.to_dict().items() if k in ("time_kind", "value", "offset", "anchor_relation", "granularity")}
        if prop.predicate == "rel.extreme":
            qualifiers["pole"] = prop.annotations.get("pole")
            qualifiers["adjective"] = prop.annotations.get("adjective")
        groups = [r for r, t in args.items() if t.get("t") == "group"]
        if groups:
            role = groups[0]
            facts = []
            for member in args[role]["members"]:
                facts.append((prop.predicate, {**args, role: member}, prop.polarity, prop.quantifier, qualifiers))
            return facts, problems
        return [(prop.predicate, args, prop.polarity, prop.quantifier, qualifiers)], problems

    @traced("assert_fact")
    def assert_fact(self, scope: Scope, predicate: str, args: dict[str, dict], *, polarity: str = "positive", quantifier: str | None = None,
                    qualifiers: dict | None = None, confidence: float = 0.9, source_type: str = "user_statement", source_id: str | None = None,
                    conversation_id: str | None = None, level: str = "user", correction: bool = False, revises: str | None = None,
                    reason: str | None = None, memory_id: str | None = None) -> AssertResult:
        """Record a claim. It is validated against visible knowledge first; the outcome decides its verification state and lifecycle status.

        ``confidence`` is the confidence in *interpreting* the statement (did we understand it?). It is stored, but it never turns an unsupported
        claim into knowledge: factual support lives in the assessment. ``correction=True`` marks the statement as a correction of the user's own
        earlier claim (the old claim is kept as superseded, with a revision record); ``revises`` names the claim being corrected explicitly.
        """
        if level not in ("user", "project"):
            raise ScopeError("applications may only write user- or project-level knowledge")
        if source_type in ("seed_curated", "external_verified") and level == "user":
            raise ScopeError(f"source_type {source_type!r} cannot be written at user level")
        uid = scope.user_id if level == "user" else None
        qualifiers = dict(qualifiers or {})
        claim_type = integrity.classify_claim(predicate, args)

        def run_validation(exclude=frozenset()):
            return integrity.validate(predicate=predicate, args=args, polarity=polarity, quantifier=quantifier, qualifiers=qualifiers, source_type=source_type,
                                      claim_type=claim_type, interpretation_confidence=confidence, conversation_id=conversation_id,
                                      visible=self._visible_fn(scope, conversation_id, exclude))
        val = run_validation()

        # 1) the same statement is already held -----------------------------------------------------------------------------------------------
        for f in val.same:
            if revises is None and f.status in ("active", "disputed"):
                if f.level == "user":                                   # visible user-level rows are always the caller's own
                    n = f.qualifiers.get("restatements", 0) + 1
                    self.backend.update("knowledge_facts", {"id": f.id}, {"qualifiers": {**f.qualifiers, "restatements": n}, "updated_at": _now()})
                    note = "you have said this before — repeating a claim does not add evidence for it"
                else:
                    note = f"already known ({f.source_type})"
                return AssertResult("duplicate", f, reason=note, verification=f.verification if f.level == "user" else val.assessment.verification,
                                    assessment=f.assessment if f.level == "user" else val.assessment.to_dict(), checks=val.checks)

        # 2) decide what to do with conflicts --------------------------------------------------------------------------------------------------
        est = [c for c in val.conflicts if c.other_standing == "established"]
        peers = [c for c in val.conflicts if c.other_standing == "claim"]
        own_peers = [c for c in peers if c.other.level == "user" and c.kind in ("functional", "negation")]
        status = "active"
        supersede: list[Fact] = []
        revision_reason = reason
        established_writer = source_type in integrity.ESTABLISHED_SOURCES
        new_rank = RANK.get(source_type, 0)
        if revises:
            row = self.backend.get("knowledge_facts", {"id": revises})
            if not row or row["project_id"] != scope.project_id or row.get("user_id") != scope.user_id:
                raise NotFoundError("the claim to revise was not found in your scope")
            supersede = [_fact_from_row(row)]
        if established_writer:
            if any(RANK.get(c.other.source_type, 0) > new_rank for c in val.conflicts):
                status = "disputed"
        elif est:
            status = "disputed"
        elif any(c.kind == "ordering" for c in val.conflicts):
            status = "disputed"
        elif peers and not supersede:
            if claim_type == "personal" and own_peers:
                supersede = [c.other for c in own_peers]           # the speaker is the authority on themselves: latest self-report wins, history kept
            elif correction and own_peers and len(own_peers) == len(peers):
                supersede = [c.other for c in own_peers]
            else:
                status = "disputed"                                # competing claims: preserve both, do not assume the newest is right
        if supersede:
            val = run_validation(frozenset(f.id for f in supersede))
            if not est and not any(c.kind == "ordering" for c in val.conflicts) and status == "disputed" and not established_writer:
                status = "active" if not val.conflicts else status

        # 3) write -------------------------------------------------------------------------------------------------------------------------------
        fid = "f_" + uuid.uuid4().hex[:24]
        verification = val.assessment.verification
        if status == "disputed" and verification not in (Verification.CONTRADICTED.value, Verification.CONFLICTING.value) and not established_writer:
            verification = Verification.CONFLICTING.value
        assessment = val.assessment.to_dict()
        assessment["verification"] = verification
        fact = self._insert(fid, scope.project_id, uid, conversation_id, predicate, args, polarity, quantifier, qualifiers, confidence, source_type, source_id,
                            status, claim_type=claim_type, verification=verification, assessment=assessment, memory_id=memory_id)
        conflict_ids: list[str] = []
        superseded_ids = {o.id for o in supersede}
        covered = {x.other.id for x in val.conflicts}
        conflict_items = list(val.conflicts) + [integrity.Conflict("functional", o, "replaced by a revision", "claim") for o in supersede if o.id not in covered]
        for c in conflict_items:
            cid_ = "c_" + uuid.uuid4().hex[:20]
            if c.other.id in superseded_ids:
                st, res = "resolved", "revised"
            elif c.other_standing == "established" and status == "disputed":
                st, res = "resolved", "established_precedence"
            else:
                st, res = "open", None
            self.backend.insert("knowledge_conflicts", {"id": cid_, "project_id": scope.project_id, "user_id": uid, "kind": c.kind, "fact_a": c.other.id, "fact_b": fact.id,
                                                        "status": st, "resolution": res, "note": c.note, "details": {k: v for k, v in c.extra.items()},
                                                        "created_at": _now(), "resolved_at": _now() if st == "resolved" else None, "resolved_by": "system" if st == "resolved" else None})
            conflict_ids.append(cid_)
        revision_id = None
        for old in supersede:
            self.backend.update("knowledge_facts", {"id": old.id}, {"status": "superseded", "superseded_by": fid, "updated_at": _now()})
            revision_id = "r_" + uuid.uuid4().hex[:20]
            self.backend.insert("knowledge_revisions", {"id": revision_id, "project_id": scope.project_id, "user_id": uid, "fact_id": old.id, "new_fact_id": fid,
                                                        "previous": old.to_dict(), "updated": fact.to_dict(), "source": source_type, "reason": revision_reason,
                                                        "verified": fact.verification in ESTABLISHED_VERIFICATIONS, "created_at": _now()})
        if status == "disputed" and not established_writer and not est:
            for c in peers:                                        # competing claims: the earlier claim is also marked conflicting, never overwritten
                if c.other.level == "user" and c.other.status == "active" and c.other.id not in superseded_ids and c.other.verification not in ESTABLISHED_VERIFICATIONS:
                    a = dict(c.other.assessment or {})
                    a["verification"], a["level"] = "conflicting", "conflicting"
                    a["basis"] = list(a.get("basis", [])) + [f"conflicts with a later claim ({fid})"]
                    self.backend.update("knowledge_facts", {"id": c.other.id}, {"status": "disputed", "verification": "conflicting", "assessment": a, "updated_at": _now()})
        contradictions = [c.to_dict() for c in val.conflicts]
        common = dict(verification=fact.verification, assessment=fact.assessment, conflict_ids=conflict_ids, revision_id=revision_id, checks=val.checks)
        if status == "disputed":
            why = "contradicts established knowledge; the claim is kept but not believed" if est else "conflicts with another claim; both are preserved"
            return AssertResult("disputed", fact, contradictions, reason=why, **common)
        if supersede:
            return AssertResult("superseded", fact, contradictions, [o.id for o in supersede], reason="replaced the earlier value (history kept)", **common)
        return AssertResult("stored", fact, contradictions, **common)

    @traced("assert_proposition")
    def assert_proposition(self, scope: Scope, doc: ACRDocument, prop_id: str, *, conversation_id: str | None = None,
                           source_type: str = "user_statement", source_id: str | None = None, confidence: float = 0.9,
                           correction: bool = False, reason: str | None = None) -> list[AssertResult]:
        facts, problems = self.facts_from_proposition(doc, prop_id)
        if not facts:
            return [AssertResult("rejected", reason="; ".join(problems) or "nothing storable")]
        return [self.assert_fact(scope, p, a, polarity=pol, quantifier=q, qualifiers=qual, confidence=confidence, source_type=source_type,
                                 source_id=source_id, conversation_id=conversation_id, correction=correction, reason=reason) for p, a, pol, q, qual in facts]

    # ---- lookup helpers ----------------------------------------------------------------------------------------
    def _visible_rows(self, scope: Scope, where: dict, *, statuses: Iterable[str] = VISIBLE_STATUSES, conversation_id: str | None = None,
                      user_level: bool = True) -> list[dict]:
        statuses = tuple(statuses)
        base = {**where, "status": ("in", list(statuses))}
        rows = self.backend.select("knowledge_facts", {**base, "project_id": "*"})
        rows += self.backend.select("knowledge_facts", {**base, "project_id": scope.project_id, "user_id": ("null",)})
        if user_level:
            rows += self.backend.select("knowledge_facts", {**base, "project_id": scope.project_id, "user_id": scope.user_id})
        # defence in depth: never return anything outside the visible set even if a backend bug returned it
        return [r for r in rows if r["project_id"] == "*" or (r["project_id"] == scope.project_id and r.get("user_id") in (None, scope.user_id))]

    def _visible_fn(self, scope: Scope, conversation_id: str | None, exclude=frozenset()):
        """``visible(predicate) -> [Fact]``: active and disputed facts this scope may see. Scenario premises from other conversations are not visible."""
        cache: dict[str, list[Fact]] = {}

        def visible(pred: str) -> list[Fact]:
            if pred not in cache:
                out = []
                for row in self._visible_rows(scope, {"predicate": pred}, statuses=("active", "disputed")):
                    f = _fact_from_row(row)
                    if f.id in exclude:
                        continue
                    if f.claim_type == "premise" and f.level != "global" and conversation_id is not None and f.conversation_id not in (None, conversation_id):
                        continue
                    out.append(f)
                cache[pred] = out
            return cache[pred]
        return visible

    # ---- querying --------------------------------------------------------------------------------------------------
    @traced("query")
    def query(self, scope: Scope, predicate: str | None = None, args: dict[str, str | None] | None = None, *, polarity: str | None = None,
              conversation_id: str | None = None, statuses: Iterable[str] = VISIBLE_STATUSES, include_self: bool = True,
              established_only: bool = False) -> list[Fact]:
        """Match facts by predicate and argument *keys* (``None`` = any value). Returns facts ordered by reliability.
        ``established_only`` keeps curated / independently verified knowledge and drops claims (user statements that have not been verified)."""
        where: dict[str, Any] = {}
        if predicate:
            where["predicate"] = predicate
        if polarity:
            where["polarity"] = polarity
        cands = [_fact_from_row(r) for r in self._visible_rows(scope, where, statuses=statuses)]
        if include_self and (predicate is None or True):
            cands += [f for f in self.self_model.facts() if (predicate is None or f.predicate == predicate) and (polarity is None or f.polarity == polarity)]
        out = []
        for f in cands:
            about_user = any((t or {}).get("key") == "@user" for t in f.args.values())     # facts about the user, and claims about the world, follow the user across conversations; scenario premises do not
            if conversation_id is not None and f.conversation_id not in (None, conversation_id) and not about_user and f.claim_type != "world":
                continue
            if args and not all(k is None or (f.args.get(r) or {}).get("key") == k for r, k in args.items()):
                continue
            if established_only and not f.established:
                continue
            out.append(f)
        out.sort(key=lambda f: (-RANK.get(f.source_type, 0), -f.confidence, f.created_at or ""))
        return out

    def facts_about(self, scope: Scope, term_key: str, *, limit: int = 50) -> list[Fact]:
        ids: set[str] = set()
        for pid, uid in (("*", None), (scope.project_id, None), (scope.project_id, scope.user_id)):
            for row in self.backend.select("knowledge_terms", {"project_id": pid, "term_key": term_key}, limit=500):
                ids.add(row["fact_id"])
        facts = []
        for fid in ids:
            row = self.backend.get("knowledge_facts", {"id": fid})
            if row and row["status"] == "active" and (row["project_id"] == "*" or (row["project_id"] == scope.project_id and row.get("user_id") in (None, scope.user_id))):
                facts.append(_fact_from_row(row))
        facts += [f for f in self.self_model.facts() if any(t.get("key") == term_key for t in f.args.values())]
        return facts[:limit]

    def find_entity(self, scope: Scope, label: str, *, threshold: float = 0.7, limit: int = 3) -> dict:
        """Exact (normalised) lookup first, then fuzzy suggestions. Never auto-corrects: callers decide what to do with suggestions."""
        key = norm_key(label)
        known: dict[str, dict] = {}
        for row in self._visible_rows(scope, {}, statuses=("active",)):
            for t in row["args"].values():
                if t.get("t") == "entity":
                    known[t["key"]] = t
        for f in self.self_model.facts():
            for t in f.args.values():
                if t.get("t") == "entity":
                    known[t["key"]] = t
        if key in known:
            return {"found": True, "term": known[key], "suggestions": []}
        def sim(a, b):
            return max(fuzzy_match(a, b), 1 - damerau(a, b) / max(len(a), len(b), 1) if len(a) >= 4 else 0.0)
        scored = sorted(((sim(key, k), t) for k, t in known.items()), key=lambda x: -x[0])
        return {"found": False, "term": None, "suggestions": [{"label": t["label"], "score": round(s, 3)} for s, t in scored[:limit] if s >= threshold]}

    def search(self, scope: Scope, text: str, *, limit: int = 5) -> list[tuple[Fact, float]]:
        facts = [_fact_from_row(r) for r in self._visible_rows(scope, {})] + self.self_model.facts()
        if not facts:
            return []
        corpus = [words(f.statement + " " + " ".join(render_term(t) for t in f.args.values())) for f in facts]
        scores = BM25(corpus).scores(words(text))
        ranked = sorted(zip(facts, scores), key=lambda x: -x[1])
        return [(f, s) for f, s in ranked[:limit] if s > 0]

    # ---- claims, conflicts, revisions ------------------------------------------------------------------------------------------------------
    def validate_claim(self, scope: Scope, predicate: str, args: dict[str, dict], *, polarity: str = "positive", quantifier: str | None = None,
                       source_type: str = "user_statement", conversation_id: str | None = None, confidence: float = 0.9) -> dict:
        """Dry run: what would validation say about this claim? Writes nothing."""
        v = integrity.validate(predicate=predicate, args=args, polarity=polarity, quantifier=quantifier, qualifiers={}, source_type=source_type,
                               claim_type=integrity.classify_claim(predicate, args), interpretation_confidence=confidence, conversation_id=conversation_id,
                               visible=self._visible_fn(scope, conversation_id))
        return v.to_dict()

    def _own_row(self, scope: Scope, fact_id: str) -> dict:
        row = self.backend.get("knowledge_facts", {"id": fact_id})
        visible = row and (row["project_id"] == "*" or (row["project_id"] == scope.project_id and row.get("user_id") in (None, scope.user_id)))
        if not visible:
            raise NotFoundError("claim not found in your scope")
        return row

    def claims(self, scope: Scope, *, statuses=("active", "disputed", "superseded", "retracted"), verification: str | None = None,
               subject_key: str | None = None, conversation_id: str | None = None, include_curated: bool = False, limit: int = 200) -> list[Claim]:
        """Claims visible to the caller. By default only what the caller (or their project) asserted; curated global knowledge is opt-in."""
        rows = self._visible_rows(scope, {}, statuses=statuses)
        if not include_curated:
            rows = [r for r in rows if r["project_id"] != "*"]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        out: list[Claim] = []
        open_by_fact = self._open_conflicts_by_fact(scope)
        for r in rows:
            f = _fact_from_row(r)
            if verification and f.verification != verification:
                continue
            if subject_key and not any((t or {}).get("key") == subject_key for t in f.args.values()):
                continue
            if conversation_id is not None and f.claim_type == "premise" and f.conversation_id not in (None, conversation_id):
                continue
            out.append(f.to_claim(open_by_fact.get(f.id, [])))
            if len(out) >= limit:
                break
        return out

    def _open_conflicts_by_fact(self, scope: Scope) -> dict[str, list[str]]:
        m: dict[str, list[str]] = {}
        for pid, uid in ((scope.project_id, scope.user_id), (scope.project_id, None)):
            where = {"project_id": pid, "user_id": uid} if uid else {"project_id": pid, "user_id": ("null",)}
            for c in self.backend.select("knowledge_conflicts", {**where, "status": "open"}, limit=1000):
                for fid in (c["fact_a"], c["fact_b"]):
                    m.setdefault(fid, []).append(c["id"])
        return m

    def history(self, scope: Scope, fact_id: str) -> dict:
        """Everything known about one claim: the claim, its conflicts, and its revision chain (both directions)."""
        row = self._own_row(scope, fact_id)
        f = _fact_from_row(row)
        conflicts = [c for c in self.conflicts(scope, limit=1000) if fact_id in (c["fact_a"], c["fact_b"])]
        revisions = []
        for pid, uid in ((scope.project_id, scope.user_id), (scope.project_id, None)):
            where = {"project_id": pid, "user_id": uid} if uid else {"project_id": pid, "user_id": ("null",)}
            for r in self.backend.select("knowledge_revisions", where, limit=1000):
                if fact_id in (r["fact_id"], r.get("new_fact_id")):
                    revisions.append(r)
        revisions.sort(key=lambda r: r.get("created_at") or "")
        return {"claim": f.to_claim([c["id"] for c in conflicts if c["status"] == "open"]).to_dict(), "conflicts": conflicts, "revisions": revisions}

    def conflicts(self, scope: Scope, *, status: str | None = None, limit: int = 200) -> list[dict]:
        out = []
        for pid, uid in ((scope.project_id, scope.user_id), (scope.project_id, None)):
            where: dict = {"project_id": pid, "user_id": uid} if uid else {"project_id": pid, "user_id": ("null",)}
            if status:
                where["status"] = status
            out += self.backend.select("knowledge_conflicts", where, limit=limit)
        out.sort(key=lambda c: c.get("created_at") or "", reverse=True)
        return out[:limit]

    def resolve_conflict(self, scope: Scope, conflict_id: str, resolution: str, *, winner: str | None = None, note: str | None = None,
                         resolved_by: str | None = None) -> dict:
        """Resolve an open conflict. ``manual_choice`` needs ``winner`` (one of the two claim ids): the other claim is kept, marked superseded.
        ``dismissed`` leaves both claims in place. Established knowledge is never changed by this call."""
        if resolution not in ("manual_choice", "dismissed"):
            raise InputError("resolution must be 'manual_choice' or 'dismissed'")
        c = self.backend.get("knowledge_conflicts", {"id": conflict_id})
        if not c or c["project_id"] != scope.project_id or c.get("user_id") not in (None, scope.user_id):
            raise NotFoundError("conflict not found in your scope")
        if c["status"] != "open":
            raise InputError("conflict is already resolved")
        if resolution == "manual_choice":
            if winner not in (c["fact_a"], c["fact_b"]):
                raise InputError("winner must be one of the conflicting claims")
            loser = c["fact_b"] if winner == c["fact_a"] else c["fact_a"]
            lrow, wrow = self._own_row(scope, loser), self._own_row(scope, winner)
            if lrow["project_id"] == "*" or wrow["project_id"] == "*":
                raise ScopeError("curated knowledge cannot be changed by resolving a conflict")
            self.backend.update("knowledge_facts", {"id": winner}, {"status": "active", "updated_at": _now()})
            self.backend.update("knowledge_facts", {"id": loser}, {"status": "superseded", "superseded_by": winner, "updated_at": _now()})
            rid = "r_" + uuid.uuid4().hex[:20]
            self.backend.insert("knowledge_revisions", {"id": rid, "project_id": scope.project_id, "user_id": c.get("user_id"), "fact_id": loser, "new_fact_id": winner,
                                                        "previous": _fact_from_row(lrow).to_dict(), "updated": _fact_from_row(wrow).to_dict(), "source": "manual_choice",
                                                        "reason": note, "verified": False, "created_at": _now()})
        self.backend.update("knowledge_conflicts", {"id": conflict_id}, {"status": "resolved", "resolution": resolution, "note": note or c.get("note"),
                                                                           "resolved_at": _now(), "resolved_by": resolved_by or scope.user_id})
        return self.backend.get("knowledge_conflicts", {"id": conflict_id})

    def revise(self, scope: Scope, fact_id: str, new_args: dict[str, dict], *, reason: str | None = None, source: str = "user_statement") -> AssertResult:
        """Correct one of the caller's own claims. The old claim is kept (superseded) with a revision record; the correction is validated like any
        other claim, so a correction that contradicts established knowledge is itself recorded as contradicted, not believed."""
        row = self.backend.get("knowledge_facts", {"id": fact_id})
        if not row or row["project_id"] != scope.project_id or row.get("user_id") != scope.user_id:
            raise NotFoundError("claim not found in your scope")
        if row["status"] not in ("active", "disputed"):
            raise InputError("only an active or disputed claim can be revised")
        merged = {**row["args"], **new_args}
        return self.assert_fact(scope, row["predicate"], merged, polarity=row["polarity"], quantifier=row.get("quantifier"), qualifiers=row.get("qualifiers"),
                                source_type=source, conversation_id=row.get("conversation_id"), revises=fact_id, reason=reason)

    def link_memory(self, scope: Scope, fact_id: str, memory_id: str) -> None:
        row = self.backend.get("knowledge_facts", {"id": fact_id})
        if row and row["project_id"] == scope.project_id and row.get("user_id") == scope.user_id:
            self.backend.update("knowledge_facts", {"id": fact_id}, {"memory_id": memory_id})

    # ---- management ------------------------------------------------------------------------------------------------------
    @traced("retract")
    def retract(self, scope: Scope, fact_id: str, *, level: str = "user") -> bool:
        row = self.backend.get("knowledge_facts", {"id": fact_id})
        if not row or row["project_id"] != scope.project_id or (level == "user" and row.get("user_id") != scope.user_id):
            raise NotFoundError("fact not found in your scope")
        if row["project_id"] == "*":
            raise ScopeError("global knowledge cannot be retracted by applications")
        self.backend.update("knowledge_facts", {"id": fact_id}, {"status": "retracted", "updated_at": _now()})
        return True

    def restore(self, scope: Scope, fact_id: str) -> bool:
        row = self.backend.get("knowledge_facts", {"id": fact_id})
        if not row or row["project_id"] != scope.project_id or row.get("user_id") not in (None, scope.user_id):
            raise NotFoundError("fact not found in your scope")
        self.backend.update("knowledge_facts", {"id": fact_id}, {"status": "active", "updated_at": _now()})
        return True

    def list_facts(self, scope: Scope, *, statuses=("active", "disputed", "superseded", "retracted"), limit: int = 200, user_only: bool = False) -> list[Fact]:
        rows = self._visible_rows(scope, {}, statuses=statuses)
        if user_only:
            rows = [r for r in rows if r.get("user_id") == scope.user_id]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return [_fact_from_row(r) for r in rows[:limit]]

    def stats(self, scope: Scope) -> dict:
        rows = self._visible_rows(scope, {}, statuses=("active", "disputed", "superseded", "retracted"))
        by_status: dict[str, int] = {}
        by_level: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            lvl = "global" if r["project_id"] == "*" else ("user" if r.get("user_id") else "project")
            by_level[lvl] = by_level.get(lvl, 0) + 1
        return {"visible_facts": len(rows), "by_status": by_status, "by_level": by_level, "self_model_facts": len(self.self_model.facts())}
