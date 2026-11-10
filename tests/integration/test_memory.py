from datetime import datetime, timedelta, timezone

import pytest

from intelligence.core.errors import InputError, NotFoundError
from intelligence.core.types import FixedClock, Scope
from intelligence.engines.memory.engine import MemoryEngine
from tests.support.backends import backend_params, build

A, B, C = Scope("p1", "alice"), Scope("p1", "bob"), Scope("p2", "alice")
T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


class Tick(FixedClock):
    def advance(self, **kw):
        self._moment += timedelta(**kw)


@pytest.fixture(scope="module", params=backend_params())
def _backend(request):
    return build(request.param)


@pytest.fixture()
def clock():
    return Tick(T0)


@pytest.fixture()
def me(_backend, clock):
    for r in _backend.select("memories", {"project_id": ("in", ["p1", "p2"])}):
        _backend.delete("memories", {"id": r["id"]})
    return MemoryEngine(_backend, clock)


def test_recall_finds_relevant_and_ranks_by_relevance(me):
    me.remember(A, "semantic", "My sister Grace lives in Mombasa")
    me.remember(A, "semantic", "I work as a nurse at a clinic")
    me.remember(A, "episodic", "We discussed the capital of Kenya")
    hits = me.recall(A, "where does my sister live")
    assert hits and "Grace" in hits[0]["memory"]["content"]
    assert set(hits[0]["parts"]) == {"relevance", "recency", "importance", "reinforcement"}
    assert me.recall(A, "quantum chromodynamics") == []            # nothing relevant -> nothing invented


def test_isolation_between_users_and_projects(me):
    me.remember(A, "semantic", "My favourite colour is green")
    assert me.recall(A, "favourite colour")
    assert not me.recall(B, "favourite colour") and not me.recall(C, "favourite colour")
    assert me.inspect(B)["total_rows"] == 0
    mid = me.recall(A, "favourite colour")[0]["memory"]["id"]
    with pytest.raises(NotFoundError):
        me.get(B, mid)
    with pytest.raises(NotFoundError):
        me.forget(C, mid)
    assert me.recall(A, "favourite colour")                         # still there


def test_preference_keyed_supersession_and_history(me):
    me.set_preference(A, "tone", "formal")
    assert me.get_preference(A, "tone") == "formal"
    r = me.set_preference(A, "tone", "casual")
    assert r["action"] == "superseded" and me.get_preference(A, "tone") == "casual"
    assert me.set_preference(A, "tone", "casual")["action"] == "unchanged"
    assert me.preferences(A) == {"tone": "casual"}
    assert me.get_preference(B, "tone", "none") == "none"
    assert sum(1 for m in me.inspect(A, include_inactive=True)["memories"] if m["status"] == "superseded") == 1


def test_working_memory_expires_and_is_bounded(me, clock):
    for i in range(15):
        me.remember(A, "working", f"scratch item {i}", conversation_id="c1")
    assert len(me.recent(A, category="working", conversation_id="c1", limit=50)) == 12
    clock.advance(hours=3)
    assert me.recent(A, category="working", limit=50) == []
    assert me.prune(A) == 12


def test_recency_and_importance_influence_order(me, clock):
    me.remember(A, "episodic", "Talked about the garden roses", importance=0.2)
    clock.advance(days=60)
    me.remember(A, "episodic", "Talked about the garden tulips", importance=0.9)
    hits = me.recall(A, "garden")
    assert "tulips" in hits[0]["memory"]["content"]


def test_conversational_memory_stays_in_its_conversation(me):
    me.record_turn(A, "c1", "user", "I am planning a trip to Lisbon")
    assert me.recall(A, "trip Lisbon", conversation_id="c1")
    assert not me.recall(A, "trip Lisbon", conversation_id="c2")


def test_update_forget_and_validation(me):
    m = me.remember(A, "semantic", "I own a red bicycle")
    assert me.update(A, m["id"], content="I own a blue bicycle")["content"].endswith("blue bicycle")
    assert me.forget(A, m["id"]) and not me.recall(A, "bicycle")
    with pytest.raises(NotFoundError):
        me.get(A, m["id"])
    with pytest.raises(InputError):
        me.remember(A, "nope", "x")
    with pytest.raises(InputError):
        me.remember(A, "semantic", "   ")
    with pytest.raises(InputError):
        me.remember(A, "semantic", "x", importance=1.5)


def test_forget_matching_reports_what_was_removed(me):
    me.remember(A, "semantic", "My dog is called Biscuit")
    me.remember(A, "semantic", "I like tea")
    ids = me.forget_matching(A, "dog Biscuit")
    assert len(ids) == 1 and me.recall(A, "tea")
