"""Claim layer: provenance, validation, conflicts, revisions, isolation. Runs on the in-memory backend and, when AVOENIX_TEST_PG is set, on PostgreSQL."""
import pytest

from intelligence.core.errors import InputError, NotFoundError
from intelligence.core.types import Scope
from intelligence.engines.knowledge.engine import KnowledgeEngine
from intelligence.engines.knowledge.terms import entity_term
from tests.support.backends import backend_params, build

A, B = Scope("p1", "alice"), Scope("p1", "bob")


@pytest.fixture(scope="module", params=backend_params())
def _seeded(request):
    k = KnowledgeEngine(build(request.param))
    k.seed()
    return k


@pytest.fixture()
def ke(_seeded):
    b = _seeded.backend
    for t in ("knowledge_conflicts", "knowledge_revisions"):
        for r in b.select(t, {"project_id": ("in", ["p1", "p2"])}):
            b.delete(t, {"id": r["id"]})
    for r in b.select("knowledge_facts", {"project_id": ("in", ["p1", "p2"])}):
        b.delete("knowledge_terms", {"fact_id": r["id"]})
        b.delete("knowledge_facts", {"id": r["id"]})
    return _seeded


def cap(country, city):
    return {"owner": entity_term(country), "value": entity_term(city)}


def test_claim_against_curated_fact_is_contradicted_and_kept(ke):
    r = ke.assert_fact(A, "attr.capital", cap("Kenya", "Mombasa"))
    assert r.fact is not None and r.verification == "contradicted"
    assert r.assessment["level"] in ("conflicting", "unverified", "insufficient") or r.assessment["refutation"] is not None
    assert r.fact.provenance == "user_provided" and not r.fact.established
    assert any(c["check"] == "contradiction" and c["outcome"] == "conflicts_found" for c in r.checks)


def test_agreeing_claim_is_supported_not_independently_verified(ke):
    r = ke.assert_fact(A, "attr.capital", cap("United States", "Washington, D.C."))
    assert r.verification in ("supported", "curated", "verified")
    assert r.verification != "verified"           # curated seed knowledge is honest about not being independently verified


def test_repeating_a_claim_adds_no_support(ke):
    a = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Poseidonis"))
    b = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Poseidonis"))
    assert b.status == "duplicate" and b.fact.id == a.fact.id
    assert (b.assessment or {}).get("support") in (None, 0.0)
    assert b.verification == "unverified"


def test_peer_conflict_is_preserved_both_ways(ke):
    a = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Poseidonis"))
    b = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Marinus"))
    assert b.status == "disputed" and b.conflict_ids
    ids = {c["id"]: c for c in ke.conflicts(A, status="open")}
    c = ids[b.conflict_ids[0]]
    assert {c["fact_a"], c["fact_b"]} == {a.fact.id, b.fact.id}
    assert {x.verification for x in ke.claims(A)} == {"conflicting"}


def test_manual_resolution_keeps_history(ke):
    a = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Poseidonis"))
    b = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Marinus"))
    c = ke.resolve_conflict(A, b.conflict_ids[0], "manual_choice", winner=a.fact.id, note="chose first")
    assert c["status"] == "resolved" and c["resolution"] == "manual_choice"
    h = ke.history(A, b.fact.id)
    assert h["claim"]["status"] == "superseded" and h["revisions"]
    with pytest.raises(InputError):
        ke.resolve_conflict(A, b.conflict_ids[0], "dismissed")
    with pytest.raises(InputError):
        ke.resolve_conflict(A, b.conflict_ids[0], "manual_choice", winner="nope")


def test_cannot_resolve_conflict_outside_scope(ke):
    ke.assert_fact(A, "attr.capital", cap("Atlantis", "Poseidonis"))
    b = ke.assert_fact(A, "attr.capital", cap("Atlantis", "Marinus"))
    with pytest.raises(NotFoundError):
        ke.resolve_conflict(B, b.conflict_ids[0], "dismissed")
    assert ke.claims(B) == [] and ke.conflicts(B) == []


def test_revision_preserves_original_and_does_not_trust_newest(ke):
    a = ke.assert_fact(A, "attr.capital", cap("Kenya", "Mombasa"))
    r = ke.revise(A, a.fact.id, {"value": entity_term("Kisumu")}, reason="typo")
    assert r.fact.id != a.fact.id and r.revision_id
    assert r.verification == "contradicted"          # still contradicts Nairobi: newest is not assumed right
    h = ke.history(A, a.fact.id)
    assert h["claim"]["status"] == "superseded" and h["revisions"][0]["reason"] == "typo"
    with pytest.raises(InputError):
        ke.revise(A, a.fact.id, {"value": entity_term("X")})      # already superseded


def test_validate_claim_is_a_dry_run(ke):
    before = len(ke.claims(A))
    v = ke.validate_claim(A, "attr.capital", cap("Kenya", "Mombasa"))
    assert v["conflicts"] and any(c["check"] == "contradiction" for c in v["checks"]) and len(ke.claims(A)) == before


def test_claims_are_isolated_between_users(ke):
    ke.assert_fact(A, "attr.capital", cap("Atlantis", "Poseidonis"))
    ke.assert_fact(B, "attr.capital", cap("Atlantis", "Marinus"))
    assert [c.object for c in ke.claims(A)] == [c.object for c in ke.claims(A)] and len(ke.claims(A)) == 1 and len(ke.claims(B)) == 1
    assert ke.claims(A)[0].object != ke.claims(B)[0].object
    assert ke.conflicts(A) == []        # another user's claim is not a conflict for me


def test_claim_serialisation_round_trip(ke):
    from intelligence.representation.claims import Claim
    r = ke.assert_fact(A, "attr.capital", cap("Kenya", "Mombasa"))
    c = ke.claims(A)[0]
    assert Claim.from_dict(c.to_dict()).to_dict() == c.to_dict() and c.to_dict()["schema"] == "claim/1.0"
