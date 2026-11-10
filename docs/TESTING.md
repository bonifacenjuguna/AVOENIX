# Testing (v0.0.0)

Labels: **PASSED** · **FAILED** · **SKIPPED** (test chose not to run) · **BLOCKED BY ENVIRONMENT** (could not be run here) · **NOT TESTED**. Mocks and test doubles are never presented as proof that a real service works.

## Executed in the build sandbox
| Suite | Command | Result |
|---|---|---|
| Whole suite, no database | `python -m pytest` | 162 PASSED, 37 SKIPPED (PostgreSQL-parametrised cases: BLOCKED BY ENVIRONMENT without `AVOENIX_TEST_PG`) |
| Whole suite, real PostgreSQL 16 | `AVOENIX_TEST_PG=127.0.0.1:54329:avoenix_test python -m pytest` | 199 PASSED, 0 failed |
| Evaluation dataset | `python scripts/run_evaluation.py` | 50/57 (dev 30/32, holdout 20/25); 7 FAILED cases reported below |
| Studio TypeScript | `tsc --noEmit` | syntax-clean (0 TS1xxx errors); full type-check **BLOCKED BY ENVIRONMENT** (react/next types not installable) |

Contents: `tests/unit` (ACR, algorithms, reasoning, emotion, response, evaluation), `tests/integration` (backend contract on both backends, knowledge, memory, personality, planning, learning), `tests/acceptance` (end-to-end turns), `services/intelligence-api/tests` (auth, lockout, sessions, rate limit, scoping, audit, safe errors, config validation, evaluation endpoint logic).

### PostgreSQL test caveat
PostgreSQL was exercised through a `psql`-subprocess adapter (`tests/support/psql_database.py`) because `psycopg` could not be installed. Each statement runs on its own connection, so **transaction atomicity is not tested**; `PsycopgDatabase` and `PostgresBackend` transactions are NOT TESTED. RLS policies are NOT TESTED (no non-owner role).

## NOT executed (BLOCKED BY ENVIRONMENT: package installation and Docker unavailable)
FastAPI routes/middleware/CORS/cookies (`app/main.py` only `py_compile`d) · Alembic migration · Docker images and compose · Next.js build and runtime · Railway/Vercel deployment · browser behaviour of Studio · load/performance beyond the in-process timings in the evaluation report.

## Evaluation dataset (`evaluation/datasets/core_v0.json`)
57 developer-authored, differently worded cases in 12 categories; `holdout` cases were written with the dev cases and **not used to tune behaviour**. Targets are development goals only.

**Disclosure:** the runner is not seeded, so reply wording varies between runs. The first runs flagged `kn-03` because its regex accepted only "yes" while the system correctly answered "Correct — dogs are mammals."; I widened the accepted *correct* phrasings for yes/no cases (a checker fix, not a behaviour change). The 7 failures below were not touched. After that change 6 consecutive runs gave 50/57; wording-dependent checks can still flip a case in other runs.

| Metric | Result on this dataset | Target | Note |
|---|---|---|---|
| intent/task classification | 24/27 = 88.9% | ≥ 85% | small sample; not a general claim |
| memory retrieval | 3/5 = 60% | ≥ 90% | **below target** |
| deterministic reasoning | 21/23 = 91.3% | ≥ 90% | small sample |

Failing cases (left as is): `multi-05` (two-entity "who is youngest" answered from closed-world assumption rather than reported underdetermined — a design disagreement), `kn-04` ("Tell me the capital of Japan" unsupported phrasing), `mem-02` ("I'm called Priya" not parsed as name), `mem-04` ("Who am I?" unsupported), `ctx-03` ("What about the oldest?" second-level ellipsis), `lrn-02` ("Keep your answers short" read as an action request), `lrn-03` ("Can you be more formal?" read as a factual question). Confidence calibration was measured by the evaluation engine but the sample is too small to claim calibration.

## Manual acceptance (to run after deployment)
1. `GET /readyz` → 200. 2. Sign in to Studio with the bootstrap admin. 3. Send the youngest-person example; expect "David". 4. Health page shows 12 engines, all `ok`. 5. Restart the API; conversation list persists (requires `DATABASE_URL`). 6. Sign out; `/v1/auth/me` → 401.

## Local database setup
`createdb avoenix_test && psql avoenix_test -f database/schemas/0001_initial.sql`, then set `AVOENIX_TEST_PG=host:port:dbname[:user]` (needs `psql`/`pg_isready` on PATH).
