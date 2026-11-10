from intelligence.core.contracts import Conclusion, ReasoningResult
from intelligence.engines.evaluation.engine import EvaluationEngine, band_of
from intelligence.storage import MemoryBackend

E = EvaluationEngine(MemoryBackend())


def test_bands_and_not_evaluated():
    assert band_of(0.9) == "high" and band_of(0.6) == "medium" and band_of(0.2) == "low" and band_of(None) == "not_evaluated"
    rr = ReasoningResult(conclusions=[], strategies_tried=[], elapsed_ms=1, primary=Conclusion(strategy="t", status="unknown"))
    a = E.assess_turn(None, rr)
    assert a["band"] == "not_evaluated" and a["overall"] is None and "interpretation" in a["not_evaluated"]


def test_suite_checks_failures_and_metrics():
    cases = [
        {"id": "a", "category": "x", "metrics": ["reasoning"], "expect": {"status": "answered", "contains": ["David"]}},
        {"id": "b", "category": "x", "metrics": ["reasoning"], "expect": {"status": "answered", "contains": ["Peter"]}},          # will fail
        {"id": "c", "category": "y", "split": "holdout", "metrics": ["intent"], "expect": {"task": "greeting"}},
        {"id": "d", "category": "y", "expect": {"status": "yes"}},                                                                 # crash
    ]

    def respond(case):
        if case["id"] == "d":
            raise RuntimeError("boom")
        return [{"response": "It's David.", "reasoning_status": "answered", "understanding": {"task": "greeting"}, "confidence": 0.9}]

    rep = E.run_suite(cases, respond, label="unit", persist=True)
    assert rep["summary"]["overall"] == {"passed": 2, "total": 4, "accuracy": 0.5}
    assert {f["id"] for f in rep["failures"]} == {"b", "d"}
    assert rep["summary"]["metrics"]["deterministic_reasoning"]["accuracy"] == 0.5
    assert rep["summary"]["metrics"]["deterministic_reasoning"]["status"] == "below_target"
    assert rep["summary"]["metrics"]["memory_retrieval"]["status"] == "not_evaluated"
    assert rep["summary"]["by_split"]["holdout"]["total"] == 1
    assert rep["calibration"]["status"] == "measured" and E.latest_runs()[0]["label"] == "unit"
