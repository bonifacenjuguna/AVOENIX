import pytest

from intelligence.core.errors import LearningRejected, NotFoundError, ScopeError
from intelligence.core.types import Scope
from intelligence.engines.knowledge.engine import KnowledgeEngine
from intelligence.engines.language.engine import LanguageEngine
from intelligence.engines.learning.engine import LearningEngine
from intelligence.engines.memory.engine import MemoryEngine
from tests.support.backends import backend_params, build

A, B, ADMIN = Scope("p1", "alice"), Scope("p1", "bob"), Scope("p1", "admin")


@pytest.fixture(scope="module", params=backend_params())
def _stack(request):
    b = build(request.param)
    ke = KnowledgeEngine(b)
    ke.seed()
    return b, ke


@pytest.fixture()
def le(_stack):
    b, ke = _stack
    for t in ("learning_records", "feedback", "memories", "knowledge_terms"):
        for r in b.select(t, {"project_id": ("in", ["p1"])}):
            if t == "knowledge_terms":
                b.delete(t, {"fact_id": r["fact_id"]})
            else:
                b.delete(t, {"id": r["id"]})
    for r in b.select("knowledge_facts", {"project_id": "p1"}):
        b.delete("knowledge_terms", {"fact_id": r["id"]})
        b.delete("knowledge_facts", {"id": r["id"]})
    return LearningEngine(b, ke, MemoryEngine(b), language=LanguageEngine())


def test_classification_covers_four_classes(le):
    assert le.classify("Please don't use emoji")["change"] == {"key": "style.emoji", "value": "none"}
    assert le.classify("keep it short")["kind"] == "preference"
    assert le.classify("Call me Sam")["change"]["value"] == "Sam"
    assert le.classify("show your steps")["kind"] == "strategy_adjustment"
    assert le.classify("No, the capital of Kenya is Nairobi")["kind"] == "fact_correction"
    assert le.classify("Remember that Zed is a wizard")["kind"] == "general_knowledge"
    assert le.classify("What is the capital of France?") is None


def test_preference_applied_verified_and_reversible(le):
    r = le.learn_from_message(A, "Please don't use emoji")
    assert r["status"] == "applied" and r["verified"] and r["evaluation"]["regressions"] == []
    assert le.memory.get_preference(A, "style.emoji") == "none"
    assert le.memory.get_preference(B, "style.emoji") is None                   # per-user
    le.learn_from_message(A, "Use more emoji please")
    assert le.memory.get_preference(A, "style.emoji") == "more"
    rec = le.revert(A, r["id"], decided_by="alice")
    assert rec["status"] == "reverted"
    h = [x["status"] for x in le.history(A)]
    assert "reverted" in h and "applied" in h


def test_revert_of_superseding_change_restores_previous_value(le):
    first = le.learn_from_message(A, "be more formal")
    second = le.learn_from_message(A, "be more casual")
    assert le.memory.get_preference(A, "style.formality") == "casual"
    le.revert(A, second["id"], decided_by="alice")
    assert le.memory.get_preference(A, "style.formality") == "formal"


def test_repeating_a_preference_does_not_destroy_it_on_revert(le):
    r1 = le.learn_from_message(A, "keep it short")
    r2 = le.learn_from_message(A, "keep it short")
    le.revert(A, r2["id"], decided_by="alice")
    assert le.memory.get_preference(A, "style.length") == "short"


def test_strategy_switch(le):
    r = le.learn_from_message(A, "Please show your steps")
    assert r["status"] == "applied" and le.memory.get_preference(A, "behavior.show_steps") is True


def test_invalid_name_rejected(le):
    r = le.learn_from_message(A, "call me X1")
    assert r is None or r["status"] == "rejected"


def test_user_fact_correction_applied_and_isolated(le):
    r = le.learn_from_message(A, "Actually, Zed is a wizard.")
    assert r["status"] == "applied" and r["verified"]
    assert le.knowledge.query(A, "rel.is_a", {"subject": "zed"}, include_self=False)
    assert not le.knowledge.query(B, "rel.is_a", {"subject": "zed"}, include_self=False)
    assert le.revert(A, r["id"], decided_by="alice")["status"] == "reverted"
    assert not le.knowledge.query(A, "rel.is_a", {"subject": "zed"}, include_self=False)


def test_correction_conflicting_with_curated_knowledge_is_rejected_not_applied(le):
    r = le.learn_from_message(A, "No, the capital of France is Lyon.")
    assert r["status"] == "rejected" and not r["verified"] and "disputed" in (r["reason"] or "")
    assert le.knowledge.query(A, "attr.capital", {"owner": "france"}, include_self=False)[0].args["value"]["label"] == "Paris"
    assert not le.knowledge.query(A, "attr.capital", {"owner": "france"}, statuses=("disputed", "active"), include_self=False)[0].args["value"]["label"] == "Lyon"
    assert all(f.status != "active" or f.args["value"]["label"] == "Paris" for f in le.knowledge.query(A, "attr.capital", {"owner": "france"}, include_self=False))


def test_regression_check_blocks_harmful_change(le):
    """A golden probe that a change breaks must lead to automatic undo."""
    le.golden = le.golden + [{"name": "no_lyon_claims", "predicate": "rel.is_a", "args": {"subject": "zed"}, "expect_present": False}]
    r = le.learn_from_message(A, "Actually, Zed is a wizard.")
    assert r["status"] == "rejected" and "regression" in r["reason"] and r["evaluation"]["regressions"]
    assert not le.knowledge.query(A, "rel.is_a", {"subject": "zed"}, include_self=False)


def test_general_knowledge_needs_admin(le):
    r = le.learn_from_message(A, "Remember that Zed is a wizard.")
    assert r["status"] == "proposed" and not r["verified"]
    assert not le.knowledge.query(B, "rel.is_a", {"subject": "zed"}, include_self=False)
    with pytest.raises(ScopeError):
        le.apply(A, r["id"], decided_by="alice")
    done = le.approve(ADMIN, r["id"], admin_id="admin")
    assert done["status"] == "applied"
    assert le.knowledge.query(B, "rel.is_a", {"subject": "zed"}, include_self=False)             # now visible project-wide
    assert le.knowledge.query(B, "rel.is_a", {"subject": "zed"}, include_self=False)[0].source_type == "learned"


def test_records_are_user_scoped(le):
    r = le.learn_from_message(A, "keep it short")
    with pytest.raises(NotFoundError):
        le.revert(B, r["id"], decided_by="bob")
    assert le.history(B) == []


def test_feedback_validation(le):
    fb = le.submit_feedback(A, "rating", rating=-1, comment="wrong answer", message_id="m1")
    assert fb["status"] == "recorded"
    with pytest.raises(Exception):
        le.submit_feedback(A, "rating", rating=5)
    assert le.learn_from_message(A, "What is 2 plus 2?") is None
