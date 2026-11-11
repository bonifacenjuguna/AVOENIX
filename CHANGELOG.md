# Changelog

All notable changes to AVOENIX are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [Semantic Versioning](https://semver.org/) as described in `docs/VERSIONING.md`.

## [v0.0.1] — Knowledge Integrity + Studio redesign

### Added
- **Knowledge Integrity.** User statements about the world are stored as *claims* (`claim/1.0`) with provenance, claim type, verification state, a structured confidence assessment, timestamps, evidence and conflict references. Saying something no longer makes it knowledge. Curated seed facts are "curated" (established for answering, honestly **not** independently verified). See `docs/KNOWLEDGE_INTEGRITY.md`.
- Offline validation layer (`engines/knowledge/integrity.py`): source reliability, contradiction detection (negation, functional/temporal, taxonomic incl. inherited negation, location, ordering cycles), comparison with internal knowledge (agreement and is-a / located-in entailment), evidence availability, logical consistency. No network, no ML.
- Conflict preservation with status and resolution history; append-only revision history; entity alias canonicalisation (USA → United States).
- Memory vs knowledge separation: the orchestrator writes an episodic memory ("User said …") and links it to the claim.
- Reasoning status `unverified_claim`; response messages `claim_recorded` / `claim_answer`; `confidence.factual_support`; confidence is not reported for unverified claims.
- Migration `0002_knowledge_integrity.sql` (+ `_down.sql`): additive, idempotent, one-time backfill of existing facts; `migrate.py` now applies all forward migrations in order.
- API: `GET /v1/conversations/{id}/export` (complete conversation, md/txt/json), `GET /v1/claims`, `/v1/claims/{id}/history`, `/v1/conflicts`, `POST /v1/conflicts/{id}/resolve`.
- **Studio redesign** (monochrome token system, light/dark with persistence, Markdown + code blocks, copy, timestamps, grouped/searchable history, export menu, confirm dialog, toasts, accessible composer, responsive layout, Knowledge page with claims and conflicts). See `docs/STUDIO.md`.
- Evaluation: `evaluation/datasets/knowledge_integrity_v1.json` (10 cases) and six new metrics; `scripts/measure_performance.py`.
- Tests: knowledge-integrity acceptance, claim engine (both backends), API export/claims/isolation, regression guard, Studio pure-logic tests.

### Changed
- Reasoning reads only the knowledge basis (established + personal + premise facts); unestablished world claims no longer influence answers or produce "probably".
- World claims follow the user across conversations (scenario premises still do not).
- A world "correction" ("No, the capital is X") goes through the claim path instead of the learning engine, which would have rejected it.
- An elliptical follow-up that resolved to the same question twice is now answered once (pre-existing v0.0.0 defect).
- `MemoryEngine`/messages API: `limit=None` returns the whole conversation (export); the paged endpoint still caps at 500.
- Studio palette: orange accent removed.

### Known issues
See `docs/CAPABILITY_ASSESSMENT.md`. Unchanged evaluation failures from v0.0.0 (7 cases) remain; two parser limits found while writing the new cases are listed there.

## [v0.0.0] — initial foundation

First delivery. Everything listed was written in one build session; "verified" means exercised by the test suite described in `docs/TESTING.md`.

### Added
- Intelligence core (Python stdlib only; no ML, no external AI services): twelve engines — Input, Language Understanding (English rule-based), Context, Memory, Knowledge, Reasoning, Learning, Emotion/Sentiment, Planning/Goal, Personality, Response Generation, Evaluation/Confidence — and an orchestrator (`intelligence/app.py`).
- ACR (`acr/1.0`): typed, validated, serialisable, schema-versioned representation.
- Algorithms: partial order + CSP, exact rational arithmetic, BM25, string similarity, confidence combinators.
- Storage: table-spec-driven backends (in-memory, PostgreSQL), isolation by project/user, schema `0001`.
- API service (FastAPI): `/v1` endpoints, scrypt passwords, opaque hashed sessions, lockout, rate limiting, audit log. *HTTP layer not executed in the build sandbox.*
- AVOENIX Studio (Next.js): Milestone 1 (auth, chat, history, health/diagnostics, latency, errors); Milestones 2–4 partial read-only views. *Not built or run in the build sandbox.*
- Evaluation dataset (57 cases, 12 categories, dev/holdout split) and runner.
- Dockerfile, docker-compose, Railway and Vercel configuration, `migrate.py` startup migration; `.env.example` with placeholders only.

### Known issues
See `docs/CAPABILITY_ASSESSMENT.md` (weaknesses) and `evaluation/results/latest.json` (7 failing evaluation cases, left unadjusted).
