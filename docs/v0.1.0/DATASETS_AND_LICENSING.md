# Datasets and licensing — v0.1.0

Nothing third-party is bundled. The build environment had no network, so no external dataset was downloaded or parsed. Supplying data is the user's step; the manifest enforces the licence gate.

| Resource | Licence (as published; verify before use) | Reader | Status here |
|---|---|---|---|
| Princeton WordNet 3.x (WNDB) | WordNet licence (permissive, attribution) | `readers.py` WNDB | Parser tested on a synthetic format-faithful fixture only — **real file UNVERIFIED** |
| Open English WordNet | CC BY 4.0 | WNDB | same |
| ConceptNet 5 | CC BY-SA 4.0 (share-alike) | CSV | synthetic fixture only |
| Wikidata | CC0 | JSONL | synthetic fixture only |
| Plain text corpora | per corpus | text | synthetic fixture only |

Every import needs a manifest declaring source, licence, version and trust; imports with a missing or disallowed licence are refused. Imported statements are capped at confidence 0.8 (default 0.6), preserved raw by sha256, deduplicated, quality-gated (rollback on failure), reversible, and offered to the Knowledge Engine only as `source_type="imported"` candidates. Share-alike resources (ConceptNet) may impose obligations on derived data: check before redistributing a processed store.

Evaluation data authored in this repo: `intelligence_v1_dev.json` (33 cases), `intelligence_v1_heldout.json` (64 cases, sha256 pinned in `intelligence_v1_heldout.sha256`). The pin was recorded at the final state of the set, after the fixlog changes — see `docs/v0.1.0/EVALUATION.md` for why it is not independent.
