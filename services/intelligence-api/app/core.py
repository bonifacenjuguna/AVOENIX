"""Framework-independent API logic: authentication, authorisation, scoping, audit, endpoint handlers.

``ApiCore`` methods take plain values and return ``(http_status, body)``; the FastAPI layer (``main.py``) only maps HTTP to these calls.
Every scope used for intelligence calls is derived from the authenticated session — never from request data — so one user cannot
address another user's conversations, memory or knowledge.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from intelligence.app import Avoenix, AvoenixConfig
from intelligence.core.errors import AvoenixError, ConflictError, InputError, LearningRejected, NotFoundError, ScopeError
from intelligence.core.types import Scope
from intelligence.storage.backend import Backend

from .config import Settings
from .ratelimit import RateLimiter
from .security import burn_password_check, hash_password, hash_token, new_token, verify_password

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_STATUS = {InputError: 400, NotFoundError: 404, ConflictError: 409, ScopeError: 403, LearningRejected: 422}


class Principal:
    def __init__(self, user: dict, session_id: str):
        self.user, self.session_id = user, session_id

    @property
    def id(self) -> str:
        return self.user["id"]

    @property
    def is_admin(self) -> bool:
        return self.user["role"] == "admin"


class ApiCore:
    def __init__(self, backend: Backend, settings: Settings, engine: Avoenix | None = None, *, clock=None, dataset_path: str | None = None):
        self.backend, self.settings = backend, settings
        self.engine = engine or Avoenix(backend, AvoenixConfig())
        self.now = clock or (lambda: datetime.now(timezone.utc))
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self.login_limiter = RateLimiter(settings.login_rate_limit_per_minute)
        self.dataset_path = dataset_path
        self.started_at = self.now()

    # ---- helpers ---------------------------------------------------------------------------------------------------------------
    def _iso(self, dt: datetime | None = None) -> str:
        return (dt or self.now()).isoformat()

    @staticmethod
    def _parse(ts: Any) -> datetime | None:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    def scope_for(self, p: Principal) -> Scope:
        return Scope(self.settings.project_id, f"admin:{p.id}")

    def audit(self, action: str, *, actor: str | None = None, target_type: str | None = None, target_id: str | None = None, ip: str | None = None,
              details: dict | None = None) -> None:
        try:
            self.backend.insert("audit_log", {"at": self._iso(), "actor_id": actor, "actor_type": "user" if actor else "anonymous", "action": action,
                                              "target_type": target_type, "target_id": target_id, "project_id": self.settings.project_id,
                                              "details": details or {}, "ip": ip})
        except Exception:  # noqa: BLE001 - auditing must never take the request down; the failure is visible in health
            self.audit_failures = getattr(self, "audit_failures", 0) + 1

    def safe_error(self, exc: Exception) -> tuple[int, dict]:
        """Map exceptions to safe bodies: known errors keep their message; anything else is a generic 500 with a reference id."""
        if isinstance(exc, AvoenixError):
            for cls, status in _STATUS.items():
                if isinstance(exc, cls):
                    return status, {"error": exc.to_dict()}
            return 500, {"error": {"code": exc.code, "message": "internal error", "details": {}}}
        ref = uuid.uuid4().hex[:10]
        return 500, {"error": {"code": "internal_error", "message": "An internal error occurred.", "details": {"reference": ref}}}

    # ---- bootstrap -------------------------------------------------------------------------------------------------------------
    def bootstrap_admin(self) -> str:
        s = self.settings
        if not s.admin_email or not s.admin_password:
            return "no admin bootstrap configured (AVOENIX_ADMIN_EMAIL / AVOENIX_ADMIN_PASSWORD not set)"
        if not _EMAIL.match(s.admin_email):
            return "admin email invalid; bootstrap skipped"
        if any(u["email"].lower() == s.admin_email.lower() for u in self.backend.select("users", {})):
            return "admin already exists; password from environment is NOT re-applied"
        uid = "u_" + uuid.uuid4().hex[:16]
        self.backend.insert("users", {"id": uid, "email": s.admin_email, "password_hash": hash_password(s.admin_password), "role": "admin",
                                      "display_name": "Administrator", "is_active": True, "created_at": self._iso(), "last_login_at": None,
                                      "failed_logins": 0, "locked_until": None})
        if not self.backend.get("projects", {"id": s.project_id}):
            self.backend.insert("projects", {"id": s.project_id, "name": "AVOENIX Studio", "description": "Studio admin project", "status": "active",
                                             "owner_user_id": uid, "created_at": self._iso()})
        self.audit("admin.bootstrap", actor=uid, target_type="user", target_id=uid)
        return "admin created"

    # ---- authentication --------------------------------------------------------------------------------------------------------
    def login(self, email: str, password: str, *, ip: str | None = None, user_agent: str | None = None) -> tuple[int, dict, str | None]:
        ok, retry = self.login_limiter.allow(f"login:{ip or 'unknown'}")
        if not ok:
            self.audit("auth.login.rate_limited", ip=ip)
            return 429, {"error": {"code": "rate_limited", "message": "Too many login attempts.", "details": {"retry_after_s": round(retry)}}}, None
        if not isinstance(email, str) or not isinstance(password, str) or not email or not password or len(password) > 1024 or len(email) > 320:
            return 400, {"error": {"code": "invalid_input", "message": "email and password are required", "details": {}}}, None
        rows = [u for u in self.backend.select("users", {}) if u["email"].lower() == email.strip().lower()]
        user = rows[0] if rows else None
        generic = (401, {"error": {"code": "invalid_credentials", "message": "Invalid email or password.", "details": {}}}, None)
        if user is None:
            burn_password_check(password)
            self.audit("auth.login.failed", ip=ip, details={"reason": "unknown_account"})
            return generic
        locked = self._parse(user.get("locked_until"))
        if locked and locked > self.now():
            burn_password_check(password)
            self.audit("auth.login.locked", actor=user["id"], ip=ip)
            return generic                                           # same response: no account-state oracle
        if not user["is_active"] or not verify_password(password, user["password_hash"]):
            fails = int(user.get("failed_logins") or 0) + 1
            upd: dict = {"failed_logins": fails}
            if fails >= self.settings.max_failed_logins:
                upd = {"failed_logins": 0, "locked_until": self._iso(self.now() + timedelta(minutes=self.settings.lockout_minutes))}
            self.backend.update("users", {"id": user["id"]}, upd)
            self.audit("auth.login.failed", actor=user["id"], ip=ip, details={"failed_logins": fails})
            return generic
        token = new_token()
        sid = "s_" + uuid.uuid4().hex[:16]
        self.backend.insert("sessions", {"id": sid, "user_id": user["id"], "token_hash": hash_token(token), "created_at": self._iso(),
                                         "expires_at": self._iso(self.now() + timedelta(hours=self.settings.session_ttl_hours)), "revoked_at": None,
                                         "ip": ip, "user_agent": (user_agent or "")[:200]})
        self.backend.update("users", {"id": user["id"]}, {"failed_logins": 0, "locked_until": None, "last_login_at": self._iso()})
        self.audit("auth.login", actor=user["id"], target_type="session", target_id=sid, ip=ip)
        return 200, {"user": self._public_user(user), "expires_in_s": self.settings.session_ttl_hours * 3600}, token

    @staticmethod
    def _public_user(u: dict) -> dict:
        return {"id": u["id"], "email": u["email"], "role": u["role"], "display_name": u.get("display_name")}

    def authenticate(self, token: str | None) -> Principal | None:
        if not token or len(token) > 256:
            return None
        row = self.backend.get("sessions", {"token_hash": hash_token(token)})
        if not row or row.get("revoked_at"):
            return None
        exp = self._parse(row["expires_at"])
        if exp is None or exp <= self.now():
            return None
        user = self.backend.get("users", {"id": row["user_id"]})
        if not user or not user["is_active"]:
            return None
        return Principal(user, row["id"])

    def logout(self, p: Principal, ip: str | None = None) -> tuple[int, dict]:
        self.backend.update("sessions", {"id": p.session_id}, {"revoked_at": self._iso()})
        self.audit("auth.logout", actor=p.id, target_type="session", target_id=p.session_id, ip=ip)
        return 200, {"ok": True}

    def check_rate(self, p: Principal | None, ip: str | None) -> tuple[bool, float]:
        return self.limiter.allow(f"u:{p.id}" if p else f"ip:{ip or 'unknown'}")

    # ---- public / health -------------------------------------------------------------------------------------------------------
    def liveness(self) -> tuple[int, dict]:
        return 200, {"status": "alive", "version": self.engine.version_info()["platform"]}

    def readiness(self) -> tuple[int, dict]:
        ok, detail = self.backend.ping()
        return (200 if ok else 503), {"status": "ready" if ok else "not_ready", "storage": {"ok": ok, "detail": detail}}

    def version(self) -> tuple[int, dict]:
        return 200, self.engine.version_info()

    def health(self) -> tuple[int, dict]:
        h = self.engine.health()
        h["audit_write_failures"] = getattr(self, "audit_failures", 0)
        h["uptime_s"] = round((self.now() - self.started_at).total_seconds())
        return (200 if h["status"] != "failed" else 503), h

    # ---- conversations & chat --------------------------------------------------------------------------------------------------
    def create_conversation(self, p: Principal, title: str | None) -> tuple[int, dict]:
        if title is not None and (not isinstance(title, str) or len(title) > 200):
            raise InputError("title must be a string of at most 200 characters")
        c = self.engine.create_conversation(self.scope_for(p), title)
        self.audit("conversation.create", actor=p.id, target_type="conversation", target_id=c["id"])
        return 201, self._conv(c)

    @staticmethod
    def _conv(c: dict) -> dict:
        return {k: c.get(k) for k in ("id", "title", "archived", "created_at", "updated_at")}

    def list_conversations(self, p: Principal) -> tuple[int, dict]:
        return 200, {"conversations": [self._conv(c) for c in self.engine.list_conversations(self.scope_for(p))]}

    def messages(self, p: Principal, cid: str) -> tuple[int, dict]:
        self._id(cid)
        return 200, {"conversation_id": cid, "messages": [{k: m.get(k) for k in ("id", "role", "content", "turn_index", "latency_ms", "created_at")}
                                                         for m in self.engine.messages(self.scope_for(p), cid)]}

    def delete_conversation(self, p: Principal, cid: str) -> tuple[int, dict]:
        self._id(cid)
        self.engine.delete_conversation(self.scope_for(p), cid)
        self.audit("conversation.delete", actor=p.id, target_type="conversation", target_id=cid)
        return 200, {"deleted": True}

    def chat(self, p: Principal, text: Any, conversation_id: str | None, client_context: dict | None) -> tuple[int, dict]:
        if not isinstance(text, str):
            raise InputError("text must be a string")
        if conversation_id is not None:
            self._id(conversation_id)
        ctx = client_context if isinstance(client_context, dict) else None
        r = self.engine.process_turn(self.scope_for(p), text, conversation_id, client_context=ctx)
        return 200, r.to_dict()

    def trace(self, p: Principal, message_id: str) -> tuple[int, dict]:
        self._id(message_id)
        return 200, self.engine.get_trace(self.scope_for(p), message_id)

    # ---- inspection ------------------------------------------------------------------------------------------------------------
    def engines(self) -> tuple[int, dict]:
        return 200, {"engines": self.engine.engines_info()}

    def memory(self, p: Principal, query: str | None, limit: int = 20) -> tuple[int, dict]:
        s, limit = self.scope_for(p), max(1, min(int(limit), 100))
        items = self.engine.memory.recall(s, query, limit=limit, touch=False) if query else self.engine.memory.recent(s, limit=limit)
        return 200, {"items": items, "preferences": self.engine.memory.preferences(s)}

    def knowledge(self, p: Principal, query: str | None, limit: int = 20) -> tuple[int, dict]:
        s, limit = self.scope_for(p), max(1, min(int(limit), 100))
        if query:
            facts = [{**f.to_dict(), "score": round(sc, 3)} for f, sc in self.engine.knowledge.search(s, query, limit=limit)]
        else:
            facts = [f.to_dict() for f in self.engine.knowledge.list_facts(s, limit=limit, user_only=True)]
        return 200, {"facts": facts, "stats": self.engine.knowledge.stats(s)}

    def feedback(self, p: Principal, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict):
            raise InputError("body must be an object")
        rec = self.engine.learning.submit_feedback(self.scope_for(p), str(body.get("kind", "")), rating=body.get("rating"), comment=body.get("comment"),
                                                   message_id=body.get("message_id"), conversation_id=body.get("conversation_id"))
        self.audit("feedback.submit", actor=p.id, target_type="feedback", target_id=rec["id"])
        return 201, {"id": rec["id"], "status": rec["status"]}

    def learning_history(self, p: Principal) -> tuple[int, dict]:
        return 200, {"records": self.engine.learning.history(self.scope_for(p))}

    def learning_revert(self, p: Principal, record_id: str) -> tuple[int, dict]:
        self._id(record_id)
        rec = self.engine.learning.revert(self.scope_for(p), record_id, decided_by=p.id)
        self.audit("learning.revert", actor=p.id, target_type="learning_record", target_id=record_id)
        return 200, rec

    def evaluation_runs(self) -> tuple[int, dict]:
        return 200, {"runs": self.engine.evaluation.latest_runs(10)}

    def evaluation_run(self, p: Principal) -> tuple[int, dict]:
        if not p.is_admin:
            return 403, {"error": {"code": "forbidden", "message": "admin role required", "details": {}}}
        path = Path(self.dataset_path) if self.dataset_path else None
        if not path or not path.exists():
            return 503, {"error": {"code": "dataset_unavailable", "message": "evaluation dataset not found on this deployment", "details": {}}}
        cases = json.loads(path.read_text())["cases"]
        counter = {"n": 0}

        def respond(case: dict) -> list[dict]:
            counter["n"] += 1
            scope, cid, out = Scope("eval", f"eval:{uuid.uuid4().hex[:8]}:{counter['n']}"), None, []
            for t in case["turns"]:
                r = self.engine.process_turn(scope, t, cid)
                cid = r.conversation_id
                out.append({"response": r.response, "understanding": r.understanding, "reasoning_status": (r.response_meta or {}).get("reasoning_status"),
                            "emoji": (r.response_meta or {}).get("emoji"), "confidence": (r.confidence or {}).get("overall")})
            return out
        report = self.engine.evaluation.run_suite(cases, respond, label=path.stem, persist=True, environment={"backend": type(self.backend).__name__})
        self.audit("evaluation.run", actor=p.id, details={"passed": report["summary"]["overall"]["passed"], "total": report["summary"]["overall"]["total"]})
        return 200, {"summary": report["summary"], "failures": report["failures"], "caveats": report["caveats"]}

    def diagnostics(self, p: Principal) -> tuple[int, dict]:
        _, health = self.health()
        return 200, {"version": self.engine.version_info(), "environment": self.settings.environment,
                     "storage": health["storage"], "engines": [{"key": e["key"], "status": e["status"], "detail": e["detail"], "metrics": e["metrics"]} for e in health["engines"]],
                     "uptime_s": health["uptime_s"], "audit_write_failures": health["audit_write_failures"],
                     "implemented_milestones": {"1": "implemented", "2": "partial (memory/knowledge inspection, read-only)", "3": "partial (learning history, revert)",
                                                "4": "partial (evaluation runner)", "5": "not implemented"}}

    def _id(self, v: str) -> None:
        if not isinstance(v, str) or not _ID.match(v):
            raise InputError("invalid identifier")
