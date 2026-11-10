"""Evaluation & Confidence Engine.

Two jobs, both based on real measurements:

1. ``assess_turn``: combines the evidence-support scores of the stages that actually ran (interpretation, reasoning, knowledge
   reliability) into one overall support score and a band. Stages that did not run contribute nothing and are listed as
   ``not_evaluated`` — they are never filled with defaults. The score is *support for the answer*, not a calibrated probability.
2. ``run_suite``: executes a labelled dataset through any ``respond(case) -> turn dict`` callable, checks each expectation,
   and reports accuracy per metric / category / split, the failures with reasons, and a calibration table comparing stated
   confidence with measured correctness. Targets (development goals) are reported next to results but never change them.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ...algorithms.confidence import weighted_geometric
from ...core.contracts import EmotionSignal, LanguageResult, ReasoningResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...storage.backend import Backend
from ...version import PLATFORM_VERSION

TARGETS = {"intent_accuracy": 0.85, "memory_retrieval": 0.90, "deterministic_reasoning": 0.90}      # development goals, not achievements
BANDS = ((0.8, "high"), (0.55, "medium"), (0.0, "low"))


def band_of(x: float | None) -> str:
    if x is None:
        return "not_evaluated"
    return next(name for lim, name in BANDS if x >= lim)


@dataclass
class CaseResult:
    id: str
    category: str
    split: str
    passed: bool
    checks: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    confidence: float | None = None
    latency_ms: float | None = None
    metric_tags: list[str] = field(default_factory=list)
    error: str | None = None
    response: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class EvaluationEngine(Engine):
    info = EngineInfo(
        key="evaluation", name="Evaluation & Confidence Engine", status=EngineStatus.PARTIAL,
        summary="Per-turn evidence-support assessment and a dataset runner with per-category metrics, failure reports and a calibration table.",
        depends_on=("language", "reasoning"),
        capabilities=("turn assessment with explicit not_evaluated stages", "weighted-geometric combination of stage scores",
                      "dataset execution with expectation checks (status, task, text, memory)", "accuracy per metric, category and split (dev / hold-out)",
                      "expected-calibration-error style table of stated confidence vs correctness", "persistence of runs (evaluation_runs)"),
        limitations=("Measures only what the supplied dataset covers; a high score on a small dataset is not a general claim.",
                     "Confidence bands are fixed thresholds, not calibrated; the calibration table reports how far off they are.",
                     "The bundled dataset is small and authored by the AVOENIX developers (not independent)."),
    )

    def self_check(self) -> tuple[bool, str]:
        r = self.assess_turn(None, None, None, answered=False)
        ok = isinstance(r, dict) and "band" in r
        return ok, "assess_turn probe (no evidence yields an explicit not-evaluated band)" if ok else "assess_turn probe failed"

    def __init__(self, backend: Backend | None = None):
        super().__init__()
        self.backend = backend

    # ---- per-turn assessment -------------------------------------------------------------------------------------------------
    @traced("assess_turn")
    def assess_turn(self, language: LanguageResult | None, reasoning: ReasoningResult | None, emotion: EmotionSignal | None = None, *, answered: bool = True) -> dict:
        comps: dict[str, float] = {}
        not_evaluated: list[str] = []
        factors: list[str] = []
        if language is not None:
            comps["interpretation"] = round(language.interpretation_confidence, 3)
            if language.interpretation_confidence < 0.6:
                factors.append("the sentence was only partly understood")
            if language.corrections:
                factors.append(f"{len(language.corrections)} spelling/typing repair(s) were applied")
        else:
            not_evaluated.append("interpretation")
        pc = reasoning.primary if reasoning else None
        if pc is not None and pc.confidence is not None and pc.status in ("answered", "yes", "no", "likely", "consistent"):
            comps["reasoning"] = round(pc.confidence, 3)
            if pc.assumptions:
                factors.append("the answer relies on user-stated premises")
        elif pc is not None and pc.status in ("unknown", "underdetermined", "unsupported", "contradiction", "undefined"):
            not_evaluated.append("reasoning (no answer was established)")
        else:
            not_evaluated.append("reasoning")
        if emotion is not None and emotion.certainty > 0:
            comps["affect_reading"] = round(emotion.certainty, 3)
        used = {k: max(v, 1e-6) for k, v in comps.items() if k != "affect_reading"}
        overall = round(weighted_geometric(used, {k: (2.0 if k == "reasoning" else 1.0) for k in used}), 3) if used else None
        if pc is not None and pc.status in ("unknown", "underdetermined", "unsupported", "contradiction"):
            band, headline = "not_evaluated", f"no answer established ({pc.status})"
        else:
            band, headline = band_of(overall), f"{band_of(overall)} support"
        return {"overall": overall, "band": band, "headline": headline, "components": comps, "not_evaluated": not_evaluated, "factors": factors,
                "note": "evidence-support score, not a probability of being correct"}

    # ---- dataset execution ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def check(expect: dict, turn: dict) -> tuple[list[dict], list[str]]:
        checks, failures = [], []

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "ok": ok, "detail": detail})
            if not ok:
                failures.append(f"{name}: {detail}")

        text = (turn.get("response") or "")
        und = turn.get("understanding") or {}
        status = (turn.get("reasoning_status"))
        if "task" in expect:
            add("task", und.get("task") == expect["task"], f"expected {expect['task']!r}, got {und.get('task')!r}")
        if "status" in expect:
            allowed = expect["status"] if isinstance(expect["status"], list) else [expect["status"]]
            add("status", status in allowed, f"expected {allowed}, got {status!r}")
        for s in expect.get("contains", []):
            add("contains", re.search(s, text, re.I) is not None, f"/{s}/ not in response: {text[:160]!r}")
        for s in expect.get("not_contains", []):
            add("not_contains", re.search(s, text, re.I) is None, f"/{s}/ unexpectedly present: {text[:160]!r}")
        if "any_of" in expect:
            add("any_of", any(re.search(s, text, re.I) for s in expect["any_of"]), f"none of {expect['any_of']} in: {text[:160]!r}")
        if "answer" in expect:
            ans = turn.get("answer")
            add("answer", str(ans).lower() == str(expect["answer"]).lower(), f"expected {expect['answer']!r}, got {ans!r}")
        if "emoji" in expect:
            add("emoji", bool(turn.get("emoji")) == bool(expect["emoji"]), f"expected emoji={expect['emoji']}, got {turn.get('emoji')}")
        if "max_confidence" in expect:
            c = turn.get("confidence")
            add("max_confidence", c is None or c <= expect["max_confidence"], f"confidence {c} above {expect['max_confidence']}")
        return checks, failures

    @traced("run_suite")
    def run_suite(self, cases: list[dict], respond: Callable[[dict], list[dict]], *, label: str = "adhoc", persist: bool = False, environment: dict | None = None) -> dict:
        """``respond(case)`` must run all turns of a case in a fresh conversation and return the list of turn dicts."""
        started = datetime.now(timezone.utc)
        results: list[CaseResult] = []
        for case in cases:
            t0 = time.perf_counter()
            cr = CaseResult(id=case["id"], category=case.get("category", "uncategorised"), split=case.get("split", "dev"), passed=False,
                            metric_tags=list(case.get("metrics", [])))
            try:
                turns = respond(case)
                expects = case.get("expect")
                expects = expects if isinstance(expects, list) else [expects or {}]
                if len(turns) < len(expects):
                    cr.failures.append(f"only {len(turns)} turn(s) returned for {len(expects)} expectation(s)")
                for i, (exp, turn) in enumerate(zip(expects, turns[-len(expects):] if expects else turns)):
                    ch, fl = self.check(exp, turn)
                    cr.checks += [{**c, "turn": i} for c in ch]
                    cr.failures += [f"turn {i}: {f}" for f in fl]
                last = turns[-1] if turns else {}
                cr.confidence, cr.response = last.get("confidence"), last.get("response")
            except Exception as e:  # a crashing case is a failed case, never a skipped one
                cr.error = f"{type(e).__name__}: {e}"
                cr.failures.append(cr.error)
            cr.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            cr.passed = not cr.failures
            results.append(cr)
        report = self._report(results, label, started, environment or {})
        if persist and self.backend is not None:
            self.backend.insert("evaluation_runs", {"id": "ev_" + uuid.uuid4().hex[:12], "suite": label, "platform_version": PLATFORM_VERSION, "label": label,
                                                    "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
                                                    "summary": report["summary"], "results": {"cases": report["cases"], "calibration": report["calibration"]},
                                                    "environment": report["environment"], "triggered_by": "evaluation-engine"})
        return report

    @staticmethod
    def _rate(rs: list[CaseResult]) -> dict:
        n = len(rs)
        return {"passed": sum(r.passed for r in rs), "total": n, "accuracy": round(sum(r.passed for r in rs) / n, 4) if n else None}

    def _report(self, results: list[CaseResult], label: str, started: datetime, environment: dict) -> dict:
        by_cat: dict[str, list[CaseResult]] = {}
        for r in results:
            by_cat.setdefault(r.category, []).append(r)
        metrics: dict[str, Any] = {}
        for name, tag in (("intent_accuracy", "intent"), ("memory_retrieval", "memory"), ("deterministic_reasoning", "reasoning")):
            rs = [r for r in results if tag in r.metric_tags]
            m = self._rate(rs) if rs else {"passed": 0, "total": 0, "accuracy": None}
            m["target"] = TARGETS[name]
            m["status"] = "not_evaluated" if not rs else ("target_met_on_this_dataset" if m["accuracy"] >= TARGETS[name] else "below_target")
            metrics[name] = m
        splits = {s: self._rate([r for r in results if r.split == s]) for s in sorted({r.split for r in results})}
        calibration = self._calibration([r for r in results if r.confidence is not None])
        lat = sorted(r.latency_ms for r in results if r.latency_ms is not None)
        return {
            "label": label, "platform_version": PLATFORM_VERSION, "started_at": started.isoformat(),
            "summary": {"overall": self._rate(results), "by_category": {c: self._rate(rs) for c, rs in sorted(by_cat.items())}, "by_split": splits, "metrics": metrics,
                        "latency_ms": {"p50": lat[len(lat) // 2] if lat else None, "max": lat[-1] if lat else None}},
            "failures": [{"id": r.id, "category": r.category, "split": r.split, "reasons": r.failures} for r in results if not r.passed],
            "cases": [r.to_dict() for r in results], "calibration": calibration, "environment": environment,
            "caveats": ["Targets are development goals, not claims of achievement.", "Dataset is small and developer-authored; results do not generalise beyond it."],
        }

    @staticmethod
    def _calibration(rs: list[CaseResult]) -> dict:
        if not rs:
            return {"status": "not_evaluated", "reason": "no case returned a confidence value", "bins": []}
        edges = [0.0, 0.5, 0.75, 0.9, 1.0001]
        bins, ece, n = [], 0.0, len(rs)
        for lo, hi in zip(edges, edges[1:]):
            grp = [r for r in rs if lo <= r.confidence < hi]
            if not grp:
                continue
            mean_conf = sum(r.confidence for r in grp) / len(grp)
            acc = sum(r.passed for r in grp) / len(grp)
            ece += len(grp) / n * abs(mean_conf - acc)
            bins.append({"range": f"[{lo:.2f}, {min(hi, 1.0):.2f})", "n": len(grp), "mean_confidence": round(mean_conf, 3), "accuracy": round(acc, 3)})
        return {"status": "measured", "n": n, "expected_calibration_error": round(ece, 4), "bins": bins,
                "note": "Confidence is an evidence-support score; a large error means it should not be read as a probability."}

    def latest_runs(self, limit: int = 10) -> list[dict]:
        if self.backend is None:
            return []
        rows = self.backend.select("evaluation_runs", {})
        rows.sort(key=lambda r: r["started_at"], reverse=True)
        return [{k: r[k] for k in ("id", "suite", "label", "platform_version", "started_at", "finished_at", "summary")} for r in rows[:limit]]
