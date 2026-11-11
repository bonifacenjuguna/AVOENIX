"""Knowledge Integrity (v0.0.1) through full turns: remembering a statement is not believing it. In-memory backend; no network, no ML."""
from __future__ import annotations

import re

import pytest

from intelligence.app import Avoenix, AvoenixConfig
from intelligence.core.types import Scope
from intelligence.storage import MemoryBackend


@pytest.fixture()
def system():
    return Avoenix(MemoryBackend(), AvoenixConfig(deterministic_seed=7))


def talk(a, scope, *texts, cid=None):
    out = []
    for t in texts:
        r = a.process_turn(scope, t, cid)
        cid = r.conversation_id
        out.append(r)
    return out


def test_user_claim_does_not_override_established_capital(system):
    S = Scope("p", "ki1")
    q1, claim, q2 = talk(system, S, "What is the capital of the USA?", "The capital of the USA is New York.", "What is the capital of the USA?")
    assert "Washington" in q1.response
    assert "unverified" in claim.response.lower() and "Washington" in claim.response     # remembered, flagged, corrected
    assert "Washington" in q2.response
    assert not re.search(r"\bNew York is the capital\b|capital of United States is New York\.", q2.response)
    assert "probably" not in q2.response.lower()


def test_original_statement_stays_retrievable_with_provenance(system):
    S = Scope("p", "ki2")
    talk(system, S, "The capital of the USA is New York.")
    cl = system.knowledge.claims(S)
    assert len(cl) == 1
    c = cl[0]
    assert c.provenance == "user_provided" and c.verification in ("contradicted", "conflicting")
    assert c.memory_id                                           # the episodic record of "the user said this" is linked, but is a separate record
    mem = system.memory.get(S, c.memory_id)
    assert "New York" in mem["content"] and mem["category"] == "episodic"


def test_claim_with_no_established_knowledge_is_unverified_not_fact(system):
    S = Scope("p", "ki3")
    r, a = talk(system, S, "The capital of Atlantis is Poseidonis.", "What is the capital of Atlantis?")
    assert "unverified" in r.response.lower()
    assert "established" in a.response.lower() or "couldn't verify" in a.response.lower() or "unverified" in a.response.lower()
    assert a.reasoning["conclusions"][0]["status"] == "unverified_claim"
    assert a.confidence["band"] == "not_evaluated"


def test_two_unverified_conflicting_claims_are_both_preserved(system):
    S = Scope("p", "ki4")
    talk(system, S, "The capital of Atlantis is Poseidonis.", "The capital of Atlantis is Marinus.")
    cl = system.knowledge.claims(S)
    assert len(cl) == 2 and all(c.verification == "conflicting" for c in cl)
    open_ = system.knowledge.conflicts(S, status="open")
    assert len(open_) == 1


def test_nairobi_vs_mombasa(system):
    S = Scope("p", "ki5")
    t = talk(system, S, "What is the capital of Kenya?", "The capital of Kenya is Mombasa.", "What is the capital of Kenya?")
    assert "Nairobi" in t[0].response and "Nairobi" in t[2].response and "Mombasa" in t[2].response
    assert "not treating it as fact" in t[2].response


def test_personal_statements_remain_directly_believed(system):
    S = Scope("p", "ki6")
    talk(system, S, "My name is Savah.")
    r, = talk(system, S, "What is my name?")
    assert "Savah" in r.response


def test_agreeing_claim_is_recognised_as_supported(system):
    S = Scope("p", "ki7")
    r, = talk(system, S, "The capital of the USA is Washington, D.C.")
    assert "matches" in r.response.lower() or "agrees" in r.response.lower()


def test_follow_up_about_entity_surfaces_state(system):
    S = Scope("p", "ki8")
    r = talk(system, S, "The capital of the USA is New York.", "What is the capital of the USA?", "What about Kenya?")
    assert "Washington" in r[1].response and "Nairobi" in r[2].response
    assert len(r[2].reasoning["conclusions"]) == 1           # an elliptical follow-up is answered once
