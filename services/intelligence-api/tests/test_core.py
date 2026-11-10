"""Tests of the framework-independent API core (auth, scoping, rate limiting, audit, safe errors). Memory backend; no HTTP.
The FastAPI mapping in app/main.py is NOT covered here (BLOCKED BY ENVIRONMENT: fastapi not installable in the build sandbox)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "services" / "intelligence-api")]

from app.config import Settings  # noqa: E402
from app.core import ApiCore  # noqa: E402
from app.ratelimit import RateLimiter  # noqa: E402
from app.security import hash_password, hash_token, verify_password  # noqa: E402
from intelligence.core.errors import InputError  # noqa: E402
from intelligence.storage import MemoryBackend  # noqa: E402

PW = "correct horse battery"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture()
def api():
    clock = Clock()
    s = Settings(admin_email="admin@example.test", admin_password=PW, max_failed_logins=3, login_rate_limit_per_minute=50)
    core = ApiCore(MemoryBackend(), s, clock=clock)
    core.bootstrap_admin()
    core.clock = clock
    return core


def login(core, pw=PW, email="admin@example.test", ip="1.1.1.1"):
    return core.login(email, pw, ip=ip)


def test_password_hash_roundtrip_and_salt():
    h1, h2 = hash_password("abc"), hash_password("abc")
    assert h1 != h2 and verify_password("abc", h1) and not verify_password("abd", h1) and "abc" not in h1
    assert not verify_password("abc", "garbage")


def test_bootstrap_idempotent_and_no_plaintext(api):
    assert "already exists" in api.bootstrap_admin()
    row = api.backend.select("users", {})[0]
    assert PW not in str(row) and row["password_hash"].startswith("scrypt$")


def test_login_success_stores_only_token_hash(api):
    status, body, token = login(api)
    assert status == 200 and token and body["user"]["role"] == "admin"
    sess = api.backend.select("sessions", {})[0]
    assert sess["token_hash"] == hash_token(token) and token not in str(sess)
    assert api.authenticate(token).user["email"] == "admin@example.test"


def test_login_failures_are_generic(api):
    a, b = login(api, pw="wrong-password"), login(api, email="nobody@example.test")
    assert a[0] == b[0] == 401 and a[1] == b[1] and a[2] is None


def test_lockout_after_repeated_failures(api):
    for _ in range(3):
        login(api, pw="bad-password-x")
    status, _, token = login(api)                      # correct password but locked
    assert status == 401 and token is None
    api.now = lambda: api.clock.t + timedelta(minutes=16)
    assert login(api)[0] == 200


def test_session_expiry_and_logout(api):
    _, _, token = login(api)
    p = api.authenticate(token)
    api.now = lambda: api.clock.t + timedelta(hours=13)
    assert api.authenticate(token) is None
    api.now = lambda: api.clock.t
    assert api.authenticate(token) is not None
    api.logout(p)
    assert api.authenticate(token) is None


def test_invalid_tokens_rejected(api):
    assert api.authenticate(None) is None and api.authenticate("x" * 300) is None and api.authenticate("nope") is None


def test_audit_records_login_events(api):
    login(api, pw="bad-password-x")
    login(api)
    actions = [r["action"] for r in api.backend.select("audit_log", {})]
    assert {"admin.bootstrap", "auth.login.failed", "auth.login"} <= set(actions)
    assert PW not in str(api.backend.select("audit_log", {}))


def test_login_rate_limit():
    s = Settings(admin_email="a@example.test", admin_password=PW, login_rate_limit_per_minute=3)
    core = ApiCore(MemoryBackend(), s)
    core.bootstrap_admin()
    codes = [core.login("a@example.test", "bad-password-x", ip="9.9.9.9")[0] for _ in range(5)]
    assert codes[:3] == [401] * 3 and codes[3:] == [429, 429]


def test_rate_limiter_window():
    t = {"v": 0.0}
    rl = RateLimiter(2, 10, clock=lambda: t["v"])
    assert rl.allow("k")[0] and rl.allow("k")[0] and not rl.allow("k")[0]
    t["v"] = 11
    assert rl.allow("k")[0]


def test_chat_roundtrip_and_conversation_listing(api):
    p = api.authenticate(login(api)[2])
    s, body = api.chat(p, "John is older than Peter. Peter is older than David. Who is the youngest?", None, None)
    assert s == 200 and "David" in body["response"]
    cid = body["conversation_id"]
    assert [c["id"] for c in api.list_conversations(p)[1]["conversations"]] == [cid]
    msgs = api.messages(p, cid)[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert api.trace(p, msgs[1]["id"])[0] == 200


def test_isolation_between_admin_users(api):
    api.backend.insert("users", {"id": "u_second", "email": "b@example.test", "password_hash": hash_password(PW), "role": "admin", "display_name": "B",
                                 "is_active": True, "created_at": api._iso(), "last_login_at": None, "failed_logins": 0, "locked_until": None})
    p1 = api.authenticate(login(api)[2])
    p2 = api.authenticate(login(api, email="b@example.test")[2])
    _, body = api.chat(p1, "My name is Alex.", None, None)
    assert api.list_conversations(p2)[1]["conversations"] == []
    from intelligence.core.errors import NotFoundError
    with pytest.raises(NotFoundError):
        api.messages(p2, body["conversation_id"])
    assert "Alex" not in api.chat(p2, "What is my name?", None, None)[1]["response"]


def test_input_validation_and_safe_errors(api):
    p = api.authenticate(login(api)[2])
    with pytest.raises(InputError):
        api.chat(p, 123, None, None)                                # type: ignore[arg-type]
    with pytest.raises(InputError):
        api.messages(p, "../../etc/passwd")
    s, b = api.safe_error(InputError("bad"))
    assert s == 400 and b["error"]["code"] == "invalid_input"
    s, b = api.safe_error(RuntimeError("secret connection string postgres://u:p@h/db"))
    assert s == 500 and "secret" not in str(b) and "reference" in b["error"]["details"]


def test_oversized_text_is_rejected_by_engine(api):
    p = api.authenticate(login(api)[2])
    s, b = api.chat(p, "a" * 50_000, None, None)
    assert b["status"] == "error"


def test_production_config_validation():
    assert Settings(environment="production").problems()
    ok = Settings(environment="production", database_url="postgresql://x", cors_origins=["https://studio.example"])
    assert ok.problems() == []
    assert Settings(environment="production", database_url="x", cors_origins=["*"]).problems()
    assert Settings(admin_password="short").problems()


def test_diagnostics_and_health_are_real(api):
    p = api.authenticate(login(api)[2])
    s, d = api.diagnostics(p)
    assert s == 200 and len(d["engines"]) == 12 and d["version"]["platform"] == "v0.0.0"
    assert api.readiness()[0] == 200


def test_evaluation_run_requires_dataset_and_reports(api, tmp_path):
    p = api.authenticate(login(api)[2])
    assert api.evaluation_run(p)[0] == 503
    api.dataset_path = str(ROOT / "evaluation/datasets/core_v0.json")
    s, body = api.evaluation_run(p)
    assert s == 200 and body["summary"]["overall"]["total"] >= 50
    assert api.evaluation_runs()[1]["runs"]
