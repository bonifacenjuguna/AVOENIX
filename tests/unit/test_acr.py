import pytest

from intelligence.core.errors import RepresentationError
from intelligence.representation import (
    ACRBuilder, ACRDocument, Event, Provenance, concepts, dumps, loads, register_migration,
)
from intelligence.representation.serialization import unregister_migration


def build_gift():
    b = ACRBuilder(default_provenance=Provenance("user_statement", "t"))
    sarah = b.entity("Sarah", "class.person", features={"gender": "f", "animacy": "animate"})
    mike = b.entity("Michael", "class.person", features={"gender": "m", "animacy": "animate"})
    book = b.entity("book", "class.thing", features={"animacy": "inanimate"})
    yesterday = b.time("relative", anchor="utterance_time", offset={"days": -1}, granularity="day")
    school = b.entity("school", "class.place")
    need = b.event("act.need", {"experiencer": mike, "theme": book}, tense="past", purpose=school)
    give = b.event("act.give", {"agent": sarah, "recipient": mike, "theme": book}, time=yesterday, tense="past", root=True)
    b.link("cause", need, give, root=True)
    return b.build()


def test_compose_event_with_purpose_time_and_links():
    doc = build_gift()
    assert doc.validate().ok, doc.validate().errors
    give = [e for e in doc.of_kind(Event) if e.action == "act.give"][0]
    assert doc.get(give.roles["agent"]).label == "Sarah"
    assert doc.get(give.time).offset == {"days": -1}


def test_roundtrip_serialization_is_lossless():
    doc = build_gift()
    again = loads(dumps(doc))
    assert again.to_dict() == doc.to_dict()
    assert again.validate().ok


def test_dangling_reference_is_reported():
    b = ACRBuilder()
    b.event("act.give", {"agent": "missing"})
    rep = b.build().validate()
    assert not rep.ok and any("dangling" in e for e in rep.errors)
    with pytest.raises(RepresentationError):
        b.build().validate(strict=True)


def test_structural_cycle_detected():
    b = ACRBuilder()
    a = b.proposition("rel.is_a", {})
    c = b.condition(a, a)
    b.doc.nodes[a].args["x"] = c
    assert any("cycle" in e for e in b.build().validate().errors)


def test_confidence_range_and_polarity_validated():
    b = ACRBuilder()
    b.proposition("rel.is_a", {}, confidence=1.5, polarity="maybe")
    errs = b.build().validate().errors
    assert any("confidence" in e for e in errs) and any("polarity" in e for e in errs)


def test_merge_remaps_references():
    a, b = build_gift(), build_gift()
    before = len(a)
    mapping = a.merge(b, prefix="x:")
    assert len(a) == before * 2
    assert a.validate().ok
    assert all(v.startswith("x:") for v in mapping.values())


def test_subgraph_follows_references():
    doc = build_gift()
    give = [e for e in doc.of_kind(Event) if e.action == "act.give"][0]
    sub = doc.subgraph([give.id])
    assert give.id in sub.nodes and sub.validate().ok
    assert not any(isinstance(n, Event) and n.action == "act.need" for n in sub.nodes.values())


def test_unknown_node_kind_strict_and_lenient():
    data = build_gift().to_dict()
    data["nodes"].append({"kind": "hologram", "id": "zz", "shape": "cube"})
    with pytest.raises(RepresentationError):
        ACRDocument.from_dict(data)
    doc = ACRDocument.from_dict(data, strict=False)
    assert doc.nodes["zz"].raw_kind == "hologram"        # preserved, not dropped
    assert ACRDocument.from_dict(doc.to_dict(), strict=False).nodes["zz"].data["shape"] == "cube"


def test_unknown_fields_survive_roundtrip():
    data = build_gift().to_dict()
    data["nodes"][0]["future_field"] = {"a": 1}
    doc = ACRDocument.from_dict(data)
    assert doc.nodes[data["nodes"][0]["id"]].annotations["_unknown_fields"]["future_field"] == {"a": 1}


def test_schema_migration_chain():
    def old_to_new(d):  # synthetic older schema used only by this test
        d["nodes"] = [dict(n, kind={"thing": "entity"}.get(n["kind"], n["kind"])) for n in d["nodes"]]
        return d

    register_migration("acr/0.9-test", "acr/1.0", old_to_new)
    try:
        legacy = {"schema_version": "acr/0.9-test", "id": "d", "nodes": [
            {"kind": "thing", "id": "a", "label": "Rex", "entity_type": "class.animal"}], "roots": ["a"]}
        from intelligence.representation import from_dict
        doc = from_dict(legacy)
        assert doc.schema_version == "acr/1.0" and doc.get("a").label == "Rex"
    finally:
        unregister_migration("acr/0.9-test")
    with pytest.raises(RepresentationError):
        loads('{"schema_version": "acr/9.9", "nodes": []}')


def test_reference_resolution_helper():
    b = ACRBuilder()
    m = b.entity("Michael", "class.person")
    ref = b.reference("pronoun", features={"gender": "m"}, resolved=m)
    doc = b.build()
    assert doc.resolve(ref).label == "Michael"


def test_concept_inventory_properties():
    assert concepts.is_a("class.person", "class.entity")
    assert concepts.is_transitive("rel.exceeds") and concepts.is_symmetric("rel.equal_on")
    assert concepts.is_functional("rel.has_name")
    assert concepts.get("dim.age").meta["property"] == "prop.age"
