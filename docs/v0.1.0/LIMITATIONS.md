# Limitations and next steps — v0.1.0

## Known limitations
- Understanding coverage is bounded by hand-authored frames (nine plus the funds analysis), methods and the seed lexicon. Unlisted verbs/nouns fall through to the v0.0.1 pipeline.
- Third-party and conversation-entity attributes are conversation-scoped (not persisted across conversations).
- Preferences are shown as lemmas ("you love mango"); no plural/mass-noun handling from the user's surface form.
- Verb coverage of the tagger is incomplete ("Peter's dog barks" is not split because "barks" is unknown).
- Spell repair is shared with the legacy pipeline and can mis-correct rare words ("chess" → "chef" was observed).
- HTN method library is small (prepare, learn).
- Realiser LM is trained on a tiny corpus.
- "Call me X" is answered by the meaning layer (task label differs from v0.0.1).
- Importers and distributional module: synthetic fixtures only; real-data quality **UNVERIFIED**. The distributional module is not wired into live understanding.
- Held-out set no longer independent (see EVALUATION.md).

## Not tested / not verified
- PostgreSQL backend tests, FastAPI HTTP layer (fastapi unavailable earlier), Studio build and browser rendering: **NOT TESTED** in this session.
- Real WordNet/ConceptNet/Wikidata/corpus imports: **UNVERIFIED**.

## Next steps
1. Supply real WordNet/OEWN and a licensed corpus; run the ingest pipeline and measure.
2. Independent held-out set written by a different person; human-rated responses.
3. Extend frames/methods (data only); add unknown-word clarification using the distributional module.
4. Persist third-party entity attributes with provenance behind the Knowledge Engine.
5. Run PG, HTTP and Studio checks in an environment with those dependencies.
