# Testing (v0.0.1)

Labels: **PASSED** · **FAILED** · **SKIPPED** (test chose not to run) · **BLOCKED BY ENVIRONMENT** (could not be run here) · **NOT TESTED**. Mocks and test doubles are never presented as proof that a real service works. Full per-item results: `docs/TESTING_REPORT.md`.

## Executed in the build sandbox
| Suite | Command | Result |
|---|---|---|
| Whole suite, no database | `python -m pytest tests services` | 196 PASSED, 47 SKIPPED (PostgreSQL-parametrised cases need `AVOENIX_TEST_PG`) |
| Whole suite, real PostgreSQL 16 | `AVOENIX_TEST_PG=127.0.0.1:54329:avoenix_test python -m pytest tests services` | 243 PASSED, 0 skipped, 0 failed |
| Studio pure logic (Node 22) | `cd apps/studio && node --experimental-strip-types --test tests/lib.test.ts` | 10 PASSED |
| Core evaluation | `python scripts/run_evaluation.py` | 50/57 (dev 30/32, holdout 20/25): the same 7 cases fail as in v0.0.0 |
| Knowledge-integrity evaluation | `python scripts/run_evaluation.py --dataset evaluation/datasets/knowledge_integrity_v1.json --out evaluation/results/knowledge_integrity.json` | 10/10 (see disclosure in `docs/KNOWLEDGE_INTEGRITY.md`) |
| Latency measurement | `python scripts/measure_performance.py` | in `evaluation/results/performance.json` (memory backend; p50 3.6–8.5 ms per turn on this machine; **not** a capacity claim) |
| Migration `0002` | psql on PostgreSQL 16 | applied twice (idempotent), rolled back, re-applied on a scratch database: PASSED |
| Studio TypeScript | `tsc` syntax pass | 0 syntax errors; full type-check **BLOCKED BY ENVIRONMENT** |

Contents: `tests/unit`, `tests/integration` (backend contract on both backends, knowledge, **claims**, memory, personality, planning, learning), `tests/acceptance` (end-to-end turns, **knowledge integrity**, **v0.0.1 regression guard**: age-ordering, name recall, Nairobi capital, contextual follow-up, persistence across restart, premise contradiction), `services/intelligence-api/tests` (auth, lockout, sessions, rate limit, scoping, audit, safe errors, config, **export, claims, conflicts, isolation, migration runner**).

### PostgreSQL test caveat
PostgreSQL is exercised through a `psql`-subprocess adapter (`tests/support/psql_database.py`) because `psycopg` could not be installed. Each statement runs on its own connection, so **transaction atomicity is not tested**; `PsycopgDatabase` / `PostgresBackend` transactions are NOT TESTED. RLS policies are NOT TESTED. The PostgreSQL server must be running before the PG run: a run with `AVOENIX_TEST_PG` set but the server down reports the PG cases as SKIPPED, not PASSED.

## NOT executed (BLOCKED BY ENVIRONMENT: package installation and Docker unavailable)
FastAPI routes/middleware/CORS/cookies, including the new export/claims/conflicts routes (`app/main.py` only `py_compile`d) · `migrate.py` (psycopg; only its file-ordering logic is tested) · Docker images and compose · Next.js build and runtime · Railway/Vercel deployment · browser behaviour of Studio (rendering, theme persistence, export download, responsive layout, accessibility audit) · frontend component tests · load/performance beyond in-process timings.

## Evaluation dataset (`evaluation/datasets/core_v0.json`, unchanged from v0.0.0)
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
`createdb avoenix_test && psql avoenix_test -f database/schemas/0001_initial.sql -f database/schemas/0002_knowledge_integrity.sql`, then set `AVOENIX_TEST_PG=host:port:dbname[:user]` (needs `psql`/`pg_isready` on PATH).
