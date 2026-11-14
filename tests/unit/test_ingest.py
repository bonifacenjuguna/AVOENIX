"""Ingestion foundation: format-faithful *synthetic* fixtures only (no real WordNet/ConceptNet/Wikidata file is available offline)."""
import json
import sqlite3
from pathlib import Path

import pytest

from intelligence.ingest import ManifestError, ProcessedStore, SourceManifest, import_source, list_imports, restore_import, revert_import
from intelligence.meaning import lexicon
from intelligence.meaning.lexicon import ConceptGraph

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "ingest"


def mf(**kw):
    base = dict(source_id="fixture-wn", name="fixture", version="1", format="wordnet_wndb", license="CC0-1.0")
    base.update(kw)
    return SourceManifest(**base)


@pytest.fixture
def store(tmp_path):
    s = ProcessedStore(tmp_path / "store")
    yield s
    s.close()


def test_wordnet_import_counts_rejects_and_raw_preserved(store):
    verb = import_source(mf(), FIX / "data.verb", store, max_reject_rate=0.5)
    assert verb.status == "active" and verb.counts["rejected"] == 1                    # the malformed line is counted, not hidden
    assert any("wordnet line" in k for k in verb.rejects)
    raw = list((store.root / "raw").iterdir())
    assert len(raw) == 1 and raw[0].read_bytes() == (FIX / "data.verb").read_bytes()      # raw data byte-identical, kept apart from processed rows
    lemmas = {r[0] for r in store.con.execute("SELECT lemma FROM synset_lemmas")}
    assert {"live", "domicile", "sojourn", "abide"} <= lemmas
    assert store.con.execute("SELECT COUNT(*) FROM relations WHERE rel='hypernym'").fetchone()[0] > 0   # synset pointer resolved to lemma relations


def test_reimport_identical_input_is_skipped(store):
    a = import_source(mf(), FIX / "data.adj", store)
    b = import_source(mf(), FIX / "data.adj", store)
    assert a.status == "active" and b.status == "skipped"
    assert store.con.execute("SELECT COUNT(*) FROM synset_lemmas").fetchone()[0] == 3


def test_license_gate_and_confidence_cap():
    with pytest.raises(ManifestError):
        mf(license="Proprietary-EULA").validate()
    with pytest.raises(ManifestError):
        mf(license="CC-BY-4.0").validate()                                              # attribution required
    with pytest.raises(ManifestError):
        mf(confidence_cap=0.99).validate()                                              # imported data may never be treated as established
    assert mf(license="Proprietary-EULA").validate(accept_unknown_license=True).redistributable is False


def test_conceptnet_filters_language_selfloops_and_malformed(store):
    rep = import_source(mf(source_id="fixture-cn", format="conceptnet_csv"), FIX / "conceptnet.csv", store, max_reject_rate=0.5)
    rels = {(a, r, b) for a, r, b, w in store.con.execute("SELECT src, rel, dst, weight FROM relations")}
    assert ("broke", "synonym", "penniless") in rels and ("rich", "antonym", "poor") in rels
    assert not any("riche" in x for t in rels for x in t)                               # non-English edge dropped
    assert rep.counts["rejected"] == 2                                                  # self loop + malformed line
    assert max(w for *_, w in store.con.execute("SELECT src, rel, dst, weight FROM relations")) <= 0.6


def test_quality_gate_fails_and_rolls_back(store):
    rep = import_source(mf(source_id="fixture-bad"), FIX / "data.verb", store, max_reject_rate=0.01)
    assert rep.status == "failed" and "quality gate" in rep.notes[0]
    assert store.con.execute("SELECT COUNT(*) FROM synset_lemmas").fetchone()[0] == 0   # nothing half-imported


def test_wikidata_statements_are_candidates_with_capped_confidence(store):
    rep = import_source(mf(source_id="fixture-wd", format="wikidata_jsonl", license="CC0-1.0"), FIX / "wikidata.jsonl", store, max_reject_rate=0.6)
    rows = store.con.execute("SELECT subject, predicate, object, confidence, status FROM statements ORDER BY subject").fetchall()
    assert ("Kenya", "capital", "Nairobi", 0.6, "candidate") in rows
    assert all(r[3] <= 0.6 and r[4] == "candidate" for r in rows)
    assert any("candidates" in n for n in rep.notes)


def test_revert_and_restore_change_what_the_lexicon_sees(store):
    rep = import_source(mf(), FIX / "data.verb", store, max_reject_rate=0.5)
    base = ConceptGraph.from_seed()
    assert not base.concepts_of("domicile")
    g = ConceptGraph.from_seed()
    assert g.extend_from_store(store.db_path) > 0
    m = g.concepts_of("domicile", "verb")[0]
    assert m.concept == "c.reside" and m.via.startswith("imported:") and m.confidence < 1.0   # mapped through a shared synset, flagged as imported
    assert revert_import(store, rep.import_id)
    g2 = ConceptGraph.from_seed()
    assert g2.extend_from_store(store.db_path) == 0
    assert restore_import(store, rep.import_id)
    assert ConceptGraph.from_seed().extend_from_store(store.db_path) > 0
    assert [i["status"] for i in list_imports(store)] == ["active"]


def test_imported_lemma_never_crosses_part_of_speech(store):
    import_source(mf(), FIX / "data.adj", store)
    g = ConceptGraph.from_seed()
    g.extend_from_store(store.db_path)
    # "scarce" shares a synset with the seed adjective "short" (c.insufficient); it must not be offered as a verb or noun concept
    assert [m.concept for m in g.concepts_of("scarce", "adj", strict=True)] == ["c.insufficient"]
    assert g.concepts_of("scarce", "verb", strict=True) == []


def test_unseen_vocabulary_improves_understanding_only_with_the_import(store, tmp_path):
    """Before/after: 'I domicile in Kampala.' is not understood with the seed lexicon alone and is with the imported synset."""
    from intelligence.app import Avoenix, AvoenixConfig
    from intelligence.core.types import Scope
    from intelligence.storage import MemoryBackend
    import_source(mf(), FIX / "data.verb", store, max_reject_rate=0.5)

    def ask(cfg):
        app = Avoenix(MemoryBackend(), cfg)
        sc = Scope(project_id="p", user_id="u")
        r = app.process_turn(sc, "I domicile in Kampala.")
        r2 = app.process_turn(sc, "Where do I live?", r.conversation_id)
        return r2.response
    try:
        before = ask(AvoenixConfig())
        after = ask(AvoenixConfig(lexicon_store=str(store.db_path)))
    finally:
        lexicon.use_store(None)
    assert "Kampala" not in before
    assert "Kampala" in after
