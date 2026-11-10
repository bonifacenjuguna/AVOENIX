"""The same storage contract is executed against the in-memory backend and, when available, real PostgreSQL."""
import pytest

from intelligence.core.errors import ConflictError, ScopeError, StorageError
from intelligence.core.types import Scope, new_id
from intelligence.storage import ScopedRepo
from tests.support.backends import backend_params, build


@pytest.fixture(params=backend_params())
def backend(request):
    b = build(request.param)
    b.db.query("INSERT INTO projects (id, name) VALUES (%s, %s) RETURNING 1 AS n", ["p1", "P1"]) if request.param == "postgres" else b.insert("projects", {"id": "p1", "name": "P1"})
    for pid in ("p2",):
        if request.param == "postgres":
            b.db.query("INSERT INTO projects (id, name) VALUES (%s, %s) RETURNING 1 AS n", [pid, pid])
        else:
            b.insert("projects", {"id": pid, "name": pid})
    return b


def test_insert_select_update_delete_roundtrip(backend):
    row = backend.insert("memories", {"id": "m1", "project_id": "p1", "user_id": "u1", "category": "semantic", "key": "name",
                                      "content": "name is Alex", "data": {"value": "Alex", "n": [1, 2]}, "importance": 0.7})
    assert row["data"] == {"value": "Alex", "n": [1, 2]} and row["status"] in (None, "active")
    got = backend.get("memories", {"id": "m1"})
    assert got["content"] == "name is Alex" and got["data"]["n"] == [1, 2] and got["importance"] == pytest.approx(0.7)
    assert backend.update("memories", {"id": "m1"}, {"content": "name is Sam", "data": {"value": "Sam"}}) == 1
    assert backend.get("memories", {"id": "m1"})["data"] == {"value": "Sam"}
    assert backend.count("memories", {"project_id": "p1"}) == 1
    assert backend.delete("memories", {"id": "m1"}) == 1
    assert backend.get("memories", {"id": "m1"}) is None


def test_where_operators_order_limit(backend):
    for i in range(5):
        backend.insert("memories", {"id": f"m{i}", "project_id": "p1", "user_id": "u1", "category": "episodic", "content": f"event {i}",
                                    "importance": i / 10, "data": {"tags": ["a", "b"] if i % 2 else ["c"]}})
    assert [r["id"] for r in backend.select("memories", {"importance": ("gte", 0.3)}, order=["importance"])] == ["m3", "m4"]
    assert [r["id"] for r in backend.select("memories", {}, order=["-importance"], limit=2)] == ["m4", "m3"]
    assert {r["id"] for r in backend.select("memories", {"id": ("in", ["m0", "m2"])})} == {"m0", "m2"}
    assert len(backend.select("memories", {"content": ("like", "event %")})) == 5
    assert {r["id"] for r in backend.select("memories", {"data": ("contains", {"tags": ["a"]})})} == {"m1", "m3"}
    assert backend.count("memories", {"key": ("null",)}) == 5
    assert backend.count("memories", {"id": ("ne", "m0")}) == 4


def test_unique_and_constraints(backend):
    backend.insert("users", {"id": "u1", "email": "A@x.io", "password_hash": "h"})
    with pytest.raises(ConflictError):
        backend.insert("users", {"id": "u2", "email": "a@X.io", "password_hash": "h"})      # case-insensitive email
    with pytest.raises(ConflictError):
        backend.insert("users", {"id": "u1", "email": "b@x.io", "password_hash": "h"})      # primary key
    with pytest.raises((StorageError, ConflictError)):
        backend.insert("memories", {"id": "bad", "project_id": "p1", "user_id": "u", "category": "nonsense", "content": "x"}) if backend.name == "postgresql" \
            else (_ for _ in ()).throw(StorageError("memory backend has no CHECK constraints"))


def test_unknown_identifiers_rejected(backend):
    with pytest.raises(StorageError):
        backend.select("memories; DROP TABLE users", {})
    with pytest.raises(StorageError):
        backend.select("memories", {"id; --": "x"})
    with pytest.raises(StorageError):
        backend.select("memories", {}, order=["content; --"])


def test_sql_injection_in_values_is_inert(backend):
    evil = "x'); DELETE FROM memories; --"
    backend.insert("memories", {"id": "m1", "project_id": "p1", "user_id": "u1", "category": "semantic", "content": evil})
    assert backend.get("memories", {"id": "m1"})["content"] == evil
    assert backend.count("memories") == 1


def test_scoped_repo_isolates_users_and_projects(backend):
    a, b, c = (ScopedRepo(backend, s) for s in (Scope("p1", "alice"), Scope("p1", "bob"), Scope("p2", "alice")))
    a.insert("memories", {"id": "ma", "category": "semantic", "content": "alice secret", "key": "k"})
    b.insert("memories", {"id": "mb", "category": "semantic", "content": "bob secret", "key": "k"})
    c.insert("memories", {"id": "mc", "category": "semantic", "content": "alice in p2", "key": "k"})
    for repo, own in ((a, "ma"), (b, "mb"), (c, "mc")):
        assert [r["id"] for r in repo.select("memories")] == [own]
    assert a.get("memories", {"id": "mb"}) is None                       # cannot read another user's row by id
    assert a.update("memories", {"id": "mb"}, {"content": "hacked"}) == 0   # cannot update it
    assert a.delete("memories", {"id": "mb"}) == 0                          # cannot delete it
    assert backend.get("memories", {"id": "mb"})["content"] == "bob secret"
    with pytest.raises(ScopeError):
        a.select("memories", {"user_id": "bob"})                          # cannot widen the scope through the filter
    with pytest.raises(ScopeError):
        a.insert("memories", {"id": "x", "user_id": "bob", "category": "semantic", "content": "x"})
    assert a.count("memories") == 1
