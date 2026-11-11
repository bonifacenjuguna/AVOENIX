# Capability assessment (v0.0.1)

Legend: **Known** = verified by an executed test · **Inferred** = follows from the code but not executed · **Assumed** = depends on an unverified component · **Unknown** = not assessed.

## Intelligence core
| Capability | Status | Basis |
|---|---|---|
| Ordering/transitive reasoning, superlatives, contradiction detection, "unknown" reporting | Known | unit + acceptance + evaluation |
| Exact arithmetic (`Fraction`), division by zero reported undefined | Known | tests + evaluation |
| Memory across conversations, user/project isolation | Known | acceptance + integration (both backends) |
| Preference learning with read-back verification and revert | Known | learning tests (both backends) |
| Goal decomposition and next actions | Known | planning tests (narrow patterns) |
| Varied, repetition-aware, emoji-aware replies | Known (behaviour) / Unknown (perceived quality) | response tests; no human evaluation |
| Emotion/sentiment | Known on tested lexicon cases | lexicon-based; no accuracy study |
| PostgreSQL persistence | Known with a non-atomic adapter | transactions untested |

## Knowledge Integrity (new in v0.0.1)
| Capability | Status | Basis |
|---|---|---|
| Claim model with provenance, verification, structured assessment, serialisation | **Implemented** | unit + integration (both backends) |
| User statements not treated as knowledge; established answer wins; original statement retrievable | **Implemented** (for the predicates listed in `docs/KNOWLEDGE_INTEGRITY.md`) | acceptance + evaluation 10/10 |
| Contradiction detection (negation, functional, taxonomic, location, ordering) and preserved conflicts | **Implemented** within those structural kinds | integration |
| Conflict resolution lifecycle and append-only revisions | **Implemented** (manual_choice, dismissed, revised, established_precedence) | integration + API logic tests |
| Memory vs knowledge separation (episodic "User said" linked to the claim) | **Implemented** | acceptance |
| Independent verification of facts | **Not implemented** — no external source; `verified` is reserved; seed facts are `curated` | — |
| Claim classification beyond the predicate list / entity types | **Partial** — other relations are premises | code |
| Temporal, numeric-tolerance, commonsense validation | **Unimplemented** | — |
| Confidence calibration for claims | **Experimental** — measured (0/1 → 1/1 on one case), far too small to claim calibration | evaluation |
| Hearsay ("Someone told me X"), "What about X?" right after a statement, "How old am I?" | **Unimplemented / known parser limits** (the last also fails in v0.0.0) | evaluation findings |
| Cross-engine claim retrieval by context ("What about the USA?") | **Partial** — works after a question; not after a bare statement | acceptance |

## Not implemented / weak (honest list)
- English grammar coverage is narrow. Known failures: "Which is bigger, a cat or a dog?"; plural generics ("Do birds fly?"); "the sum of 4 and 5"; word problems with state; relative clauses; split antecedents; conditionals lose their condition; pending-clarification follow-ups; several paraphrases listed in `docs/TESTING.md` (name phrasings, "Tell me the capital of…", "Keep your answers short").
- Knowledge is a curated seed plus what users tell the system; user statements are claims and are not believed. No external verification source exists (`external_verified` is reserved).
- No temporal, probabilistic, or general commonsense reasoning. No open-ended text generation: by design it can only verbalise structured results.
- Memory retrieval is lexical (BM25-style), no semantic similarity.
- Confidence/bands are evidence-support heuristics; calibration is **not** established.
- Single language (English). Other languages are detected and politely refused.
- Evaluation dataset is small and developer-authored; hold-out is only a discipline marker, not an independent test set.

## Services and UI
| Component | Status |
|---|---|
| API business logic (`ApiCore`): auth, lockout, sessions, scoping, rate limit, audit | Known (tested without HTTP) |
| FastAPI HTTP mapping, CORS, cookies (incl. new export/claims/conflicts routes) | **Unknown** — written, `py_compile`d, never run |
| `migrate.py`, Docker, compose, Railway | **Unknown** — never run |
| Studio v0.0.1 redesign (tokens, light/dark, Markdown chat, grouped history, export, claims/conflicts view) | **Unknown (written, not built or rendered)** — pure-logic parts unit-tested (10 PASSED); components unexecuted |
| Conversation export logic (all formats, completeness > 500 messages, access control, filename safety, audit) | Known (API core tests); HTTP route **Unknown** |
| Studio other pages | Re-skinned read-only pages, same caveat |
| RLS policies | Not tested |

## Security posture (see `docs/SECURITY.md`)
Hashing, token storage, lockout, scoping and error sanitising are tested at the logic level. Transport security, cookie flags in a browser, CORS behaviour and rate limiting behind a proxy/replicas are unverified.
