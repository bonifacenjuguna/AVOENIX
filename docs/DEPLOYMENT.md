# Deployment (v0.0.0) — **instructions only; none of this was executed by the author**

## Topology
Vercel (Studio) → same-origin `/api/*` BFF → Railway (FastAPI) → PostgreSQL (Railway plugin or any PostgreSQL ≥ 14).

## 1. Database
Provision PostgreSQL; set `DATABASE_URL` on the API service. Migrations: `alembic -c services/intelligence-api/alembic.ini upgrade head` (the Railway `preDeployCommand` runs this). Alternative: `psql "$DATABASE_URL" -f database/schemas/0001_initial.sql` (idempotent `CREATE … IF NOT EXISTS`). v0.0.0 has no downgrade; back up first.

## 2. API on Railway
Root of the repository, builder `DOCKERFILE` (`railway.json`). Variables (see `.env.example`): `AVOENIX_ENV=production`, `DATABASE_URL`, `AVOENIX_CORS_ORIGINS=https://<studio-domain>`, `AVOENIX_ADMIN_EMAIL`, `AVOENIX_ADMIN_PASSWORD` (≥ 12 chars; remove after first boot), `AVOENIX_COOKIE_SECURE=true`. Production startup fails fast on a missing `DATABASE_URL`/CORS list. Health check path: `/readyz`.

## 3. Studio on Vercel
Project root `apps/studio`; env `AVOENIX_API_URL=https://<railway-domain>` (server-side only). Build `next build`.

## 4. Local stack
`cp .env.example .env`; set `AVOENIX_ADMIN_PASSWORD` and `POSTGRES_PASSWORD`; `docker compose up --build` → Studio http://localhost:3000, API http://localhost:8000/docs. Apply migrations once: `docker compose exec api alembic -c services/intelligence-api/alembic.ini upgrade head`.

## 5. Verify after deploy
Follow "Manual acceptance" in `docs/TESTING.md`. Report any failure — the steps above are untested.

## Operational notes
Single process assumed (in-memory rate limiter). The knowledge seed runs idempotently on first start (may take several seconds on a cold PostgreSQL). Back up PostgreSQL regularly; conversations and memories are personal data.
