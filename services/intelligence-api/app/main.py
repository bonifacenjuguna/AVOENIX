"""FastAPI application (HTTP layer only). All logic is in ``core.ApiCore``.

BLOCKED BY ENVIRONMENT in the build sandbox: fastapi/uvicorn could not be installed, so this module has been syntax-checked
(py_compile) but NOT executed. See docs/TESTING.md.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:                       # the intelligence package lives at the repository root
    sys.path.insert(0, str(ROOT))

from intelligence.storage import MemoryBackend  # noqa: E402

from .config import Settings  # noqa: E402
from .core import ApiCore, Principal  # noqa: E402

log = logging.getLogger("avoenix.api")
COOKIE = "avoenix_session"


def build_backend(settings: Settings):
    if settings.database_url:
        from intelligence.storage.postgres_backend import PostgresBackend, PsycopgDatabase
        return PostgresBackend(PsycopgDatabase(settings.database_url))
    return MemoryBackend()


def create_app(settings: Settings | None = None, backend: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()
    problems = settings.problems()
    if problems:
        raise RuntimeError("invalid configuration: " + "; ".join(problems))
    backend = backend or build_backend(settings)
    core = ApiCore(backend, settings, dataset_path=os.environ.get("AVOENIX_EVAL_DATASET", str(ROOT / "evaluation/datasets/core_v0.json")))
    log.info("admin bootstrap: %s", core.bootstrap_admin())
    app = FastAPI(title="AVOENIX Intelligence API", version=core.engine.version_info()["platform"], docs_url=None if settings.environment == "production" else "/docs",
                  redoc_url=None, openapi_url=None if settings.environment == "production" else "/openapi.json")
    app.state.core = core
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Content-Type"], max_age=600)

    def ip_of(request: Request) -> str | None:
        fwd = request.headers.get("x-forwarded-for")            # Railway terminates TLS and sets this; first hop is the client
        return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None))

    def reply(status: int, body: dict, headers: dict | None = None) -> JSONResponse:
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **(headers or {})})

    @app.middleware("http")
    async def guard(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_body_bytes:
            return reply(413, {"error": {"code": "payload_too_large", "message": "Request body too large.", "details": {}}})
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            status, body = core.safe_error(exc)
            log.exception("unhandled error (reference %s)", body["error"].get("details", {}).get("reference"))
            return reply(status, body)

    def auth(request: Request) -> Principal:
        p = core.authenticate(request.cookies.get(COOKIE))
        ok, retry = core.check_rate(p, ip_of(request))
        if not ok:
            raise _HttpError(429, {"error": {"code": "rate_limited", "message": "Too many requests.", "details": {"retry_after_s": round(retry)}}})
        if p is None:
            raise _HttpError(401, {"error": {"code": "unauthenticated", "message": "Sign in required.", "details": {}}})
        return p

    class _HttpError(Exception):
        def __init__(self, status: int, body: dict):
            self.status, self.body = status, body

    @app.exception_handler(_HttpError)
    async def _http_error(_: Request, exc: _HttpError):
        return reply(exc.status, exc.body)

    async def body_of(request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def run(fn, *a, **kw) -> JSONResponse:
        try:
            status, body = fn(*a, **kw)
            return reply(status, body)
        except Exception as exc:  # noqa: BLE001
            status, body = core.safe_error(exc)
            if status >= 500:
                log.exception("request failed (reference %s)", body["error"].get("details", {}).get("reference"))
            return reply(status, body)

    # ---- public ----
    @app.get("/healthz")
    def healthz():
        return run(core.liveness)

    @app.get("/readyz")
    def readyz():
        return run(core.readiness)

    @app.get("/v1/version")
    def version():
        return run(core.version)

    # ---- auth ----
    @app.post("/v1/auth/login")
    async def login(request: Request):
        b = await body_of(request)
        status, body, token = core.login(b.get("email"), b.get("password"), ip=ip_of(request), user_agent=request.headers.get("user-agent"))
        resp = reply(status, body)
        if token:
            resp.set_cookie(COOKIE, token, max_age=settings.session_ttl_hours * 3600, httponly=True, secure=settings.cookie_secure, samesite="none" if settings.cookie_secure else "lax", path="/")
        return resp

    @app.post("/v1/auth/logout")
    def logout(request: Request, p: Principal = Depends(auth)):
        status, body = core.logout(p, ip_of(request))
        resp = reply(status, body)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/v1/auth/me")
    def me(p: Principal = Depends(auth)):
        return reply(200, {"user": core._public_user(p.user)})

    # ---- diagnostics & inspection ----
    @app.get("/v1/health")
    def health(p: Principal = Depends(auth)):
        return run(core.health)

    @app.get("/v1/engines")
    def engines(p: Principal = Depends(auth)):
        return run(core.engines)

    @app.get("/v1/diagnostics")
    def diagnostics(p: Principal = Depends(auth)):
        return run(core.diagnostics, p)

    # ---- conversations & chat ----
    @app.post("/v1/conversations")
    async def create_conversation(request: Request, p: Principal = Depends(auth)):
        b = await body_of(request)
        return run(core.create_conversation, p, b.get("title"))

    @app.get("/v1/conversations")
    def list_conversations(p: Principal = Depends(auth)):
        return run(core.list_conversations, p)

    @app.get("/v1/conversations/{cid}/messages")
    def messages(cid: str, p: Principal = Depends(auth)):
        return run(core.messages, p, cid)

    @app.delete("/v1/conversations/{cid}")
    def delete_conversation(cid: str, p: Principal = Depends(auth)):
        return run(core.delete_conversation, p, cid)

    @app.post("/v1/chat")
    async def chat(request: Request, p: Principal = Depends(auth)):
        b = await body_of(request)
        return run(core.chat, p, b.get("text"), b.get("conversation_id"), b.get("client_context"))

    @app.get("/v1/messages/{mid}/trace")
    def trace(mid: str, p: Principal = Depends(auth)):
        return run(core.trace, p, mid)

    # ---- milestones 2-4 (read-mostly) ----
    @app.get("/v1/memory")
    def memory(q: str | None = None, limit: int = 20, p: Principal = Depends(auth)):
        return run(core.memory, p, q, limit)

    @app.get("/v1/knowledge")
    def knowledge(q: str | None = None, limit: int = 20, p: Principal = Depends(auth)):
        return run(core.knowledge, p, q, limit)

    @app.post("/v1/feedback")
    async def feedback(request: Request, p: Principal = Depends(auth)):
        return run(core.feedback, p, await body_of(request))

    @app.get("/v1/learning/history")
    def learning_history(p: Principal = Depends(auth)):
        return run(core.learning_history, p)

    @app.post("/v1/learning/{rid}/revert")
    def learning_revert(rid: str, p: Principal = Depends(auth)):
        return run(core.learning_revert, p, rid)

    @app.get("/v1/evaluation/runs")
    def evaluation_runs(p: Principal = Depends(auth)):
        return run(core.evaluation_runs)

    @app.post("/v1/evaluation/run")
    def evaluation_run(p: Principal = Depends(auth)):
        return run(core.evaluation_run, p)

    return app


app = None  # created lazily by uvicorn factory: `uvicorn app.main:create_app --factory`
