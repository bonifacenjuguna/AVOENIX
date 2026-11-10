"""Learning Engine: controlled, reversible, evidence-based updates. No silent self-modification.

Pipeline for every learnable input:
    feedback -> classify (preference | fact_correction | strategy_adjustment | general_knowledge)
             -> proposal (a typed, whitelisted change)
             -> evaluation (validation + conflict check + regression check on golden knowledge probes)
             -> apply (only when policy allows) -> read-back verification -> history record
             -> revert at any time (restores exactly what the change replaced)

AVOENIX only reports "learned" when ``verified`` is true: the change was written AND read back from the store.
Learning here means *updating stored preferences, facts and behaviour switches*. It does not change code,
parsers or reasoning strategies, and no statistical model is trained.

Policy
  preference / strategy_adjustment   user-scoped; auto-applied after validation and regression check
  fact_correction                    user-scoped fact; auto-applied if it does not conflict with curated knowledge; otherwise rejected
                                     (kept as a disputed claim for administrators; never served as an answer)
  general_knowledge                  project-wide; always needs an administrator decision (status ``proposed`` until approved)
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from ...core.contracts import LanguageResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import InputError, LearningRejected, NotFoundError, ScopeError
from ...core.types import Scope
from ...storage.backend import Backend
from ...storage.scoped import ScopedRepo
from ..knowledge.engine import KnowledgeEngine
from ..memory.engine import MemoryEngine

PREFERENCE_DOMAIN = {
    "style.emoji": {"none", "more", "default"}, "style.formality": {"formal", "casual", "default"}, "style.length": {"short", "long", "default"},
    "style.warmth": {"warm", "neutral", "default"}, "user.preferred_name": None,           # None = free text (validated separately)
}
STRATEGY_DOMAIN = {"behavior.show_steps": {True, False}, "behavior.ask_clarification": {True, False}}

_PREF_RULES: list[tuple[str, str, Any]] = [
    (r"\b(no|without|stop using|don'?t use|do not use|quit using)\s+(any\s+)?emoji", "style.emoji", "none"),
    (r"\b(more|use more)\s+emoji|\bi (like|love) emoji", "style.emoji", "more"),
    (r"\b(be|speak|write)\s+(more\s+)?formal(ly)?\b|\bformal tone\b", "style.formality", "formal"),
    (r"\b(be|speak|write)\s+(more\s+)?(casual(ly)?|relaxed|informal(ly)?)\b|\bcasual tone\b", "style.formality", "casual"),
    (r"\b(shorter|brief(er)?|concise|keep it short|less verbose|too long|short (answers?|replies|responses))\b", "style.length", "short"),
    (r"\b(longer|more detail(s|ed)?|elaborate|explain more|in depth|long (answers?|replies|responses))\b", "style.length", "long"),
    (r"\b(be|sound)\s+(more\s+)?(warm|friendly|kind)\b", "style.warmth", "warm"),
    (r"\b(be|sound)\s+(more\s+)?(neutral|businesslike|professional)\b", "style.warmth", "neutral"),
]
_STRATEGY_RULES: list[tuple[str, str, Any]] = [
    (r"\b(show|explain|give)\s+(me\s+)?(your\s+)?(steps|reasoning|work|working)\b|\bwalk me through\b", "behavior.show_steps", True),
    (r"\b(don'?t|do not|stop)\s+(show|explain|give)\w*\s+(me\s+)?(your\s+)?(steps|reasoning|work|working)\b|\bjust (the )?answer\b", "behavior.show_steps", False),
    (r"\bask me (a )?(question|questions|before)|\bask (for )?clarification\b", "behavior.ask_clarification", True),
    (r"\b(don'?t|do not|stop)\s+ask(ing)?\s+(me\s+)?(questions|for clarification)\b", "behavior.ask_clarification", False),
]
_NAME = re.compile(r"\b(?i:call me|you can call me|please call me|i go by)\s+([A-Z][a-zA-Z'-]{1,30})\b")
_CORRECTION_MARK = re.compile(r"^\s*(?:no\b[,.!]?|nope\b[,.!]?|actually\b[,:]?|wrong\b[,.!]?|incorrect\b[,.!]?|that'?s (?:wrong|incorrect|not right)\b[,.!:]?|you(?:'re| are) wrong\b[,.!:]?)\s*(?P<rest>.*)$", re.I)
_TEACH = re.compile(r"^\s*(?:please\s+)?(?:remember|learn|note|know)\s+that\s+(?P<rest>.+)$", re.I)

GOLDEN: list[dict] = [
    {"name": "capital_france", "predicate": "attr.capital", "args": {"owner": "france"}, "expect_value": "paris"},
    {"name": "capital_kenya", "predicate": "attr.capital", "args": {"owner": "kenya"}, "expect_value": "nairobi"},
    {"name": "capital_japan", "predicate": "attr.capital", "args": {"owner": "japan"}, "expect_value": "tokyo"},
    {"name": "dog_is_mammal", "predicate": "rel.is_a", "args": {"subject": "kind.dog", "object": "kind.mammal"}, "expect_present": True},
    {"name": "whale_not_fish", "predicate": "rel.is_a", "args": {"subject": "kind.whale", "object": "kind.fish"}, "polarity": "negative", "expect_present": True},
]


def _now(clock) -> str:
    return clock.now().isoformat()


class LearningEngine(Engine):
    info = EngineInfo(
        key="learning", name="Learning Engine", status=EngineStatus.PARTIAL,
        summary="Feedback -> classified proposal -> validation + regression check -> verified, reversible, audited update of preferences, facts and behaviour switches.",
        depends_on=("memory", "knowledge", "language"),
        capabilities=("four update classes (preference, fact correction, strategy adjustment, general knowledge)", "whitelisted, typed changes",
                      "golden-probe regression check with automatic rejection", "read-back persistence verification", "revert with exact restoration",
                      "full history in learning_records", "administrator approval for project-wide knowledge"),
        limitations=("Learns stored data only: no parser, strategy or model changes; nothing is trained.",
                     "Classification is rule-based on English phrasing; unusual wording is not recognised as feedback.",
                     "The golden regression suite is small (5 probes) and only covers knowledge answers.",
                     "Fact corrections that conflict with curated knowledge are never applied automatically."),
    )

    def self_check(self) -> tuple[bool, str]:
        a, b = self.classify("Please don't use emoji"), self.classify("What is the capital of France?")
        ok = bool(a) and a["kind"] == "preference" and b is None
        return ok, "classification probe (preference detected, question ignored)" if ok else "classification probe failed"

    def __init__(self, backend: Backend, knowledge: KnowledgeEngine, memory: MemoryEngine, *, language=None, golden: list[dict] | None = None,
                 extra_regression: Callable[[Scope], list[dict]] | None = None):
        super().__init__()
        self.backend, self.knowledge, self.memory, self.language = backend, knowledge, memory, language
        self.golden = golden if golden is not None else GOLDEN
        self.extra_regression = extra_regression
        self.clock = memory.clock

    # ---- feedback --------------------------------------------------------------------------------------------------------
    @traced("submit_feedback")
    def submit_feedback(self, scope: Scope, kind: str, *, rating: int | None = None, comment: str | None = None, message_id: str | None = None,
                        conversation_id: str | None = None, payload: dict | None = None) -> dict:
        if kind not in ("rating", "correction", "report", "comment"):
            raise InputError("kind must be rating, correction, report or comment")
        if rating is not None and rating not in (-1, 0, 1):
            raise InputError("rating must be -1, 0 or 1")
        if comment is not None and len(comment) > 4000:
            raise InputError("comment too long")
        return ScopedRepo(self.backend, scope).insert("feedback", {
            "id": "fb_" + uuid.uuid4().hex[:16], "conversation_id": conversation_id, "message_id": message_id, "kind": kind, "rating": rating,
            "comment": comment, "payload": payload or {}, "status": "recorded", "created_at": _now(self.clock)})

    # ---- classification -------------------------------------------------------------------------------------------------------
    def classify(self, text: str, lr: LanguageResult | None = None) -> dict | None:
        """Return {'kind','change'|'statement'} or None when the text contains nothing learnable."""
        t = text.strip()
        if m := _NAME.search(t):
            return {"kind": "preference", "change": {"key": "user.preferred_name", "value": m.group(1)}, "basis": "call-me pattern"}
        for pat, key, val in _PREF_RULES:
            if re.search(pat, t, re.I):
                return {"kind": "preference", "change": {"key": key, "value": val}, "basis": f"matched /{pat[:40]}…/"}
        for pat, key, val in _STRATEGY_RULES:
            if re.search(pat, t, re.I):
                return {"kind": "strategy_adjustment", "change": {"key": key, "value": val}, "basis": f"matched /{pat[:40]}…/"}
        if m := _TEACH.match(t):
            return {"kind": "general_knowledge", "statement": m.group("rest").strip(), "basis": "explicit teach marker"}
        if m := _CORRECTION_MARK.match(t):
            rest = m.group("rest").strip()
            if len(rest.split()) >= 3:
                return {"kind": "fact_correction", "statement": rest, "basis": "correction marker"}
        return None

    def _statement_to_facts(self, scope: Scope, statement: str) -> tuple[list[tuple], list[str]]:
        if self.language is None:
            raise InputError("language engine not configured for fact extraction")
        from ..input.engine import InputProcessingEngine
        lr = self.language.analyze(InputProcessingEngine().process(statement))
        facts: list[tuple] = []
        problems: list[str] = []
        for rid in lr.doc.roots:
            n = lr.doc.nodes[rid]
            if n.KIND == "intention" and n.act in ("assert", "inform", "correct", "confirm"):
                for pid in n.content:
                    f, p = self.knowledge.facts_from_proposition(lr.doc, pid)
                    facts += f
                    problems += p
        return facts, problems

    # ---- records ---------------------------------------------------------------------------------------------------------------
    def _new_record(self, scope: Scope, kind: str, proposal: dict, *, feedback_id: str | None = None) -> dict:
        return self.backend.insert("learning_records", {
            "id": "lr_" + uuid.uuid4().hex[:16], "project_id": scope.project_id, "user_id": scope.user_id, "kind": kind, "status": "proposed",
            "proposal": proposal, "evaluation": None, "applied_change": None, "reason": None, "source_feedback_id": feedback_id,
            "created_at": _now(self.clock), "decided_at": None, "decided_by": None, "applied_at": None, "reverted_at": None})

    def _get(self, scope: Scope, record_id: str, *, admin: bool = False) -> dict:
        row = self.backend.get("learning_records", {"id": record_id})
        if not row or row["project_id"] != scope.project_id or (not admin and row.get("user_id") not in (scope.user_id,)):
            raise NotFoundError("learning record not found")
        return row

    def _set(self, record_id: str, **values) -> dict:
        self.backend.update("learning_records", {"id": record_id}, values)
        return self.backend.get("learning_records", {"id": record_id})

    def history(self, scope: Scope, *, limit: int = 100, include_project: bool = False) -> list[dict]:
        rows = self.backend.select("learning_records", {"project_id": scope.project_id})
        rows = [r for r in rows if r.get("user_id") == scope.user_id or (include_project and r.get("user_id") is None)]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows[:limit]

    def pending(self, project_id: str) -> list[dict]:
        return [r for r in self.backend.select("learning_records", {"project_id": project_id, "status": "proposed"})]

    # ---- evaluation ------------------------------------------------------------------------------------------------------------
    def run_golden(self, scope: Scope) -> list[dict]:
        out = []
        for g in self.golden:
            facts = self.knowledge.query(scope, g["predicate"], g["args"], polarity=g.get("polarity"), include_self=False)
            if "expect_value" in g:
                got = facts[0].key_of("value") if facts else None
                out.append({"name": g["name"], "ok": got == g["expect_value"], "got": got, "expected": g["expect_value"]})
            else:
                out.append({"name": g["name"], "ok": bool(facts) == g.get("expect_present", True), "got": bool(facts)})
        if self.extra_regression:
            out += self.extra_regression(scope)
        return out

    @staticmethod
    def _diff(before: list[dict], after: list[dict]) -> list[dict]:
        b = {r["name"]: r for r in before}
        return [{"name": r["name"], "before": b.get(r["name"]), "after": r} for r in after if b.get(r["name"], {}).get("ok") != r["ok"] or b.get(r["name"], {}).get("got") != r.get("got")]

    def _validate(self, kind: str, change: dict) -> list[str]:
        problems = []
        if kind == "preference":
            dom = PREFERENCE_DOMAIN.get(change["key"], "missing")
            if dom == "missing":
                problems.append(f"preference key {change['key']!r} is not whitelisted")
            elif dom is not None and change["value"] not in dom:
                problems.append(f"value {change['value']!r} not allowed for {change['key']}")
            elif change["key"] == "user.preferred_name" and not re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,30}", str(change["value"])):
                problems.append("preferred name must be 2-31 letters")
        elif kind == "strategy_adjustment":
            dom = STRATEGY_DOMAIN.get(change["key"])
            if dom is None or change["value"] not in dom:
                problems.append(f"strategy switch {change['key']!r}={change['value']!r} is not whitelisted")
        return problems

    # ---- main entry --------------------------------------------------------------------------------------------------------------
    @traced("learn_from_message")
    def learn_from_message(self, scope: Scope, text: str, *, conversation_id: str | None = None, feedback_id: str | None = None,
                           auto_apply: bool = True) -> dict | None:
        c = self.classify(text)
        if c is None:
            return None
        kind = c["kind"]
        if kind in ("preference", "strategy_adjustment"):
            rec = self._new_record(scope, kind, {"change": c["change"], "basis": c["basis"], "source_text": text[:300]}, feedback_id=feedback_id)
            problems = self._validate(kind, c["change"])
            if problems:
                rec = self._set(rec["id"], status="rejected", reason="; ".join(problems), decided_at=_now(self.clock), decided_by="system:validation",
                                evaluation={"validation": problems})
                return self._summary(rec)
            return self._summary(self.apply(scope, rec["id"], decided_by="system:auto") if auto_apply else rec)
        facts, problems = self._statement_to_facts(scope, c["statement"])
        if not facts:
            rec = self._new_record(scope, kind, {"statement": c["statement"], "basis": c["basis"], "facts": []}, feedback_id=feedback_id)
            rec = self._set(rec["id"], status="rejected", reason="could not turn the statement into storable facts: " + ("; ".join(problems) or "no proposition found"),
                            decided_at=_now(self.clock), decided_by="system:validation", evaluation={"problems": problems})
            return self._summary(rec)
        packed = [{"predicate": p, "args": a, "polarity": pol, "quantifier": q, "qualifiers": ql} for p, a, pol, q, ql in facts]
        rec = self._new_record(scope, kind, {"statement": c["statement"], "basis": c["basis"], "facts": packed, "conversation_id": conversation_id}, feedback_id=feedback_id)
        if kind == "general_knowledge":
            return self._summary(self._set(rec["id"], reason="project-wide knowledge needs an administrator decision"))
        return self._summary(self.apply(scope, rec["id"], decided_by="system:auto") if auto_apply else rec)

    @staticmethod
    def _summary(rec: dict) -> dict:
        ac = rec.get("applied_change") or {}
        return {"id": rec["id"], "kind": rec["kind"], "status": rec["status"], "verified": bool(ac.get("verified")) and rec["status"] == "applied",
                "reason": rec.get("reason"), "proposal": rec["proposal"], "evaluation": rec.get("evaluation"), "applied_change": rec.get("applied_change")}

    # ---- apply / revert ----------------------------------------------------------------------------------------------------------
    @traced("apply")
    def apply(self, scope: Scope, record_id: str, *, decided_by: str, admin: bool = False) -> dict:
        rec = self._get(scope, record_id, admin=admin)
        if rec["status"] not in ("proposed", "approved"):
            raise LearningRejected(f"record is {rec['status']}, cannot apply")
        kind, prop = rec["kind"], rec["proposal"]
        if kind == "general_knowledge" and not admin:
            raise ScopeError("applying project-wide knowledge requires an administrator")
        before = self.run_golden(scope)
        applied: dict[str, Any] = {"type": kind}
        try:
            if kind in ("preference", "strategy_adjustment"):
                ch = prop["change"]
                problems = self._validate(kind, ch)
                if problems:
                    raise LearningRejected("; ".join(problems))
                prev = self.memory.get_preference(scope, ch["key"], None)
                r = self.memory.set_preference(scope, ch["key"], ch["value"], source="learned")
                applied.update(memory_id=r["id"], superseded=r.get("superseded", []), previous=prev, key=ch["key"], value=ch["value"],
                               noop=r.get("action") == "unchanged")
            else:
                level = "project" if kind == "general_knowledge" else "user"
                ids, sup, disputed = [], [], []
                for f in prop["facts"]:
                    r = self.knowledge.assert_fact(scope, f["predicate"], f["args"], polarity=f["polarity"], quantifier=f.get("quantifier"), qualifiers=f.get("qualifiers"),
                                                   confidence=0.8, source_type="learned" if level == "project" else "user_statement", level=level,
                                                   conversation_id=prop.get("conversation_id") if level == "user" else None)
                    if r.status == "disputed":
                        disputed.append({"fact_id": r.fact.id, "contradictions": [c.get("note") or c.get("with", {}).get("statement") for c in r.contradictions]})
                    if r.fact is not None:
                        ids.append(r.fact.id)
                    sup += r.superseded
                applied.update(fact_ids=ids, superseded=sup, disputed=disputed, level=level)
                if disputed:                # all-or-nothing: nothing from a conflicting correction stays in the store
                    self._undo(scope, applied)
                    raise LearningRejected("conflicts with existing higher-reliability or order-inconsistent knowledge; kept only as a disputed claim")
            after = self.run_golden(scope)
            regressions = self._diff(before, after)
            evaluation = {"golden_before": sum(r["ok"] for r in before), "golden_after": sum(r["ok"] for r in after), "total": len(after), "regressions": regressions}
            if regressions:
                self._undo(scope, applied)
                raise LearningRejected(f"regression in {len(regressions)} golden probe(s); change undone")
            applied["verified"] = self._verify(scope, applied)
            if not applied["verified"]:
                self._undo(scope, applied)
                rec = self._set(record_id, status="failed", reason="write could not be read back; change undone", evaluation=evaluation, applied_change=applied,
                                decided_at=_now(self.clock), decided_by=decided_by)
                return rec
            return self._set(record_id, status="applied", evaluation=evaluation, applied_change=applied, decided_at=_now(self.clock), decided_by=decided_by,
                             applied_at=_now(self.clock), reason=None)
        except LearningRejected as e:
            return self._set(record_id, status="rejected", reason=str(e), applied_change=({**applied, "undone": True} if applied.get("disputed") else None),
                             evaluation=locals().get("evaluation") or {"golden_before": sum(r["ok"] for r in before), "total": len(before)},
                             decided_at=_now(self.clock), decided_by=decided_by)

    def _verify(self, scope: Scope, a: dict) -> bool:
        if a["type"] in ("preference", "strategy_adjustment"):
            return self.memory.get_preference(scope, a["key"], object()) == a["value"]
        for fid in a.get("fact_ids", []):
            row = self.backend.get("knowledge_facts", {"id": fid})
            if not row or row["status"] != "active":
                return False
        return bool(a.get("fact_ids"))

    def _undo(self, scope: Scope, a: dict) -> None:
        if a.get("noop"):
            return
        if a["type"] in ("preference", "strategy_adjustment"):
            if a.get("memory_id"):
                self.memory.repo(scope).update("memories", {"id": a["memory_id"]}, {"status": "deleted"})
            for old in a.get("superseded", []):
                self.memory.repo(scope).update("memories", {"id": old}, {"status": "active"})
        else:
            for fid in a.get("fact_ids", []):
                self.backend.update("knowledge_facts", {"id": fid}, {"status": "retracted"})
            for old in a.get("superseded", []):
                self.backend.update("knowledge_facts", {"id": old}, {"status": "active", "superseded_by": None})

    @traced("revert")
    def revert(self, scope: Scope, record_id: str, *, decided_by: str, admin: bool = False) -> dict:
        rec = self._get(scope, record_id, admin=admin)
        if rec["status"] != "applied":
            raise LearningRejected(f"only applied records can be reverted (status: {rec['status']})")
        a = rec["applied_change"] or {}
        self._undo(scope, a)
        ok = not self._verify(scope, a) if a.get("type") != "preference" and a.get("type") != "strategy_adjustment" else True
        return self._set(record_id, status="reverted", reverted_at=_now(self.clock), decided_by=decided_by,
                         reason=None if ok else "revert could not be verified")

    def approve(self, scope: Scope, record_id: str, *, admin_id: str) -> dict:
        rec = self._get(scope, record_id, admin=True)
        if rec["status"] != "proposed":
            raise LearningRejected(f"record is {rec['status']}")
        self._set(record_id, status="approved", decided_by=admin_id, decided_at=_now(self.clock))
        return self.apply(scope, record_id, decided_by=admin_id, admin=True)

    def reject(self, scope: Scope, record_id: str, *, admin_id: str, reason: str = "rejected by administrator") -> dict:
        rec = self._get(scope, record_id, admin=True)
        if rec["status"] not in ("proposed", "approved"):
            raise LearningRejected(f"record is {rec['status']}")
        return self._set(record_id, status="rejected", reason=reason, decided_by=admin_id, decided_at=_now(self.clock))
