"""Meaning layer unit tests: chunker, frames (paraphrase generalisation), dialogue state, reasoning, realiser, distributional semantics."""
import os
import random

import pytest

from intelligence.engines.input.engine import InputProcessingEngine
from intelligence.engines.language.engine import LanguageEngine
from intelligence.meaning.chunker import Chunker, words_to_number
from intelligence.meaning.dialogue import DialogueState
from intelligence.meaning.frames import FrameMatcher
from intelligence.meaning.lexicon import ConceptGraph, default_graph
from intelligence.meaning.planning import plan_from_clause
from intelligence.meaning.realize import ActRealizer, NgramLM, clause, default_lm, inflect, plural
from intelligence.meaning.reason import Deduction, WordProblem, solve_abstract_order
from intelligence.semantics import CoocBuilder, VectorStore, build_vectors, typed_relation

INP, LANG, CH, FM = InputProcessingEngine(max_chars=4000), LanguageEngine(), Chunker(), FrameMatcher()


def clauses(t):
    return CH.parse(LANG.analyze(INP.process(t)).tokens, t.strip().endswith("?"))


def frames(t, state=None):
    its, _ = FM.interpret(clauses(t), state or DialogueState())
    return its


# ---- chunker ------------------------------------------------------------------------------------------------------------------------------
def test_chunker_negation_tense_and_subject():
    c = clauses("I don't have enough money.")[0]
    assert c.subject.f["pron"] == "i" and c.negated and c.vg.f["verb"] == "have"
    c = clauses("I bought a new laptop yesterday.")[0]
    assert c.tense == "past" and c.nps()[0].f["adjs"] == ["new"]


def test_chunker_repairs_tagger_error_with_lexicon_context():
    c = clauses("I cannot afford it right now.")[0]                  # the tagger calls "afford" a noun; the lexicon + position say verb
    assert c.vg.f["verb"] == "afford" and c.negated


def test_chunker_inverted_question_and_possessive_vs_contraction():
    q = clauses("Where do I live?")[0]
    assert q.wh == "where" and q.inverted and q.vg.f["verb"] == "live"
    assert clauses("My name's Zuri.")[0].vg.f["copula"]                # 's = is
    assert clauses("Peter's cat runs.")[0].subject.f.get("possessor") == "Peter"


def test_number_words():
    assert [words_to_number(x) for x in ("thirty", "twenty five", "twenty-five", "two hundred", "banana")] == [30, 25, 25, 200, None]


# ---- frames: one meaning, many surface forms ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["I live in Kampala.", "I dwell in Kampala.", "I'm based in Kampala.", "I am located in Kampala.", "Kampala is my home.",
                                  "My house is in Kampala.", "I reside in Kampala.", "I am a resident of Kampala.", "Kampala is where I live."])
def test_residence_paraphrases_share_one_frame(text):
    its = frames(text)
    assert len(its) == 1 and its[0].frame == "residence" and its[0].act == "assert"
    assert its[0].roles["place"]["value"] == "Kampala" and its[0].roles["agent"]["t"] == "self"


@pytest.mark.parametrize("text,value", [("I'm short on cash.", "insufficient"), ("I cannot afford it right now.", "insufficient"), ("I don't have enough money.", "insufficient"),
                                        ("I'm broke at the moment.", "insufficient"), ("We are low on funds.", "insufficient"), ("I can afford it.", "sufficient"),
                                        ("I'm not short on cash.", "sufficient"), ("I have enough money.", "sufficient")])
def test_funds_composition_handles_polarity_without_per_phrase_rules(text, value):
    its = frames(text)
    assert its and its[0].frame == "funds" and its[0].roles["value"]["value"] == value, its


def test_similar_words_are_not_equivalent():
    g = default_graph()
    assert g.relation("cash", "money")[0] == "synonym"
    assert g.relation("like", "hate")[0] == "antonym"                    # similar contexts, opposite meaning
    assert g.relation("laptop", "device")[0] in ("hypernym", "related")
    assert g.relation("laptop", "banana") == ("unrelated", 0.0)
    assert not (g.relation("like", "hate")[0] in ("same", "synonym"))


def test_question_uses_same_construction_as_statement():
    q = frames("Where do I live?")[0]
    assert q.frame == "residence" and q.act == "ask" and q.ask == "place"
    q = frames("What do I do for a living?")[0]
    assert q.frame == "occupation" and q.ask == "occupation"


def test_polarity_in_preferences():
    assert frames("I never eat meat.")[0].polarity == "negative"
    assert frames("I love mangoes.")[0].polarity == "positive"
    assert frames("I hate mangoes.")[0].polarity == "negative"


# ---- dialogue state ---------------------------------------------------------------------------------------------------------------------------
def test_pronoun_resolution_uses_salience_and_selectional_restrictions():
    st = DialogueState()
    st.begin_turn(); laptop = st.add_entity("artifact", "laptop", concept="c.laptop")
    st.begin_turn(); peter = st.add_entity("person", "Peter", person=True, gender="male")
    st.begin_turn()
    assert st.resolve_pronoun("it")[0] == laptop                            # persons are excluded for "it"
    assert st.resolve_pronoun("he")[0] == peter
    assert st.resolve_pronoun("she")[0] is None                             # no female entity: never guess
    assert st.resolve_pronoun("it", need_slot="maker")[0] == laptop        # "who makes it" needs an artifact


def test_two_equally_salient_candidates_lower_confidence():
    st = DialogueState(); st.begin_turn()
    st.add_entity("artifact", "laptop"); st.add_entity("artifact", "phone")
    eid, cands, conf = st.resolve_pronoun("it")
    assert conf < 0.6 and len(cands) == 2


def test_pending_questions_lapse_and_state_roundtrips():
    st = DialogueState(); st.begin_turn()
    e = st.add_entity("artifact", "laptop"); st.ask(e, "model", "maker")
    st2 = DialogueState(st.to_dict())
    assert st2.answer_pending()["slot"] == "model"
    for _ in range(5):
        st2.begin_turn()
    assert st2.answer_pending() is None                                     # the topic moved on


def test_attribute_revision_is_recorded_not_overwritten_silently():
    st = DialogueState(); st.begin_turn(); e = st.add_entity("person", "Peter", person=True)
    st.set_attr(e, "residence", "Arusha"); st.begin_turn(); rec = st.set_attr(e, "residence", "Moshi")
    assert rec["revises"]["value"] == "Arusha" and st.corrections[-1]["old"] == "Arusha"


# ---- reasoning --------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,answer,unit", [
    ("Mary has 9 pens. She loses 4. How many pens does Mary have now?", "5", "pen"),
    ("Tom has 5 apples. He gives 2 to Anna. How many does Tom have left?", "3", "apple"),
    ("A book costs 15 dollars. I buy 4 books. How much do I pay?", "60", "dollar"),
    ("A car travels 80 km each hour. How far does it go in 2 hours?", "160", "km"),
    ("A box holds 6 eggs. How many eggs are in 7 boxes?", "42", "egg")])
def test_word_problems_are_solved_exactly(text, answer, unit):
    s = WordProblem().solve(clauses(text))
    assert s and s.text_value() == answer and s.unit == unit and s.steps


def test_deduction_universal_conditional_and_unknown():
    def run(t):
        cl = clauses(t); d = Deduction()
        q = [c for c in cl if c.inverted or c.punct_question]
        d.ingest([c for c in cl if c not in q]); steps = []
        return d.holds(Deduction.clause_prop(q[0]), trace=steps), steps
    assert run("All fish can swim. A salmon is a fish. Can a salmon swim?")[0] is True
    assert run("If the shop is open I buy bread. The shop is open. Do I buy bread?")[0] is True
    assert run("All fish can swim. A salmon is a fish. Can a salmon fly?")[0] is None      # not derivable -> unknown, never "no"
    r, steps = run("All birds have wings. A sparrow is a bird. Does a sparrow have wings?")
    assert r is True and "every bird" in " ".join(steps)


def test_abstract_ordering_chain_and_contradiction():
    a = solve_abstract_order("A is heavier than B. B is heavier than C. Is C heavier than A?")
    assert a.answer == "no" and "A > B > C" in a.steps[0]
    assert solve_abstract_order("A is heavier than B. B is heavier than A. Is A heavier than B?").answer == "inconsistent"
    assert solve_abstract_order("A is heavier than B. C is heavier than D. Is A heavier than D?").answer == "unknown"


def test_planning_decomposes_over_available_days():
    p = plan_from_clause(clauses("How do I prepare for an exam in three days?")[0])
    assert p and p.days == 3 and [w for w, _ in p.steps] == ["Day 1", "Day 2", "Day 3"]
    assert plan_from_clause(clauses("How do I prepare for a banana?")[0]) is None          # no method: no improvisation


# ---- realiser ---------------------------------------------------------------------------------------------------------------------------------
def test_morphology_and_agreement():
    assert inflect("go", "past") == "went" and inflect("carry") == "carries" and inflect("be", "present", 1) == "am" and plural("box") == "boxes"
    assert clause("you", "live", person=2, complements=["in Kampala"]) == "you live in Kampala"
    assert clause("she", "drink", neg=True, contract=True, complements=["milk"]) == "she doesn't drink milk"


def test_lm_prefers_grammatical_word_order():
    lm = default_lm()
    assert lm.score("You live in Kampala.") > lm.score("Kampala in you live.")
    assert lm.score("Which model did you get?") > lm.score("Model which you did get?")


def test_realiser_is_seed_deterministic_and_varies_across_seeds():
    acts = [{"type": "ack", "frame": "residence", "agent": {"kind": "self"}, "value": "Kampala", "novelty": "new"}]
    same = {ActRealizer(seed=3).render(acts) for _ in range(3)}
    assert len(same) == 1
    varied = {ActRealizer(seed=s).render(acts) for s in range(40)}
    assert len(varied) >= 6                                                 # composed from opener x clause x form, not one stored sentence
    assert all("Kampala" in v and v.endswith(".") for v in varied)


def test_realiser_avoids_recent_wording():
    acts = [{"type": "ack", "frame": "occupation", "agent": {"kind": "self"}, "value": "pilot", "novelty": "new"}]
    first = ActRealizer(seed=1).render(acts)
    again = [ActRealizer(seed=1).render(acts, recent=[first]) for _ in range(1)][0]
    assert first != again


def test_uncertain_and_clarify_acts_do_not_assert():
    out = ActRealizer(seed=1).render([{"type": "clarify", "options": ["your laptop", "your phone"], "surface": "it"}])
    assert out.endswith("?") and "laptop" in out and "phone" in out
    out = ActRealizer(seed=2).render([{"type": "unknown", "frame": "residence", "agent": {"kind": "self"}}])
    assert "don't" in out.lower() or "haven't" in out.lower()


# ---- distributional semantics (SYNTHETIC corpus: mechanics only, see docs/v0.1.0/TECHNICAL_REPORT.md) ----------------------------------------------------------
def test_ppmi_vectors_group_words_by_shared_contexts(tmp_path):
    fin = ["money is short this month", "we are short of cash this month", "cash is tight and money is short", "he lacks money and cash", "bank money cash savings grow"] * 3
    trv = ["the train travels to the city", "the bus travels to the city fast", "trains and buses travel between cities", "the city has a train station and bus station"] * 3
    cb = CoocBuilder(tmp_path / "c.sqlite"); cb.add_sentences(fin, "d1"); cb.add_sentences(trv, "d2")
    assert cb.add_sentences(fin, "d1") is False                              # idempotent per document: incremental indexing
    vs = VectorStore(tmp_path / "v.sqlite"); meta = build_vectors(cb, vs, dims=6, min_count=1)
    assert meta["vocab"] > 10
    assert vs.similarity("money", "cash") > vs.similarity("money", "train")
    near = {w for w, _ in vs.nearest("train", 4)}
    assert near & {"bus", "city", "travels", "station", "trains", "buses", "travel", "cities"}          # topical neighbours appear among the top 4
    vs2 = VectorStore(tmp_path / "v2.sqlite"); build_vectors(cb, vs2, dims=6, min_count=1)
    assert vs.vector("money") == vs2.vector("money")                         # deterministic


def test_typed_relation_never_reports_similarity_as_equivalence(tmp_path):
    cb = CoocBuilder(tmp_path / "c.sqlite")
    cb.add_sentences(["i like mangoes a lot", "i hate mangoes a lot", "we like tea in the morning", "we hate tea in the morning", "they like rice every day", "they hate rice every day"] * 3, "d")
    vs = VectorStore(tmp_path / "v.sqlite"); build_vectors(cb, vs, dims=5, min_count=1)
    assert vs.similarity("like", "hate") > 0.8                               # distributionally near-identical
    r = typed_relation(default_graph(), vs, "like", "hate")
    assert r["relation"] == "opposite" and r["basis"] == "lexical"           # ...but the lexicon says opposite, and that wins
    r = typed_relation(ConceptGraph(), vs, "like", "hate")                   # with no lexical knowledge it can only claim "related", capped
    assert r["relation"] == "related" and r["confidence"] <= 0.55 and "not interchangeable" in r["note"]
