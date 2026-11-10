from datetime import datetime, timedelta, timezone

import pytest

from intelligence.core.errors import InputError, NotFoundError
from intelligence.core.types import FixedClock, Scope
from intelligence.engines.memory.engine import MemoryEngine
from intelligence.engines.planning.engine import PlanningEngine, Task, decompose, progress, schedule, topological_order
from intelligence.storage import MemoryBackend

A, B = Scope("p1", "alice"), Scope("p1", "bob")
NOW = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pe():
    return PlanningEngine(MemoryEngine(MemoryBackend(), FixedClock(NOW)))


def test_detect_goal():
    assert PlanningEngine.detect_goal("I want to learn to play the guitar.") == "learn to play the guitar"
    assert PlanningEngine.detect_goal("What is the capital of France?") is None
    assert PlanningEngine.detect_goal("I want to go") is None


def test_decompose_sequential_and_parallel():
    seq = decompose("book flights, then reserve a hotel and then pack")
    assert [s["title"] for s in seq] == ["Book flights", "Reserve a hotel", "Pack"] and [s["depends_on_prev"] for s in seq] == [False, True, True]
    assert all(not s["depends_on_prev"] for s in decompose("buy milk, eggs, bread"))
    assert len(decompose("1. write outline 2. draft 3. edit")) == 3


def test_topological_order_and_cycle():
    t = [Task("a", "a"), Task("b", "b", depends_on=["a"]), Task("c", "c", depends_on=["b"])]
    assert topological_order(t)[0] == ["a", "b", "c"]
    t[0].depends_on = ["c"]
    assert topological_order(t)[1] is not None and not schedule(t)["ok"]


def test_schedule_critical_path_and_slack():
    t = [Task("a", "a", estimate_min=60), Task("b", "b", estimate_min=30, depends_on=["a"]), Task("c", "c", estimate_min=10, depends_on=["a"]),
         Task("d", "d", estimate_min=20, depends_on=["b", "c"])]
    s = schedule(t)
    assert s["makespan_min"] == 110 and s["total_effort_min"] == 120
    assert s["critical_path"] == ["a", "b", "d"] and s["slack"]["c"] == 20


def test_progress_is_effort_weighted():
    t = [Task("a", "a", status="done", estimate_min=30), Task("b", "b", estimate_min=90)]
    assert progress(t) == pytest.approx(0.25)


def test_goal_lifecycle_isolation_and_evaluation(pe):
    g = pe.create_goal(A, "Plan the trip", priority=4, due=(NOW + timedelta(days=2)).isoformat(), decompose_text="book flights, then reserve a hotel, then pack")
    assert len(g.tasks) == 3 and g.tasks[1].depends_on == ["t1"]
    assert [t.id for t in pe.next_actions(A, g.id)] == ["t1"]
    pe.update_task(A, g.id, "t1", status="done", estimate_min=60)
    assert [t.id for t in pe.next_actions(A, g.id)] == ["t2"]
    ev = pe.evaluate(A, g.id)
    assert ev["ok"] and any(f["code"] == "missing_estimates" for f in ev["findings"]) and 0 < ev["progress"] < 1
    assert pe.list_goals(B) == []
    with pytest.raises(NotFoundError):
        pe.get_goal(B, g.id)
    pe.update_task(A, g.id, "t2", status="done"); done = pe.update_task(A, g.id, "t3", status="done")
    assert done.status == "completed"


def test_infeasible_deadline_flagged(pe):
    g = pe.create_goal(A, "Big job", due=(NOW + timedelta(hours=1)).isoformat())
    pe.add_task(A, g.id, "long task", estimate_min=600)
    ev = pe.evaluate(A, g.id)
    assert not ev["ok"] and any(f["code"] == "infeasible" for f in ev["findings"])


def test_validation_and_ranking(pe):
    with pytest.raises(InputError):
        pe.create_goal(A, " ")
    with pytest.raises(InputError):
        pe.create_goal(A, "x", priority=9)
    g = pe.create_goal(A, "Gym", priority=2)
    with pytest.raises(InputError):
        pe.add_task(A, g.id, "t", depends_on=["nope"])
    urgent = pe.create_goal(A, "Taxes", priority=4, due=(NOW + timedelta(hours=6)).isoformat())
    assert pe.rank(A)[0]["goal"] == urgent.id
