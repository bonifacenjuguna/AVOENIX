# AVOENIX v0.0.1 — Algorithmic Intelligence System

*Algorithmic Intelligence, Engineered to Evolve.*

AVOENIX is **not** a language-model chatbot. It is a deterministic, inspectable system that parses English into a language-independent
representation (ACR), reasons over it with explicit algorithms, remembers and learns in controlled, reversible ways, and composes replies
from structured facts. **No neural networks, pretrained models, or external AI APIs are used anywhere.**

> **Status: v0.0.1 — Knowledge Integrity + Studio redesign on top of the v0.0.0 foundation; partially verified.** New in this release: user statements are stored as *claims* with provenance and a verification state and are never promoted to knowledge by being said (`docs/KNOWLEDGE_INTEGRITY.md`); Studio was redesigned (`docs/STUDIO.md`). See `docs/TESTING_REPORT.md` for what was and was not executed. Read `docs/CAPABILITY_ASSESSMENT.md` before relying on anything.

## What works (verified by tests in the build environment)
- "What is the capital of the USA?" → Washington, D.C.; if you then say "The capital of the USA is New York.", AVOENIX records that *you said it* (unverified, contradicted by established knowledge), keeps your statement retrievable, and keeps answering Washington, D.C.
- "John is older than Peter. Peter is older than David. Who is the youngest?" → David (with varied wording, follow-ups, contradictions).
- Exact arithmetic, simple taxonomy/location/attribute questions, user facts across conversations, honest "I don't know".
- Preference learning with read-back verification and revert; goal/step planning; emotion-aware tone; varied, repetition-aware replies.
- PostgreSQL persistence (tested against a real PostgreSQL 16 server through a non-atomic test adapter).

## What is NOT verified here
FastAPI HTTP layer, the Next.js Studio, Docker images, Railway/Vercel deployment and `psycopg` were **not executed** (network blocked in the build sandbox). See `docs/TESTING.md`.

## Layout
```
intelligence/        the intelligence core (stdlib only; independent of FastAPI)
  engines/           12 engines · representation/ ACR · algorithms/ · storage/ · app.py orchestrator
services/intelligence-api/   FastAPI service (app/core.py holds the testable logic; app/main.py is the HTTP mapping)
apps/studio/        AVOENIX Studio (Next.js + TypeScript + Tailwind)
database/schemas/   SQL schema 0001          evaluation/   dataset + results
docs/               architecture, engines, API, testing, deployment, security, capability assessment
```

## Quick start (core only, no dependencies)
```bash
python -m pytest                       # 162 passed / 37 skipped without PostgreSQL
python scripts/run_evaluation.py       # evaluation dataset → evaluation/results/latest.json
python - <<'PY'
from intelligence.app import Avoenix; from intelligence.core.types import Scope; from intelligence.storage import MemoryBackend
a = Avoenix(MemoryBackend()); print(a.process_turn(Scope("demo", "me"), "John is older than Peter. Peter is older than David. Who is the youngest?").response)
PY
```
Full stack: `cp .env.example .env`, fill placeholders, `docker compose up` (see `docs/DEPLOYMENT.md`; not verified here).

## Documents
`docs/ARCHITECTURE.md` · `docs/engines/` · `docs/API.md` · `docs/TESTING.md` · `docs/DEPLOYMENT.md` · `docs/SECURITY.md` · `docs/VERSIONING.md` · `docs/CAPABILITY_ASSESSMENT.md` · `CHANGELOG.md`
