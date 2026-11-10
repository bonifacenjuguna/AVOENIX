# Security notes (v0.0.0)

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

Known gaps: rate limiting is in-process; no CSRF token (mitigated by SameSite and JSON-only endpoints behind a same-origin BFF — review before exposing the API cross-site); no MFA; no password reset; no dependency vulnerability scan was possible (`pip-audit`/`npm audit` need network); `api_keys` table is prepared but unused.
