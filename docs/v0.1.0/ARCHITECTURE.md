# Architecture report — v0.1.0 (meaning layer)

AVOENIX remains a **non-LLM, non-neural algorithmic system**: no language models, no neural networks, no pretrained models or embeddings, no AI inference APIs. The core is stdlib-only and offline-capable. Exact arithmetic stays in `algorithms.arithmetic`.

## Diagnosis of v0.0.1 (why it failed on unfamiliar sentences)
The v0.0.1 pipeline matched surface structure: a tagger/parser produced an ACR document and handlers fired on specific verbs and question shapes. Consequences measured on the new dev/held-out sets (baseline: dev 5/33, held-out 11/64):
- "I dwell in Kampala", "Kampala is my home", "I'm based in Kampala" were three different, mostly unhandled inputs although they mean one thing.
- No state between turns beyond stored facts: "It was expensive" / "Who makes it?" had no referent.
- Money-shortage phrasings needed one rule each; negation ("not short on cash") was not composed.
- Hearsay ("Peter says …") was absorbed or ignored rather than kept as an attributed claim.
- Replies were fixed strings per handler.

## Turn flow
```
text → input engine (normalise, spell-repair) → language engine (tokens, POS)
     → MeaningLayer.handle                         [new, tried first]
          chunker → clauses → frame matcher → dialogue state → (reasoners | knowledge) → acts → realiser
        ├─ understood: Outcome → _finish_meaning (emotion, personality, memory, context update, TurnResult)
        ├─ world-attribute paraphrase: rewritten to a canonical question and sent to the v0.0.1 pipeline
        └─ not understood: returns None → the v0.0.1 pipeline runs unchanged
```
`AvoenixConfig(meaning_enabled=False)` (CLI `--no-meaning`) reproduces v0.0.1 behaviour exactly.

## Components (`intelligence/meaning/`)
| Module | Responsibility |
|---|---|
| `chunker.py` | POS-repairing chunker → `Clause`/`Chunk` (subject, verb group with tense/negation/modality, NPs, PPs, wh, inversion, reported-speech and subordinate split, number words). |
| `lexicon.py`, `data/seed_lexicon.json` | Concept graph: lemma → concept clusters, typed edges (synonym, antonym, hypernym, related) with confidence and `via` provenance. Never crosses part of speech; similarity ≠ equivalence. Imported synsets extend it. |
| `frames.py`, `data/frames.json`, `slots.json` | Semantic frames as data: constructions (`V`, `V_PASSIVE`, `COP_ADJ`, `COP_NP`, `POSS_COP`, `NP_PP`, `COP_NAME`, `COP_WHERE`) whose open slots are filled by concept clusters, with selectional restrictions. Compositional signed "funds" interpretation. |
| `dialogue.py` | `DialogueState`: entities with salience decay (0.72/turn), pronoun resolution (gender/animacy/selectional restrictions, ambiguity lowers confidence, no guessing), pending slots that lapse, a correction log, recent-output log. Serialised in `ConversationState`. |
| `reason.py`, `planning.py`, `data/methods.json` | Word-problem ledger → exact engine; universal/conditional deduction with trace and honest `unknown`; abstract ordering via `algorithms.partial_order` with contradiction detection; HTN decomposition over available days. |
| `realize.py`, `data/realiser_corpus.txt` | Morphology, clause grammar, act renderers (ack, answer, unknown, ask_slot, clarify, confirm_revision, report, prefs, …); candidates ranked by a trigram LM (ranking prior only), seeded softmax choice, repeat penalty. |
| `engine.py` | Orchestrates the stages and returns an `Outcome` with a full inspection trace. |

## Storage and truth
- Personal facts about the user (name, residence, job, funds, preferences, possessions) go through the **Knowledge Engine** with provenance (`user_statement`).
- Third-party and conversation-entity attributes live in dialogue state only (conversation-scoped).
- Hearsay becomes an *attributed claim*; it is checked against established facts and never stored as the user's fact.
- Imported data (`intelligence/ingest/`) reaches the Knowledge Engine only as candidates (`source_type="imported"`, reliability prior 0.5, confidence cap ≤ 0.8). **Nothing imported is automatically true.**

## Security boundaries (unchanged, plus)
- Public endpoints never return the inspection record. It exists only when `AvoenixConfig.diagnostics=True`, which no public path sets.
- `POST /v1/diagnostics/turns`: 404 unless `AVOENIX_DIAGNOSTICS_ENABLED=true`; admin only (403 otherwise, audited); runs an isolated in-memory engine so it cannot read any user's data; audit stores counts only.
- No authentication, rate-limit or scoping logic was weakened.
