# Capability assessment (v0.0.0)

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

## Not implemented / weak (honest list)
- English grammar coverage is narrow. Known failures: "Which is bigger, a cat or a dog?"; plural generics ("Do birds fly?"); "the sum of 4 and 5"; word problems with state; relative clauses; split antecedents; conditionals lose their condition; pending-clarification follow-ups; several paraphrases listed in `docs/TESTING.md` (name phrasings, "Tell me the capital of…", "Keep your answers short").
- Knowledge is a 92-fact curated seed plus what users tell the system. No external verification source exists (`external_verified` is reserved).
- No temporal, probabilistic, or general commonsense reasoning. No open-ended text generation: by design it can only verbalise structured results.
- Memory retrieval is lexical (BM25-style), no semantic similarity.
- Confidence/bands are evidence-support heuristics; calibration is **not** established.
- Single language (English). Other languages are detected and politely refused.
- Evaluation dataset is small and developer-authored; hold-out is only a discipline marker, not an independent test set.

## Services and UI
| Component | Status |
|---|---|
| API business logic (`ApiCore`): auth, lockout, sessions, scoping, rate limit, audit | Known (tested without HTTP) |
| FastAPI HTTP mapping, CORS, cookies | **Unknown** — written, `py_compile`d, never run |
| Alembic migration, Docker, compose, Railway | **Unknown** — never run |
| Studio Milestone 1 (login, chat, history, health, latency, errors) | **Unknown** — syntax-checked only; never built or rendered |
| Studio Milestones 2–4 | Partial read-only pages, same caveat; Milestone 5 not implemented |
| RLS policies | Not tested |

## Security posture (see `docs/SECURITY.md`)
Hashing, token storage, lockout, scoping and error sanitising are tested at the logic level. Transport security, cookie flags in a browser, CORS behaviour and rate limiting behind a proxy/replicas are unverified.
