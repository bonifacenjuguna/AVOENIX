"""End-to-end turn tests through the orchestrator (in-memory backend; no network, no ML)."""
from __future__ import annotations

import pytest

from intelligence.app import Avoenix, AvoenixConfig
from intelligence.core.types import Scope
from intelligence.storage import MemoryBackend


@pytest.fixture(scope="module")
def system():
    return Avoenix(MemoryBackend(), AvoenixConfig(deterministic_seed=7))


def talk(a, scope, *texts, cid=None):
    out = []
    for t in texts:
        r = a.process_turn(scope, t, cid)
        cid = r.conversation_id
        out.append(r)
    return out


def test_required_reasoning_example(system):
    r, = talk(system, Scope("p", "u_reason"), "John is older than Peter. Peter is older than David. Who is the youngest?")
    assert "David" in r.response and r.status == "ok"
    assert r.understanding["task"] == "question_reasoning"


@pytest.mark.parametrize("text", [
    "Anna is taller than Ben. Ben is taller than Cara. Who is the shortest?",
    "Cara is shorter than Ben, and Ben is shorter than Anna. Who is the tallest person?",
])
def test_varied_wording_ordering(system, text):
    r, = talk(system, Scope("p", "u_vary"), text)
    assert ("Cara" in r.response) if "shortest" in text else ("Anna" in r.response)


def test_followup_ellipsis_uses_context(system):
    rs = talk(system, Scope("p", "u_ctx"), "John is older than Peter. Peter is older than David. Who is the youngest?", "And who is the oldest?")
    assert "John" in rs[1].response


def test_contradiction_detected(system):
    rs = talk(system, Scope("p", "u_con"), "John is older than Peter. Peter is older than David.", "David is older than John.")
    assert "can't all be true" in rs[1].response or "cannot all" in rs[1].response
    assert "older than John" in rs[1].response and "John is older than John" not in rs[1].response


def test_memory_across_conversations(system):
    S = Scope("p", "u_mem")
    talk(system, S, "My name is Alex.")
    r, = talk(system, S, "What is my name?")           # new conversation
    assert "Alex" in r.response


def test_user_isolation(system):
    talk(system, Scope("p", "u_a"), "My name is Alex.")
    r, = talk(system, Scope("p", "u_b"), "What is my name?")
    assert "Alex" not in r.response


def test_project_isolation(system):
    talk(system, Scope("p1", "u_x"), "My name is Zed.")
    r, = talk(system, Scope("p2", "u_x"), "What is my name?")
    assert "Zed" not in r.response


def test_arithmetic_exact(system):
    r, = talk(system, Scope("p", "u_m"), "What is 12 * 7?")
    assert "84" in r.response


def test_unknown_is_not_fabricated(system):
    r, = talk(system, Scope("p", "u_unk"), "What is the capital of Atlantis?")
    assert "on record" in r.response.lower() or "don't know" in r.response.lower()


def test_preference_learning_is_verified_and_persistent(system):
    S = Scope("p", "u_pref")
    r, = talk(system, S, "Please don't use emoji")
    assert r.understanding["task"] == "preference_update"
    assert system.memory.get_preference(S, "style.emoji", None) == "none"


def test_non_english_rejected_honestly(system):
    r, = talk(system, Scope("p", "u_lang"), "¿Cuál es la capital de España y por qué es importante para el país?")
    assert "English" in r.response


def test_unsupported_action_is_declined(system):
    r, = talk(system, Scope("p", "u_act"), "Tell me a joke")
    assert r.understanding["task"] == "request_action"


def test_greetings_vary_per_user(system):
    seen = set()
    for i in range(6):
        r, = talk(system, Scope("p", f"u_g{i}"), "Hi there")
        seen.add(r.response)
    assert len(seen) >= 2


def test_empty_input_safe_error(system):
    r = system.process_turn(Scope("p", "u_e"), "   ", None)
    assert r.status != "ok" or r.response
    assert "Traceback" not in r.response
