import pytest

from intelligence.core.types import Scope
from intelligence.engines.input.engine import InputProcessingEngine
from intelligence.engines.knowledge.engine import KnowledgeEngine
from intelligence.engines.language.engine import LanguageEngine
from intelligence.engines.reasoning.engine import ReasoningEngine
from intelligence.storage import MemoryBackend

S = Scope("p1", "alice")
_ie, _le = InputProcessingEngine(), LanguageEngine()


@pytest.fixture()
def env():
    ke = KnowledgeEngine(MemoryBackend())
    ke.seed()
    return ke, ReasoningEngine(ke)


def ask(env, text, cid="c1", store=False):
    ke, re_ = env
    lr = _le.analyze(_ie.process(text))
    res = re_.reason(S, lr, conversation_id=cid)
    if store:
        for rid in lr.doc.roots:
            n = lr.doc.nodes[rid]
            if n.KIND == "intention" and n.act == "assert":
                for pid in n.content:
                    ke.assert_proposition(S, lr.doc, pid, conversation_id=cid)
    return res


def label(res):
    return res.primary.answer["value"]["label"]


@pytest.mark.parametrize("text,expected", [
    ("John is older than Peter. Peter is older than David. Who is the youngest?", "David"),
    ("John is older than Peter. Peter is older than David. Who is the oldest?", "John"),
    ("Peter is younger than John. David is younger than Peter. Who is the oldest?", "John"),
    ("David is younger than Peter and Peter is younger than John. Who is the youngest?", "David"),
    ("Anna is taller than Ben and Ben is taller than Carl. Who is the shortest?", "Carl"),
    ("Carl is shorter than Ben. Ben is shorter than Anna. Who is the tallest?", "Anna"),
    ("Among Ann, Bob and Cy, Ann is the tallest and Cy is shorter than Bob. Who is the shortest?", "Cy"),
    ("John is 30 years old. Peter is 25 years old. David is 20 years old. Who is the youngest?", "David"),
    ("Mia is faster than Noah. Noah is faster than Omar. Who is the slowest?", "Omar"),
])
def test_superlatives_varied_wording(env, text, expected):
    res = ask(env, text)
    assert res.primary.status == "answered" and label(res) == expected
    assert res.primary.steps and res.primary.evidence and 0 < res.primary.confidence <= 1
    assert any("CSP cross-check" in s for s in res.primary.steps)


def test_four_entities_transitive_chain_and_equality(env):
    res = ask(env, "A is older than B. B is as old as C. C is older than D. Who is the youngest?")
    assert label(res) == "D"


def test_yes_no_transitivity_and_negative_answers(env):
    t = "John is older than Peter. Peter is older than David. "
    assert ask(env, t + "Is John older than David?").primary.status == "yes"
    r = ask(env, t + "Is David older than John?")
    assert r.primary.status == "no"
    assert ask(env, t + "Is Peter the youngest?").primary.status == "no"
    assert ask(env, t + "Is David the youngest?").primary.status == "yes"
    assert ask(env, t + "Who is older than David?").primary.answer["value"][0]["label"] in ("John", "Peter")
    assert len(ask(env, t + "Who is older than David?").primary.answer["value"]) == 2


def test_underdetermined_reports_missing_and_scores_hypotheses(env):
    res = ask(env, "John is older than Peter. John is older than David. Who is the youngest?")
    c = res.primary
    assert c.status == "underdetermined" and c.missing
    assert {a["label"] for a in c.alternatives} == {"Peter", "David"}
    assert all(0 < a["consistent_orderings_share"] < 1 for a in c.alternatives)


def test_unconnected_entities_are_unknown_not_guessed(env):
    res = ask(env, "John is older than Peter. Is Maria older than Peter?")
    assert res.primary.status == "unknown" and res.primary.missing
    assert ask(env, "Who is the youngest?").primary.status == "unknown"


def test_contradiction_detected_in_premises(env):
    res = ask(env, "Tom is taller than Sam. Sam is taller than Tom. Who is the tallest?")
    assert any(c.status == "contradiction" for c in res.conclusions)
    q = res.primary
    assert any("contradict" in n for n in q.notes)


def test_negated_comparison_is_used(env):
    r = ask(env, "Tom is not taller than Sam. Is Sam taller than Tom?")
    assert r.primary.status in ("unknown", "yes")           # 'not taller' means <=, so it cannot be refuted or confirmed strictly
    r = ask(env, "Tom is taller than Sam. Sam is not taller than Tom. Is Tom taller than Sam?")
    assert r.primary.status == "yes"


def test_contradiction_across_turns_via_store(env):
    ask(env, "John is older than Peter.", store=True)
    ask(env, "Peter is older than David.", store=True)
    r = ask(env, "David is older than John.")
    assert any(c.status == "contradiction" for c in r.conclusions)
    r2 = ask(env, "Who is the youngest?")
    assert label(r2) == "David"


def test_conversation_isolation_of_stated_orderings(env):
    ask(env, "John is older than Peter.", cid="c1", store=True)
    assert ask(env, "Who is the oldest?", cid="c2").primary.status == "unknown"


@pytest.mark.parametrize("text,expected", [("What is 12 times 7?", "84"), ("What is 15% of 80?", "12"), ("What is 7 plus 8 minus 3?", "12")])
def test_arithmetic(env, text, expected):
    c = ask(env, text).primary
    assert c.status == "answered" and c.answer["value"] == expected and c.strategy == "exact_arithmetic"


def test_division_by_zero_is_undefined(env):
    assert ask(env, "What is 10 divided by 0?").primary.status == "undefined"


def test_exact_fractions_no_float_error(env):
    c = ask(env, "What is 1 divided by 3?").primary
    assert c.answer["exact"] == "1/3"


def test_taxonomy_transitive_negative_and_unknown(env):
    assert ask(env, "Is a dog a mammal?").primary.status == "yes"
    r = ask(env, "Is a dog an animal?").primary
    assert r.status == "yes" and len(r.steps[0].split("→")) == 3
    assert ask(env, "Is the whale a fish?").primary.status == "no"
    assert ask(env, "Is a dog a spaceship?").primary.status == "unknown"


def test_syllogism_with_user_premises(env):
    c = ask(env, "Socrates is a man. All men are mortal. Is Socrates mortal?").primary
    assert c.status == "yes" and c.assumptions
    assert ask(env, "Is Socrates mortal?").primary.status == "unknown"        # nothing stated in this conversation


def test_attribute_lookup_unknown_and_suggestion(env):
    c = ask(env, "What is the capital of France?").primary
    assert c.status == "answered" and c.answer["value"]["label"] == "Paris" and c.evidence[0].source == "seed_curated"
    assert ask(env, "Is the capital of Kenya Nairobi?").primary.status == "yes"
    assert ask(env, "Is the capital of Kenya Mombasa?").primary.status == "no"
    u = ask(env, "What is the capital of Atlantis?").primary
    assert u.status == "unknown" and u.answer["value"] is None


def test_location_chain(env):
    c = ask(env, "Is Paris in Europe?").primary
    assert c.status == "yes" and "→" in c.steps[0]
    assert ask(env, "Is Paris in Africa?").primary.status == "unknown"


def test_user_attribute_roundtrip_and_conflict(env):
    ask(env, "My name is Alex.", store=True)
    c = ask(env, "What is my name?").primary
    assert c.status == "answered" and c.answer["value"]["label"] == "Alex"
    r = ask(env, "My name is Sam.")
    assert any(cc.status == "contradiction" for cc in r.conclusions)


def test_unsupported_is_reported_not_guessed(env):
    r = ask(env, "Do birds fly?")
    assert r.primary.status in ("unsupported", "unknown")


def test_faulty_strategy_does_not_crash_turn(env):
    from intelligence.engines.reasoning.strategies import Strategy

    class Boom(Strategy):
        name, family = "boom", "test"
        def applies(self, q): return True
        def run(self, q, fb): raise RuntimeError("kaput")

    ke, re_ = env
    re_.register(Boom(), first=True)
    r = ask(env, "What is 2 plus 2?")
    assert r.primary.answer["value"] == "4"
    assert any(t.get("error") for t in r.strategies_tried) and re_.metrics.errors >= 1
    assert re_.unregister("boom")


def test_strategy_catalogue_documents_boundaries(env):
    for d in env[1].describe_strategies():
        assert d["handles"] and d["boundaries"]


@pytest.mark.parametrize("text,expected", [
    ("John is older than Peter. Who is older, John or Peter?", "John"),
    ("John is older than Peter. Peter is older than David. Who is younger, John or David?", "David"),
    ("Ann is taller than Bob. Who is taller, Bob or Ann?", "Ann"),
])
def test_choice_questions(env, text, expected):
    r = ask(env, text)
    assert r.primary.status == "answered" and label(r) == expected


def test_choice_with_unknown_candidate(env):
    assert ask(env, "John is older than Peter. Who is older, John or Maria?").primary.status == "unknown"
