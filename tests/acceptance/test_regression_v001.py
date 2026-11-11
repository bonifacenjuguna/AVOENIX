"""v0.0.1 regression guard: behaviours that worked in v0.0.0 must still work after the Knowledge Integrity change."""
from intelligence.app import Avoenix, AvoenixConfig
from intelligence.core.types import Scope
from intelligence.storage import MemoryBackend


def mk(backend=None):
    return Avoenix(backend or MemoryBackend(), AvoenixConfig(deterministic_seed=7))


def say(a, S, *ts):
    cid, out = None, []
    for t in ts:
        r = a.process_turn(S, t, cid); cid = r.conversation_id; out.append(r.response)
    return out


def test_age_ordering_still_reasoned():
    r = say(mk(), Scope("p", "r1"), "John is older than Peter. Peter is older than David. Who is the youngest?")
    assert "David" in r[0]


def test_name_recall():
    r = say(mk(), Scope("p", "r2"), "My name is Savah.", "What is my name?")
    assert "Savah" in r[1]


def test_nairobi_capital_answer():
    assert "Nairobi" in say(mk(), Scope("p", "r3"), "What is the capital of Kenya?")[0]


def test_contextual_followup():
    r = say(mk(), Scope("p", "r4"), "What is the capital of Kenya?", "What about France?")
    assert "Paris" in r[1]


def test_persistence_across_restart_for_personal_facts_and_claims():
    b, S = MemoryBackend(), Scope("p", "r5")
    say(mk(b), S, "My name is Savah.", "The capital of Atlantis is Poseidonis.")
    again = mk(b)                                         # a new orchestrator over the same store, as after a process restart
    assert "Savah" in say(again, S, "What is my name?")[0]
    assert [c.object["label"] for c in again.knowledge.claims(S) if c.claim_type == "world"] == ["Poseidonis"]
    assert "couldn't verify" in say(again, S, "What is the capital of Atlantis?")[0].lower()


def test_ordering_premise_contradiction_still_detected():
    r = say(mk(), Scope("p", "r6"), "John is older than Peter. Peter is older than John.")
    assert "doesn't add up" in r[0].lower() and "can't all be true" in r[0].lower()
