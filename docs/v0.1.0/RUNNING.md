# Run and test — v0.1.0

```bash
python -m venv .venv && . .venv/bin/activate        # Python 3.11+; core needs only the standard library
PYTHONPATH=. python -m pytest -q tests services/intelligence-api/tests

# evaluation (after = default, before = --no-meaning)
python scripts/run_evaluation.py --dataset evaluation/datasets/intelligence_v1_heldout.json --out /tmp/heldout.json
python scripts/run_evaluation.py --dataset evaluation/datasets/intelligence_v1_heldout.json --no-meaning --out /tmp/heldout_before.json

# inspect how a conversation was understood (local, isolated, in-memory)
python scripts/trace_turn.py "I bought a new laptop yesterday." "It was expensive." "Who makes it?"
```
PostgreSQL tests: set `AVOENIX_TEST_PG=host:port:db[:user]` and install `psycopg`. API diagnostics: set `AVOENIX_DIAGNOSTICS_ENABLED=true` and log in as admin, then `POST /v1/diagnostics/turns {"texts": [...]}`.
Optional: import a lexical resource with a manifest (see `tests/fixtures/ingest/manifest_wordnet.json`) via `intelligence.ingest.pipeline.import_source(manifest, input_path, store)`, then `AvoenixConfig(lexicon_store=<path>)`.
