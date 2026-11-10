"""Knowledge Engine: structured, provenance-aware, contradiction-aware fact storage and retrieval.

Visibility model (``project_id`` / ``user_id`` columns of ``knowledge_facts``):

* ``project_id = '*'``              curated global knowledge shipped with AVOENIX (read-only for applications)
* ``project_id = P, user_id NULL``  knowledge shared inside project P (written by administrators)
* ``project_id = P, user_id = U``   what user U told the system (never visible to other users or projects)

Information supplied by users, curated seed knowledge, externally verified knowledge and internally derived
conclusions are kept apart by ``source_type`` and ranked by reliability when they conflict. A user statement can
never silently overwrite curated knowledge: it is stored as *disputed* and reported back.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ...algorithms.confidence import SOURCE_RELIABILITY, noisy_or
from ...algorithms.partial_order import PartialOrder
from ...algorithms.text_similarity import BM25, damerau, fuzzy_match, words
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import NotFoundError, ScopeError, StorageError
from ...core.types import Scope
from ...representation import ACRDocument, Logical, Proposition
from ...storage.backend import Backend
from ...version import PLATFORM_VERSION
from . import seed
from .terms import (
    SELF_SYSTEM, SELF_USER, concept_term, entity_term, is_storable_term, kind_term, norm_key, render_statement, render_term, term_from_node,
)

RANK = {"external_verified": 5, "seed_curated": 4, "system": 4, "learned": 3, "user_statement": 2, "derived": 1}
FUNCTIONAL_PREDICATES = {"attr.name", "attr.age", "attr.birthday", "attr.height", "attr.weight", "attr.address", "attr.job", "attr.capital",
                         "attr.president", "attr.population", "attr.currency", "attr.color", "attr.colour", "attr.favorite", "attr.language"}
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

    def key_of(self, role: str) -> str | None:
        t = self.args.get(role)
        return t.get("key") if t else None

    def to_dict(self) -> dict:
        return {"id": self.id, "predicate": self.predicate, "args": self.args, "polarity": self.polarity, "quantifier": self.quantifier,
                "statement": self.statement, "confidence": self.confidence, "source_type": self.source_type, "source_id": self.source_id,
                "status": self.status, "level": self.level, "conversation_id": self.conversation_id, "qualifiers": self.qualifiers,
                "created_at": self.created_at, "version": self.version}

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

    def to_dict(self) -> dict:
        return {"status": self.status, "fact": self.fact.to_dict() if self.fact else None, "contradictions": self.contradictions,
                "superseded": self.superseded, "reason": self.reason}


def _fact_from_row(row: dict, scope: Scope | None = None) -> Fact:
    level = "global" if row["project_id"] == "*" else ("user" if row.get("user_id") else "project")
    return Fact(id=row["id"], predicate=row["predicate"], args=row["args"], polarity=row["polarity"], quantifier=row.get("quantifier"),
                statement=row["statement"], confidence=float(row["confidence"]), source_type=row["source_type"], source_id=row.get("source_id"),
                status=row["status"], level=level, conversation_id=row.get("conversation_id"), qualifiers=row.get("qualifiers") or {},
                created_at=row.get("created_at"), version=row.get("version") or 1)


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
                            status="active", level="system"))

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
        """Idempotent: facts have deterministic ids, so re-running never duplicates."""
        added = 0
        def put(pred, args, polarity="positive", quantifier=None):
            nonlocal added
            fid = "seed:" + uuid.uuid5(uuid.NAMESPACE_URL, f"{pred}|{polarity}|{sorted((r, t['key']) for r, t in args.items())}").hex
            if self.backend.get("knowledge_facts", {"id": fid}):
                return
            self._insert(fid, "*", None, None, pred, args, polarity, quantifier, {}, 1.0, "seed_curated", "avoenix-seed-0.0.0", "active")
            added += 1
        for country, cap in seed.CAPITALS:
            put("attr.capital", {"owner": entity_term(country, "class.place"), "value": entity_term(cap, "class.place")})
        for a, b in seed.LOCATED_IN:
            put("rel.located_in", {"figure": entity_term(a, "class.place"), "ground": entity_term(b, "class.place")})
        for kind, parent in seed.TAXONOMY:
            put("rel.is_a", {"subject": kind_term(f"kind.{kind}", kind), "object": kind_term(f"kind.{parent}", parent)}, quantifier="all")
        for kind, parent in seed.NEGATIVE_TAXONOMY:
            put("rel.is_a", {"subject": kind_term(f"kind.{kind}", kind), "object": kind_term(f"kind.{parent}", parent)}, "negative", "all")
        return {"added": added, "total_global": self.backend.count("knowledge_facts", {"project_id": "*"})}

    # ---- writing -------------------------------------------------------------------------------------------
    def _insert(self, fid, project_id, user_id, conversation_id, pred, args, polarity, quantifier, qualifiers, confidence, source_type,
                source_id, status) -> Fact:
        statement = render_statement(pred, args, polarity, quantifier)
        row = self.backend.insert("knowledge_facts", {
            "id": fid, "project_id": project_id, "user_id": user_id, "conversation_id": conversation_id, "predicate": pred, "args": args,
            "polarity": polarity, "quantifier": quantifier, "qualifiers": qualifiers, "statement": statement, "confidence": float(confidence),
            "source_type": source_type, "source_id": source_id, "status": status, "version": 1, "created_at": _now(), "updated_at": _now()})
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
                    conversation_id: str | None = None, level: str = "user") -> AssertResult:
        if level not in ("user", "project"):
            raise ScopeError("applications may only write user- or project-level knowledge")
        if source_type in ("seed_curated", "external_verified") and level == "user":
            raise ScopeError(f"source_type {source_type!r} cannot be written at user level")
        uid = scope.user_id if level == "user" else None
        qualifiers = dict(qualifiers or {})
        existing = self._lookup_same(scope, predicate, args)
        for f in existing:
            if f.polarity == polarity and f.quantifier == quantifier:
                if f.level == "user" and f.status == "active":
                    self.backend.update("knowledge_facts", {"id": f.id}, {"qualifiers": {**f.qualifiers, "corroborations": f.qualifiers.get("corroborations", 0) + 1},
                                                                          "confidence": noisy_or([f.confidence, confidence]), "updated_at": _now()})
                return AssertResult("duplicate", f, reason="already known" + (f" ({f.source_type})" if f.level != "user" else ""))
        contradictions: list[dict] = []
        supersede: list[Fact] = []
        for f in existing:
            if f.polarity != polarity and f.quantifier == quantifier and f.status == "active":
                contradictions.append({"kind": "negation", "with": f.to_dict()})
        for f in self._functional_conflicts(scope, predicate, args):
            contradictions.append({"kind": "functional", "with": f.to_dict(), "note": f"{predicate} normally has a single value"})
        cyc = self._ordering_conflict(scope, predicate, args, polarity, conversation_id)
        if cyc:
            contradictions.append(cyc)
        new_rank = RANK.get(source_type, 0)
        status = "active"
        if contradictions:
            blockers = [c for c in contradictions if RANK.get(c["with"]["source_type"], 0) > new_rank] if all("with" in c for c in contradictions) else contradictions
            same_user_updates = [c for c in contradictions if "with" in c and c["with"]["level"] == "user" and c["kind"] in ("functional", "negation")]
            if any(c["kind"] == "ordering" for c in contradictions) or blockers:
                status = "disputed"
            elif same_user_updates:
                for c in same_user_updates:
                    old = _fact_from_row(self.backend.get("knowledge_facts", {"id": c["with"]["id"]}))
                    supersede.append(old)
            else:
                status = "disputed"
        fid = "f_" + uuid.uuid4().hex[:24]
        fact = self._insert(fid, scope.project_id, uid, conversation_id, predicate, args, polarity, quantifier, qualifiers, confidence,
                            source_type, source_id, status)
        for old in supersede:
            self.backend.update("knowledge_facts", {"id": old.id}, {"status": "superseded", "superseded_by": fid, "updated_at": _now()})
        if status == "disputed":
            return AssertResult("disputed", fact, contradictions, reason="conflicts with higher-reliability or order-inconsistent information")
        if supersede:
            return AssertResult("superseded", fact, contradictions, [o.id for o in supersede], reason="replaced the earlier value (history kept)")
        return AssertResult("stored", fact)

    @traced("assert_proposition")
    def assert_proposition(self, scope: Scope, doc: ACRDocument, prop_id: str, *, conversation_id: str | None = None,
                           source_type: str = "user_statement", source_id: str | None = None, confidence: float = 0.9) -> list[AssertResult]:
        facts, problems = self.facts_from_proposition(doc, prop_id)
        if not facts:
            return [AssertResult("rejected", reason="; ".join(problems) or "nothing storable")]
        return [self.assert_fact(scope, p, a, polarity=pol, quantifier=q, qualifiers=qual, confidence=confidence, source_type=source_type,
                                 source_id=source_id, conversation_id=conversation_id) for p, a, pol, q, qual in facts]

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

    def _lookup_same(self, scope: Scope, predicate: str, args: dict[str, dict]) -> list[Fact]:
        out = []
        for row in self._visible_rows(scope, {"predicate": predicate}, statuses=("active", "disputed")):
            if all((row["args"].get(r) or {}).get("key") == t["key"] for r, t in args.items()) and set(row["args"]) == set(args):
                out.append(_fact_from_row(row))
        return out

    def _functional_conflicts(self, scope: Scope, predicate: str, args: dict[str, dict]) -> list[Fact]:
        if predicate not in FUNCTIONAL_PREDICATES or "owner" not in args or "value" not in args:
            return []
        out = []
        for row in self._visible_rows(scope, {"predicate": predicate}):
            f = _fact_from_row(row)
            if f.polarity == "positive" and f.key_of("owner") == args["owner"]["key"] and f.key_of("value") != args["value"]["key"]:
                out.append(f)
        return out

    def _ordering_conflict(self, scope: Scope, predicate: str, args: dict[str, dict], polarity: str, conversation_id: str | None) -> dict | None:
        if predicate not in ("rel.exceeds", "rel.equal_on") or polarity != "positive" or "dimension" not in args:
            return None
        dim = args["dimension"]["key"]
        po = PartialOrder()
        for row in self._visible_rows(scope, {"predicate": "rel.exceeds"}):
            f = _fact_from_row(row)
            if f.key_of("dimension") == dim and f.polarity == "positive" and (conversation_id is None or f.conversation_id in (None, conversation_id)):
                po.add_greater(f.key_of("greater"), f.key_of("lesser"), f.id)
        if predicate == "rel.exceeds":
            po.add_greater(args["greater"]["key"], args["lesser"]["key"], "new")
        cycle = po.find_cycle()
        if cycle:
            return {"kind": "ordering", "note": "adding this relation would make the ordering circular on " + dim, "cycle": [str(c) for c in cycle]}
        return None

    # ---- querying --------------------------------------------------------------------------------------------------
    @traced("query")
    def query(self, scope: Scope, predicate: str | None = None, args: dict[str, str | None] | None = None, *, polarity: str | None = None,
              conversation_id: str | None = None, statuses: Iterable[str] = VISIBLE_STATUSES, include_self: bool = True) -> list[Fact]:
        """Match facts by predicate and argument *keys* (``None`` = any value). Returns facts ordered by reliability."""
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
            about_user = any((t or {}).get("key") == "@user" for t in f.args.values())     # facts about the user follow the user across conversations
            if conversation_id is not None and f.conversation_id not in (None, conversation_id) and not about_user:
                continue
            if args and not all(k is None or (f.args.get(r) or {}).get("key") == k for r, k in args.items()):
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
