import pytest

from intelligence.core.errors import NotFoundError, ScopeError
from intelligence.core.types import Scope
from intelligence.engines.knowledge.engine import KnowledgeEngine
from intelligence.engines.knowledge.terms import entity_term, kind_term
from tests.support.backends import backend_params, build

A, B, C = Scope("p1", "alice"), Scope("p1", "bob"), Scope("p2", "alice")


@pytest.fixture(scope="module", params=backend_params())
def _seeded(request):
    k = KnowledgeEngine(build(request.param))
    k.seed()                     # seeding over psql subprocesses is slow (~14 s), so it is done once per module
    return k


@pytest.fixture()
def ke(_seeded):
    b = _seeded.backend           # drop everything except curated global rows between tests
    for r in b.select("knowledge_facts", {"project_id": ("in", ["p1", "p2"])}):
        b.delete("knowledge_terms", {"fact_id": r["id"]})
        b.delete("knowledge_facts", {"id": r["id"]})
    return _seeded


def test_seed_is_idempotent_and_labelled(ke):
    first = ke.backend.count("knowledge_facts")
    again = ke.seed()
    assert again["added"] == 0 and ke.backend.count("knowledge_facts") == first
    f = ke.query(A, "attr.capital", {"owner": "france"})[0]
    assert f.args["value"]["label"] == "Paris" and f.source_type == "seed_curated" and f.level == "global"


def test_unknown_is_not_invented(ke):
    assert ke.query(A, "attr.capital", {"owner": "atlantis"}, include_self=False) == []
    r = ke.find_entity(A, "Fance")
    assert not r["found"] and r["suggestions"][0]["label"] == "France"      # suggested, never auto-applied


def test_user_facts_are_scoped_to_user_and_project(ke):
    ke.assert_fact(A, "rel.is_a", {"subject": entity_term("Zed"), "object": kind_term("kind.wizard", "wizard")})
    assert ke.query(A, "rel.is_a", {"subject": "zed"}, include_self=False)
    assert not ke.query(B, "rel.is_a", {"subject": "zed"}, include_self=False)        # other user, same project
    assert not ke.query(C, "rel.is_a", {"subject": "zed"}, include_self=False)        # same user id, other project
    assert not ke.facts_about(B, "zed") and ke.facts_about(A, "zed")
    assert ke.stats(B)["by_level"].get("user", 0) == 0


def test_project_level_knowledge_is_shared_in_project_only(ke):
    ke.assert_fact(A, "attr.capital", {"owner": entity_term("Narnia"), "value": entity_term("Cair Paravel")}, level="project", source_type="learned")
    assert ke.query(B, "attr.capital", {"owner": "narnia"}, include_self=False)
    assert not ke.query(C, "attr.capital", {"owner": "narnia"}, include_self=False)


def test_user_cannot_write_curated_or_verified_sources(ke):
    with pytest.raises(ScopeError):
        ke.assert_fact(A, "rel.is_a", {"subject": entity_term("X"), "object": kind_term("kind.y")}, source_type="seed_curated")
    with pytest.raises(ScopeError):
        ke.assert_fact(A, "rel.is_a", {"subject": entity_term("X"), "object": kind_term("kind.y")}, source_type="external_verified")


def test_user_cannot_overwrite_curated_knowledge(ke):
    r = ke.assert_fact(A, "attr.capital", {"owner": entity_term("France"), "value": entity_term("Lyon")})
    assert r.status == "disputed" and r.contradictions[0]["kind"] == "functional"
    answers = ke.query(A, "attr.capital", {"owner": "france"}, include_self=False)
    assert [f.args["value"]["label"] for f in answers] == ["Paris"]          # disputed fact is not served as knowledge
    assert ke.query(A, "attr.capital", {"owner": "france"}, statuses=("disputed",), include_self=False)[0].args["value"]["label"] == "Lyon"


def test_duplicate_negation_and_supersession(ke):
    name = lambda v: {"owner": {"t": "self", "key": "@user", "label": "you"}, "value": entity_term(v)}
    assert ke.assert_fact(A, "attr.name", name("Alex")).status == "stored"
    assert ke.assert_fact(A, "attr.name", name("Alex")).status == "duplicate"
    r = ke.assert_fact(A, "attr.name", name("Sam"))                          # same-user functional update -> supersede, keep history
    assert r.status == "superseded" and len(r.superseded) == 1
    assert [f.args["value"]["label"] for f in ke.query(A, "attr.name", {"owner": "@user"}, include_self=False)] == ["Sam"]
    hist = ke.list_facts(A, statuses=("superseded",))
    assert hist and hist[0].args["value"]["label"] == "Alex"
    neg = ke.assert_fact(A, "rel.is_a", {"subject": entity_term("Zed"), "object": kind_term("kind.wizard")})
    assert neg.status == "stored"
    r2 = ke.assert_fact(A, "rel.is_a", {"subject": entity_term("Zed"), "object": kind_term("kind.wizard")}, polarity="negative")
    assert r2.contradictions and r2.contradictions[0]["kind"] == "negation"


def test_circular_ordering_is_disputed(ke):
    dim = {"t": "concept", "key": "dim.age", "label": "age"}
    mk = lambda a, b: {"greater": entity_term(a), "lesser": entity_term(b), "dimension": dim}
    assert ke.assert_fact(A, "rel.exceeds", mk("John", "Peter")).status == "stored"
    assert ke.assert_fact(A, "rel.exceeds", mk("Peter", "David")).status == "stored"
    r = ke.assert_fact(A, "rel.exceeds", mk("David", "John"))
    assert r.status == "disputed" and r.contradictions[0]["kind"] == "ordering"


def test_retract_requires_scope_and_never_touches_global(ke):
    f = ke.assert_fact(A, "rel.is_a", {"subject": entity_term("Zed"), "object": kind_term("kind.wizard")}).fact
    with pytest.raises(NotFoundError):
        ke.retract(B, f.id)
    assert ke.retract(A, f.id)
    assert not ke.query(A, "rel.is_a", {"subject": "zed"}, include_self=False)
    g = ke.query(A, "attr.capital", {"owner": "france"}, include_self=False)[0]
    with pytest.raises(NotFoundError):
        ke.retract(A, g.id)


def test_self_model_is_generated_not_stored(ke):
    facts = ke.query(A, "rel.is_a", {"subject": "avoenix"})
    assert any(f.polarity == "negative" and f.args["object"]["key"] == "kind.large_language_model" for f in facts)
    assert ke.backend.count("knowledge_facts", {"source_type": "system"}) == 0


def test_lexical_search_ranks_relevant_fact(ke):
    top = ke.search(A, "capital of Kenya")[0][0]
    assert top.args["owner"]["label"] == "Kenya" or top.args["value"]["label"] == "Nairobi"
