# Changelog

All notable changes to AVOENIX are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [Semantic Versioning](https://semver.org/) as described in `docs/VERSIONING.md`.

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
