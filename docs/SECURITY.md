# Security notes (v0.0.1)

| Area | Implementation | Verified? |
|---|---|---|
| Passwords | scrypt (N=2^14, r=8, p=1, 16-byte salt), constant-time compare, timing equalisation for unknown accounts | tested |
| Sessions | 256-bit opaque token; only SHA-256 stored; expiry; revocation on logout; HttpOnly + Secure(prod) + SameSite cookie | token logic tested; cookie flags not tested in a browser |
| Brute force | per-account lockout (default 5 failures → 15 min), per-IP login rate limit; generic 401 | tested |
| Authorisation | all `/v1` routes except health/version/login require a session; evaluation run needs admin | logic tested |
| Isolation | scope derived from session; `ScopedRepo` enforces project/user filters; RLS policies in SQL (defence in depth) | app-level tested; RLS not tested |
| Input | body size cap, type checks, id regex, text length cap, parameterised SQL from a whitelisted spec | tested (logic) |
| Errors | unexpected exceptions → generic message + reference id; details only in logs | tested |
| Audit | `audit_log` rows for login/logout/failures/conversation/feedback/learning/evaluation; no secrets stored | tested |
| CORS | explicit origin allow-list, credentials on, `*` rejected at startup in production | config logic tested; middleware not run |
| Secrets | environment only; `.env.example` has placeholders; admin password is hashed at bootstrap and not re-applied | — |

## v0.0.1 review (what was reviewed and what was found)
| Area | Finding | Status |
|---|---|---|
| Export access control | `GET /v1/conversations/{id}/export` derives scope from the session; another user's conversation id returns 404 (test `test_export_is_denied_for_other_users`). Export is audited (`conversation.export`, format + count only, never content). | tested (logic) |
| Export output safety | Filenames are `[a-z0-9-]` only (test with header-injection title); `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`; content is data, never rendered server-side. | tested (filename logic); headers **not run** (FastAPI blocked) |
| Claims / conflicts endpoints | Same session scoping as other routes; ids validated by regex; `verification`/`status` validated against fixed sets; resolution is audited; cross-user resolve/history returns 404. | tested (logic) |
| SQL safety | Claim/conflict/revision tables are in the whitelisted table spec; all values are bound parameters; no string-built SQL was added. Migration `0002` is static SQL. | reviewed + applied to PostgreSQL 16 |
| Data isolation | Claims are per project/user; a peer's conflicting claim never creates a conflict for another user (test). | tested on memory + PostgreSQL |
| Studio rendering | Message text is rendered through a Markdown subset into React elements (no `innerHTML`); links limited to http/https/mailto; unsafe targets dropped (unit-tested). | parser tested; rendering **not run** |
| Studio theme script | One inline script (constant string, no user data) in `<head>`; a strict CSP without `unsafe-inline` would need a nonce. | **open** — document before adding CSP |
| Secrets | No credentials in source, tests, docs or the ZIP; `.env.example` placeholders only. | checked by scan at packaging |
| Rate limiting | New routes pass through the existing per-user middleware. Export of very large conversations is bounded only by conversation size. | **open** (no per-export size cap) |

Known gaps: rate limiting is in-process; no CSRF token (mitigated by SameSite and JSON-only endpoints behind a same-origin BFF — review before exposing the API cross-site); no MFA; no password reset; no dependency vulnerability scan was possible (`pip-audit`/`npm audit` need network); `api_keys` table is prepared but unused.
