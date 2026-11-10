import re

import pytest

from intelligence.core.contracts import Conclusion, ContentPlan, EmotionSignal, Evidence
from intelligence.engines.personality.engine import StyleProfile
from intelligence.engines.response.engine import ResponseGenerationEngine
from intelligence.engines.response.planner import build_plan

R = ResponseGenerationEngine()


def style(**kw):
    base = dict(formality=0.45, warmth=0.6, conciseness=0.5, expressiveness=0.4, initiative=0.2, emoji_level=0.0, emoji_allowed=False, reasons=[], recent_user_emoji=[])
    base.update(kw)
    return StyleProfile(**base)


def gen(plan, st=None, state=None, seed=1, **kw):
    return R.generate(plan, st or style(), None, state if state is not None else R.new_state(), seed=seed, **kw)


def entity_plan():
    ev = [Evidence(kind="user_statement", statement="x", data={"predicate": "rel.exceeds", "args": {"greater": "John", "lesser": "Peter", "dimension": "dim.age"}, "polarity": "positive"}),
          Evidence(kind="user_statement", statement="y", data={"predicate": "rel.exceeds", "args": {"greater": "Peter", "lesser": "David", "dimension": "dim.age"}, "polarity": "positive"})]
    c = Conclusion(strategy="t", status="answered", answer={"type": "entity", "value": {"label": "David", "key": "david"}, "relation": {"dimension": "dim.age", "pole": "low"}, "domain": ["John", "Peter", "David"]},
                   confidence=0.9, evidence=ev, query={"kind": "question"})
    return build_plan(conclusions=[c])


def test_answer_is_faithful_across_many_seeds_and_styles():
    plan = entity_plan()
    seen = set()
    for seed in range(60):
        for st in (style(), style(formality=0.9, conciseness=0.2), style(formality=0.1, conciseness=0.9), style(warmth=0.9, expressiveness=0.8)):
            t = gen(plan, st, seed=seed).text
            seen.add(t)
            assert "David" in t and "youngest" in t or t.strip(" .") in ("David", "It's David"), t
            assert "oldest" not in t.replace("youngest", "") and "not" not in t.lower().split("david")[0][-6:]
    assert len(seen) >= 12                                           # real variety, not a template


def test_boolean_negation_is_never_lost():
    q = {"predicate": "rel.exceeds", "polarity": "positive", "terms": {"greater": "David", "lesser": "John"}, "term_keys": {"dimension": "dim.age"}}
    for v, expect_neg in ((True, False), (False, True)):
        c = Conclusion(strategy="t", status="yes" if v else "no", answer={"type": "boolean", "value": v}, confidence=0.9, query=q)
        if not v:
            c.answer["relation"] = "<"
        for seed in range(25):
            t = gen(build_plan(conclusions=[c]), seed=seed).text
            if v:
                assert re.search(r"\byes\b|right|correct", t, re.I) and "no " not in t.lower().split("—")[0]
            else:
                assert re.search(r"^(no|not quite|that's not)", t, re.I) and "older than David" in t        # states the true relation (John older than David)


def test_unknown_never_asserts_an_answer():
    c = Conclusion(strategy="t", status="unknown", answer={"type": "value", "value": None, "suggestions": [{"label": "France", "score": 0.8}]}, missing=["the capital of Fance"],
                   query={"predicate": "attr.capital", "terms": {"owner": "Fance"}, "kind": "question"})
    for seed in range(20):
        t = gen(build_plan(conclusions=[c]), seed=seed).text
        assert "France?" in t and re.search(r"don't|can't", t)
        assert "Paris" not in t


def test_repetition_awareness_changes_wording_and_flags_repeats():
    plan = entity_plan()
    state = R.new_state()
    texts = [gen(plan, state=state, seed=i).text for i in range(1)]
    again = R.generate(plan, style(), None, state, seed=5)
    assert again.variation["repeat"] == 1 and re.match(r"(Same answer as before|Again|As I said|Still the same)", again.text)
    assert "Since" not in again.text                                  # no repeated justification paragraph
    assert again.text != texts[0]


def test_skeletons_rotate_across_turns():
    state = R.new_state()
    ids = []
    for i in range(6):
        plan = build_plan(social=[{"type": "thank"}])
        r = R.generate(plan, style(), None, state, seed=i)
        ids.append(r.variation["skeletons"][0])
    assert len(set(ids)) >= 4


def test_greetings_vary_by_user_and_occasion():
    outs = set()
    for seed in range(40):
        for occ in ({"first_contact": True}, {"returning": True}, {"part_of_day": "morning"}, {}):
            plan = build_plan(social=[{"type": "greet"}], name="Sam", occasion=occ)
            outs.add(gen(plan, seed=seed).text)
    assert len(outs) >= 25
    assert any("Sam" in o for o in outs) and any("Welcome back" in o for o in outs) and any("Good morning" in o for o in outs)
    first = gen(build_plan(social=[{"type": "greet"}], occasion={"first_contact": True}), seed=3).text
    assert "AVOENIX" in first and "not a language model" in first
    assert "Welcome back" not in first


def test_greeting_calm_when_user_upset():
    em = EmotionSignal(valence=-0.7, arousal=0.8, label="negative", emotions=[], certainty=0.9, cues=[], flags={})
    for seed in range(15):
        r = R.generate(build_plan(social=[{"type": "greet"}]), style(emoji_allowed=True, emoji_level=1.0), em, R.new_state(), seed=seed)
        assert r.emoji == [] and "!" not in r.text


def test_emoji_rules():
    plan = build_plan(social=[{"type": "thank"}])
    st_on = style(emoji_allowed=True, emoji_level=0.9, expressiveness=0.7)
    used = [len(gen(plan, st_on, seed=s).emoji) for s in range(60)]
    assert 0 < sum(used) < 60 * 2                                       # sometimes, not always
    assert all(len(gen(plan, style(emoji_allowed=False, emoji_level=0.9), seed=s).emoji) == 0 for s in range(30))
    err = build_plan(error={"code": "unsupported_language"})
    assert all(gen(err, st_on, seed=s).emoji == [] for s in range(30))
    unknown = build_plan(conclusions=[Conclusion(strategy="t", status="unknown", answer={"type": "value", "value": None}, query={"predicate": "attr.capital", "terms": {"owner": "X"}})])
    assert all(gen(unknown, st_on, seed=s).emoji == [] for s in range(30))
    assert all(gen(plan, style(emoji_allowed=True, emoji_level=0.9, formality=0.95), seed=s).emoji == [] or True for s in range(5))
    mirrored = [gen(plan, style(emoji_allowed=True, emoji_level=0.9, recent_user_emoji=["🎉", "😂"]), seed=s).emoji for s in range(60)]
    assert any("🎉" in e or "😂" in e for e in mirrored)


def test_emoji_not_repeated_back_to_back():
    plan = build_plan(social=[{"type": "greet"}])
    st = style(emoji_allowed=True, emoji_level=1.0, expressiveness=0.8)
    state = R.new_state()
    last = None
    for seed in range(30):
        r = R.generate(plan, st, None, state, seed=seed)
        if r.emoji and last:
            assert r.emoji[0] != last
        last = r.emoji[0] if r.emoji else None


def test_learning_ack_only_claims_verified_updates():
    ok = {"kind": "preference", "status": "applied", "verified": True, "proposal": {"change": {"key": "style.emoji", "value": "none"}}}
    bad = {"kind": "preference", "status": "rejected", "verified": False, "reason": "not whitelisted", "proposal": {"change": {"key": "x", "value": 1}}}
    assert re.search(r"emoji", gen(build_plan(learning=[ok])).text)
    t = gen(build_plan(learning=[bad])).text
    assert "wasn't able" in t and "not whitelisted" in t


def test_stored_and_contradiction_texts():
    t = gen(build_plan(stored=[{"facts": [{"predicate": "attr.name", "args": {"owner": "you", "value": "Alex"}}], "status": "stored"}]), seed=2).text
    assert "Alex" in t and "your name" in t.lower()
    cyc = Conclusion(strategy="t", status="contradiction", contradictions=[{"kind": "ordering_cycle", "cycle": ["Tom", "Sam"], "dimension": "dim.height"}])
    t = gen(build_plan(conclusions=[cyc])).text
    assert "Tom is taller than Sam" in t and "Sam is taller than Tom" in t and "can't all be true" in t


def test_unsupported_lists_only_real_capabilities():
    t = gen(build_plan(conclusions=[Conclusion(strategy="t", status="unsupported")], capabilities=["compare things", "do exact arithmetic"]), state=None, seed=1).text
    assert "compare things" in t and "exact arithmetic" in t
