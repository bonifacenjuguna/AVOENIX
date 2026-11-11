# HTTP API v1 (platform v0.0.1)

Base path `/v1`. JSON only. Authentication: HttpOnly session cookie `avoenix_session` (set by `POST /v1/auth/login`). Errors: `{"error": {"code", "message", "details"}}`; unexpected errors return a generic message with a `reference` id (details are logged server-side only). **Not executed against a running FastAPI server in the build sandbox**; the logic behind each route is tested in `services/intelligence-api/tests/test_core.py`.

| Method & path | Auth | Purpose |
|---|---|---|
| GET `/healthz` · `/readyz` | no | liveness · readiness (storage ping) |
| GET `/v1/version` | no | platform / api / acr / db schema versions |
| POST `/v1/auth/login` `{email,password}` | no | create session (rate limited, lockout) |
| POST `/v1/auth/logout` · GET `/v1/auth/me` | yes | end session · current user |
| GET `/v1/health` · `/v1/engines` · `/v1/diagnostics` | yes | engine self-checks, metadata, measured metrics |
| POST `/v1/conversations` · GET `/v1/conversations` | yes | create · list |
| GET `/v1/conversations/{id}/messages` · DELETE `/v1/conversations/{id}` | yes | history · delete |
| POST `/v1/chat` `{text, conversation_id?, client_context?}` | yes | process one turn; returns response, understanding, reasoning, confidence, trace, timings |
| GET `/v1/messages/{id}/trace` | yes | stored trace for an assistant message |
| GET `/v1/memory?q=` · GET `/v1/knowledge?q=` | yes | read-only inspection (own scope) |
| POST `/v1/feedback` | yes | rating/correction/report/comment |
| GET `/v1/learning/history` · POST `/v1/learning/{id}/revert` | yes | learning records · revert |
| GET `/v1/evaluation/runs` · POST `/v1/evaluation/run` | yes (run: admin) | stored runs · run bundled dataset |

### Added in v0.0.1 (all additive; no existing route, request or response field was removed or renamed)
| Method & path | Purpose |
|---|---|
| GET `/v1/conversations/{id}/export?format=json\|md\|txt` | Download the **complete** conversation (not limited to the 500-message page of `/messages`). `Content-Disposition: attachment; filename="<title>-<id8>-<date>.<ext>"`, `X-Message-Count`. 400 on bad format, 404 for unknown/foreign ids. JSON schema `avoenix.conversation/1`. |
| GET `/v1/claims?verification=&subject=&limit=` | Claims (`claim/1.0`) with provenance, verification, assessment. |
| GET `/v1/claims/{id}/history` | The claim, its revisions (previous/updated snapshots, reason) and its conflicts. |
| GET `/v1/conflicts?status=open\|resolved` | Preserved conflicts between claims/knowledge. |
| POST `/v1/conflicts/{id}/resolve` `{resolution, winner?, note?}` | `manual_choice` (needs `winner`) or `dismissed`; audited; history kept. |

Response additions (new optional fields only): `knowledge` facts and `memory.stored_facts` carry `provenance`, `claim_type`, `verification`, `assessment`, `memory_id`; `confidence.factual_support`; reasoning conclusion status `unverified_claim`; response plan message types `claim_recorded`, `claim_answer`.

**Behaviour change (not a schema change):** a statement about the world that conflicts with established knowledge is now *recorded as a contradicted claim* and answered with the established fact, where v0.0.0 replied "I'll remember that" and later hedged ("probably"). Clients that parse the reply text are unaffected structurally.

Limits: body ≤ `AVOENIX_MAX_BODY_BYTES` (64 kB), text ≤ engine `max_input_chars`, per-user rate limit (default 60/min), login limit per IP (default 10/min). Rate limits are per process.
