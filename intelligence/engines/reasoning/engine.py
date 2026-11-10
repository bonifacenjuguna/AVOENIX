"""Reasoning Engine: turns the propositions of an ACR document into conclusions using pluggable strategies.

The engine does not parse language and does not render language. It consumes ACR (plus the caller's visible knowledge)
and produces structured ``Conclusion`` objects with steps, evidence, assumptions and confidence. Strategies are
registered at runtime (``register``), so new inference methods can be added without changing the engine.
"""

from __future__ import annotations

import time

from ...core.contracts import Conclusion, LanguageResult, ReasoningResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.types import Scope
from ...representation import Intention, Proposition
from ..knowledge.engine import KnowledgeEngine
from .facts import ASSERTING_ACTS, FactBase
from .strategies import DEFAULT_STRATEGIES, Query, Strategy, build_query

DECISIVE = ("yes", "no", "answered", "contradiction", "undefined", "consistent")
QUESTION_ACTS = ("request_information", "request_confirmation")


class ReasoningEngine(Engine):
    info = EngineInfo(
        key="reasoning", name="Reasoning Engine", status=EngineStatus.PARTIAL,
        summary="Pluggable strategies over ACR: relational ordering (+CSP cross-check), taxonomy/syllogism, containment, attribute lookup, exact arithmetic, contradiction detection, induction, hypothesis generation.",
        depends_on=("knowledge", "language"),
        capabilities=("transitive ordering with equality classes, negated comparisons, superlatives and numeric measurements",
                      "backtracking CSP enumeration used to cross-check and to score hypotheses",
                      "is-a / property inheritance syllogisms and located_in chains",
                      "exact rational arithmetic", "contradiction detection (negation, single-valued attributes, ordering cycles)",
                      "Laplace-based inductive generalisation (tentative)", "unknown / underdetermined reporting with the missing information",
                      "runtime registration of additional strategies"),
        limitations=("Coverage is limited to the predicates the English front-end can produce; unsupported constructions yield 'unsupported', not guesses.",
                     "No temporal reasoning, no numeric word problems with state, no probabilistic inference.",
                     "Abduction is limited to ordering hypotheses; there is no general rule-based abductive engine.",
                     "Confidence values are evidence-support scores, not calibrated probabilities."),
    )

    def self_check(self) -> tuple[bool, str]:
        from ..input.engine import InputProcessingEngine
        from ..language.engine import LanguageEngine
        lr = LanguageEngine().analyze(InputProcessingEngine().process("John is older than Peter. Peter is older than David. Who is the youngest?"))
        res = self.reason(Scope("_selfcheck", "_selfcheck"), lr)
        ok = any(c.status == "answered" and "David" in str(c.answer) for c in res.conclusions)
        return ok, "ordering probe (John > Peter > David => David youngest)" if ok else "ordering probe failed"

    def __init__(self, knowledge: KnowledgeEngine, strategies: list[Strategy] | None = None):
        super().__init__()
        self.knowledge = knowledge
        self.strategies: list[Strategy] = strategies if strategies is not None else [s() for s in DEFAULT_STRATEGIES]

    # ---- extension ---------------------------------------------------------------------------------------------------
    def register(self, strategy: Strategy, *, first: bool = False) -> None:
        self.strategies = [s for s in self.strategies if s.name != strategy.name]
        if first:
            self.strategies.insert(0, strategy)
        else:
            self.strategies.append(strategy)

    def unregister(self, name: str) -> bool:
        before = len(self.strategies)
        self.strategies = [s for s in self.strategies if s.name != name]
        return len(self.strategies) < before

    def describe_strategies(self) -> list[dict]:
        return [s.describe() for s in self.strategies]

    # ---- main --------------------------------------------------------------------------------------------------------
    @traced("reason")
    def reason(self, scope: Scope, lr: LanguageResult, *, conversation_id: str | None = None) -> ReasoningResult:
        t0 = time.perf_counter()
        doc = lr.doc
        fb = FactBase.load(scope, self.knowledge, doc, conversation_id)
        queries = self._queries(lr)
        tried: list[dict] = []
        question_conclusions: list[Conclusion] = []
        assertion_conclusions: list[Conclusion] = []
        for q in queries:
            primary, runs = self._answer(q, fb)
            tried += runs
            (question_conclusions if q.kind != "assertion" else assertion_conclusions).append(primary)
        assertion_conclusions = self._dedupe_assertions(assertion_conclusions)
        conclusions = assertion_conclusions + question_conclusions
        # a contradiction in the premises poisons later answers: say so on each question conclusion
        contradictions = [c for c in assertion_conclusions if c.status == "contradiction"]
        if contradictions:
            for c in question_conclusions:
                c.notes.append("The statements given in this conversation contradict each other, so this answer may not be reliable.")
        for s in fb.skipped:
            if conclusions:
                conclusions[0].notes.append("not stored as knowledge: " + s)
        primary = (question_conclusions or conclusions or [None])[0]
        if contradictions and not question_conclusions:
            primary = contradictions[0]
        return ReasoningResult(conclusions=conclusions, strategies_tried=tried, elapsed_ms=(time.perf_counter() - t0) * 1000, primary=primary)

    # ---- helpers -----------------------------------------------------------------------------------------------------------
    def _queries(self, lr: LanguageResult) -> list[Query]:
        doc, out = lr.doc, []
        for rid in doc.roots:
            node = doc.nodes[rid]
            if not isinstance(node, Intention):
                continue
            qk = node.features.get("question_kind")
            if node.act in QUESTION_ACTS:
                if qk == "arithmetic" and lr.math:
                    out.append(Query(kind="arithmetic", doc=doc, prop=None, question_kind=qk, math=lr.math))
                    continue
                made = 0
                for pid in node.content:
                    n = doc.nodes.get(pid)
                    if isinstance(n, Proposition):
                        out.append(build_query("question", doc, n, question_kind=qk, wh=node.features.get("wh")))
                        made += 1
                if not made:       # the question could not be turned into a proposition: say so instead of staying silent
                    out.append(Query(kind="question", doc=doc, prop=None, question_kind=qk))
            elif node.act in ASSERTING_ACTS:
                for pid in node.content:
                    n = doc.nodes.get(pid)
                    if isinstance(n, Proposition):
                        out.append(build_query("assertion", doc, n))
        return out

    def _answer(self, q: Query, fb: FactBase) -> tuple[Conclusion, list[dict]]:
        runs: list[dict] = []
        results: list[Conclusion] = []
        for s in self.strategies:
            rec = {"strategy": s.name, "family": s.family, "applicable": False, "status": None, "ms": 0.0, "query": q.predicate or q.kind}
            try:
                if not s.applies(q):
                    runs.append(rec)
                    continue
                rec["applicable"] = True
                t = time.perf_counter()
                c = s.run(q, fb)
                rec["ms"] = round((time.perf_counter() - t) * 1000, 3)
                rec["status"] = c.status
                results.append(c)
            except Exception as e:  # a faulty strategy must never take the turn down
                rec.update(applicable=True, status="error", error=f"{type(e).__name__}: {e}")
                self.metrics.errors += 1
                self.metrics.last_error = rec["error"]
            runs.append(rec)
        results = [c for c in results if c.status != "unsupported"] or results
        if not results:
            return Conclusion(status="unsupported", strategy="none", steps=["No reasoning strategy applies to this kind of statement or question."],
                              notes=["This is outside what AVOENIX v0.0.0 can reason about."], query=q.summary()), runs
        if q.kind == "assertion":
            bad = [c for c in results if c.status == "contradiction"]
            chosen = bad[0] if bad else results[0]
            chosen.query = q.summary()
            return chosen, runs
        for pool in (DECISIVE, ("likely",), ("underdetermined",), ("unknown",)):
            pick = next((c for c in results if c.status in pool), None)
            if pick:
                break
        else:
            pick = results[0]
        if pick.status == "underdetermined":
            extra = next((c for c in results if c is not pick and c.alternatives and c.strategy != pick.strategy), None)
            if extra:
                pick.alternatives = extra.alternatives
                pick.steps += extra.steps
                pick.notes.append(f"hypotheses scored by {extra.strategy}")
        pick.notes += [n for n in q.notes if n not in pick.notes]
        pick.query = q.summary()
        return pick, runs

    @staticmethod
    def _dedupe_assertions(cs: list[Conclusion]) -> list[Conclusion]:
        out, seen = [], set()
        for c in cs:
            key = (c.status, c.strategy, tuple(c.steps[:1]))
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        if any(c.status == "contradiction" for c in out):
            return [c for c in out if c.status == "contradiction"]
        return out[:1]
