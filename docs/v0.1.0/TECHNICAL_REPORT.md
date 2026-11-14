# Technical / algorithm report — v0.1.0

Each algorithm below is classical (symbolic, statistical or information-theoretic). None is a neural or pretrained model.

| Need | Algorithm | Why this one |
|---|---|---|
| Phrase structure | Rule-based chunker over tagger output with lexicon-driven POS repair | Deterministic and inspectable; the tagger mislabels words like "afford"/"use"/"open", so the concept lexicon plus position repairs them. |
| Meaning equivalence | Concept clusters + typed edges; frames with open-class slots | One construction covers every member of a cluster, so a new synonym is a data change, not a code change. Antonyms and hypernyms are separate edge types so "like"/"hate" are never merged. |
| Compositional polarity | Signed concepts (insufficient/penniless/lack = −1, enough/afford = +1) multiplied by negation | Handles "not short on cash" without a rule per phrase. |
| Reference | Salience decay (0.72/turn) + selectional restrictions (it ≠ person; "who makes it" needs an artifact) + gender | Cheap, explainable, degrades to a clarification question when two candidates tie. |
| Reported speech | Clause split at the first NP after a say/think verb; stored as attributed claim | Keeps hearsay out of the user's own facts. |
| Arithmetic | Ledger → existing exact evaluator | Exactness is not delegated to heuristics. |
| Deduction | Backward chaining over universals/conditionals/is-a with trace | Answers "unknown" when not derivable instead of "no". |
| Ordering | `algorithms.partial_order` | Detects cycles → "inconsistent". |
| Planning | HTN methods (`methods.json`) | Small, auditable method library; no method → no improvised plan. |
| Generation | Grammar + morphology, candidates ranked by an interpolated add-k trigram LM, softmax with seeded RNG, repeat penalty | Variation without stored sentences; the LM only orders candidates the grammar already produced. |
| Data-driven lexicon | Streaming importers (WordNet WNDB, ConceptNet CSV, Wikidata JSONL, text) into SQLite; licence gate; confidence cap; quality gate with rollback; reversible | Resources can be added or removed without code changes and without trusting them. |
| Distributional similarity | Incremental co-occurrence → PPMI (context smoothing α=0.75) → orthogonal subspace iteration (truncated eigen-decomposition) | Standard count-based method in pure stdlib; only yields "related" so similarity is never treated as synonymy. |

## Honest scope
- Frames, methods and the seed lexicon are hand-authored knowledge. The architecture makes extending them a data task; it does not remove the need to author them.
- The realiser's LM corpus is tiny; it ranks among grammatical candidates, nothing more.
- Importers and the distributional module have been run only on small synthetic fixtures (no network in the build environment). Behaviour on real WordNet/ConceptNet/Wikidata/corpora is **UNVERIFIED**.
