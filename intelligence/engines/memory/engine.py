"""Memory Engine: per-user, per-project memory with categories, retrieval ranking and lifecycle.

Categories
  working         short-lived scratch for the current conversation (bounded, oldest evicted, expires)
  conversational  one entry per exchanged message worth recalling later in the same conversation
  episodic        things that happened ("user corrected a capital on 2026-11-09")
  semantic        stable facts about the user/world that are not structured knowledge
  preference      keyed user preferences (``key`` is unique per user; newer value supersedes older)
  learned         records written by the Learning Engine after a verified update

All access goes through ``ScopedRepo`` so rows of other users/projects are unreachable by construction.
Retrieval score = relevance (BM25, normalised) x 0.60 + recency x 0.20 + importance x 0.15 + access reinforcement x 0.05.
Scores are ranking heuristics, not probabilities.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from ...algorithms.text_similarity import BM25, content_words
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import InputError, NotFoundError
from ...core.types import Clock, Scope, SystemClock, new_id
from ...storage.backend import Backend
from ...storage.scoped import ScopedRepo

CATEGORIES = ("working", "conversational", "episodic", "semantic", "preference", "learned")
HALF_LIFE_DAYS = {"working": 0.1, "conversational": 3.0, "episodic": 30.0, "semantic": 180.0, "preference": 365.0, "learned": 365.0}
WORKING_CAPACITY = 12
WORKING_TTL = timedelta(hours=2)
MAX_CONTENT = 4000


def _parse(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class MemoryEngine(Engine):
    info = EngineInfo(
        key="memory", name="Memory Engine", status=EngineStatus.IMPLEMENTED,
        summary="Scoped, categorised memory with keyed preferences, BM25+recency+importance retrieval, expiry and inspection.",
        depends_on=("storage",),
        capabilities=("six memory categories", "keyed supersession for preferences", "bounded working memory with TTL",
                      "BM25 + recency + importance ranking with explainable score parts", "update / forget / inspect / prune",
                      "per-user and per-project isolation enforced in the storage layer"),
        limitations=("Retrieval is lexical: paraphrases that share no content words are not found.",
                     "No automatic summarisation or consolidation of old memories.",
                     "Importance is assigned by callers/heuristics, not learned."),
    )

    def __init__(self, backend: Backend, clock: Clock | None = None):
        super().__init__()
        self.backend = backend
        self.clock = clock or SystemClock()

    def self_check(self) -> tuple[bool, str]:
        ok, detail = self.backend.ping()
        return ok, detail

    def repo(self, scope: Scope) -> ScopedRepo:
        return ScopedRepo(self.backend, scope)

    # ---- writing -----------------------------------------------------------------------------------------------------
    @traced("remember")
    def remember(self, scope: Scope, category: str, content: str, *, key: str | None = None, data: dict | None = None, acr: dict | None = None,
                 importance: float = 0.5, confidence: float = 1.0, source: str = "user_statement", conversation_id: str | None = None,
                 ttl: timedelta | None = None) -> dict:
        if category not in CATEGORIES:
            raise InputError(f"unknown memory category {category!r}")
        content = (content or "").strip()
        if not content:
            raise InputError("memory content is empty")
        if len(content) > MAX_CONTENT:
            raise InputError(f"memory content exceeds {MAX_CONTENT} characters")
        if not (0 <= importance <= 1 and 0 <= confidence <= 1):
            raise InputError("importance and confidence must be within [0, 1]")
        repo = self.repo(scope)
        now = self.clock.now()
        if category == "working" and ttl is None:
            ttl = WORKING_TTL
        superseded: list[str] = []
        if key:
            for old in repo.select("memories", {"category": category, "key": key, "status": "active"}):
                if old["content"].strip() == content and (old.get("data") or {}) == (data or {}):
                    repo.update("memories", {"id": old["id"]}, {"access_count": (old.get("access_count") or 0) + 1, "updated_at": now.isoformat()})
                    return {**old, "action": "unchanged"}
                repo.update("memories", {"id": old["id"]}, {"status": "superseded", "updated_at": now.isoformat()})
                superseded.append(old["id"])
        row = repo.insert("memories", {
            "id": "mem_" + new_id(), "category": category, "key": key, "content": content, "data": data or {}, "acr": acr,
            "importance": importance, "confidence": confidence, "source": source, "conversation_id": conversation_id, "status": "active",
            "access_count": 0, "created_at": now.isoformat(), "updated_at": now.isoformat(), "last_accessed_at": None,
            "expires_at": (now + ttl).isoformat() if ttl else None})
        if category == "working":
            self._enforce_working_capacity(scope, conversation_id)
        return {**row, "action": "superseded" if superseded else "created", "superseded": superseded}

    def _enforce_working_capacity(self, scope: Scope, conversation_id: str | None) -> None:
        repo = self.repo(scope)
        rows = [r for r in repo.select("memories", {"category": "working", "status": "active"}) if r.get("conversation_id") == conversation_id]
        rows.sort(key=lambda r: r["created_at"])
        for r in rows[:max(0, len(rows) - WORKING_CAPACITY)]:
            repo.update("memories", {"id": r["id"]}, {"status": "deleted"})

    def set_preference(self, scope: Scope, key: str, value: Any, *, content: str | None = None, source: str = "user_statement") -> dict:
        return self.remember(scope, "preference", content or f"{key}: {value}", key=key, data={"value": value}, importance=0.8, source=source)

    def get_preference(self, scope: Scope, key: str, default: Any = None) -> Any:
        rows = self.repo(scope).select("memories", {"category": "preference", "key": key, "status": "active"})
        live = [r for r in rows if not self._expired(r)]
        if not live:
            return default
        live.sort(key=lambda r: r["created_at"], reverse=True)
        return (live[0].get("data") or {}).get("value", default)

    def preferences(self, scope: Scope) -> dict[str, Any]:
        out: dict[str, Any] = {}
        rows = [r for r in self.repo(scope).select("memories", {"category": "preference", "status": "active"}) if not self._expired(r)]
        for r in sorted(rows, key=lambda r: r["created_at"]):
            out[r["key"] or r["id"]] = (r.get("data") or {}).get("value")
        return out

    # ---- retrieval -----------------------------------------------------------------------------------------------------
    def _expired(self, row: dict) -> bool:
        exp = _parse(row.get("expires_at"))
        return bool(exp and exp <= self.clock.now())

    @traced("recall")
    def recall(self, scope: Scope, query: str, *, categories: tuple[str, ...] | None = None, limit: int = 5, conversation_id: str | None = None,
               min_relevance: float = 0.0, touch: bool = True) -> list[dict]:
        """Ranked memories for ``query``. Each hit carries the score parts so the ranking can be inspected."""
        repo = self.repo(scope)
        rows = [r for r in repo.select("memories", {"status": "active"}) if not self._expired(r) and (not categories or r["category"] in categories)]
        if conversation_id is not None:
            rows = [r for r in rows if r["category"] not in ("working", "conversational") or r.get("conversation_id") == conversation_id]
        if not rows:
            return []
        q = content_words(query)
        docs = [content_words(r["content"] + " " + (r.get("key") or "")) for r in rows]
        rel = BM25(docs).scores(q) if q else [0.0] * len(rows)
        top = max(rel) or 1.0
        now = self.clock.now()
        hits = []
        for r, raw in zip(rows, rel):
            if q and raw <= 0:
                continue
            relevance = raw / top if q else 0.0
            if relevance < min_relevance and q:
                continue
            age_days = max(0.0, (now - (_parse(r.get("last_accessed_at")) or _parse(r["created_at"]))).total_seconds() / 86400)
            recency = 0.5 ** (age_days / HALF_LIFE_DAYS.get(r["category"], 30.0))
            importance = float(r.get("importance") if r.get("importance") is not None else 0.5)
            reinforcement = min(1.0, math.log1p(r.get("access_count") or 0) / math.log(11))
            score = 0.60 * relevance + 0.20 * recency + 0.15 * importance + 0.05 * reinforcement
            hits.append({"memory": r, "score": round(score, 4), "parts": {"relevance": round(relevance, 4), "recency": round(recency, 4),
                                                                         "importance": round(importance, 4), "reinforcement": round(reinforcement, 4)}})
        hits.sort(key=lambda h: (-h["score"], h["memory"]["created_at"]))
        hits = hits[:limit]
        if touch:
            for h in hits:
                m = h["memory"]
                repo.update("memories", {"id": m["id"]}, {"access_count": (m.get("access_count") or 0) + 1, "last_accessed_at": now.isoformat()})
        return hits

    def recent(self, scope: Scope, *, category: str | None = None, conversation_id: str | None = None, limit: int = 10) -> list[dict]:
        where: dict[str, Any] = {"status": "active"}
        if category:
            where["category"] = category
        rows = [r for r in self.repo(scope).select("memories", where) if not self._expired(r)]
        if conversation_id is not None:
            rows = [r for r in rows if r.get("conversation_id") == conversation_id]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows[:limit]

    def record_turn(self, scope: Scope, conversation_id: str, role: str, text: str, *, importance: float = 0.3) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None
        return self.remember(scope, "conversational", f"{role}: {text[:MAX_CONTENT - 20]}", data={"role": role}, importance=importance,
                             conversation_id=conversation_id, source="conversation")

    # ---- lifecycle -----------------------------------------------------------------------------------------------------------
    def get(self, scope: Scope, memory_id: str) -> dict:
        row = self.repo(scope).get("memories", {"id": memory_id})
        if not row or row["status"] == "deleted":
            raise NotFoundError("memory not found")
        return row

    @traced("update_memory")
    def update(self, scope: Scope, memory_id: str, *, content: str | None = None, importance: float | None = None, data: dict | None = None) -> dict:
        row = self.get(scope, memory_id)
        values: dict[str, Any] = {"updated_at": self.clock.now().isoformat()}
        if content is not None:
            if not content.strip():
                raise InputError("memory content is empty")
            values["content"] = content.strip()
        if importance is not None:
            if not 0 <= importance <= 1:
                raise InputError("importance must be within [0, 1]")
            values["importance"] = importance
        if data is not None:
            values["data"] = data
        self.repo(scope).update("memories", {"id": row["id"]}, values)
        return self.get(scope, memory_id)

    @traced("forget")
    def forget(self, scope: Scope, memory_id: str) -> bool:
        self.get(scope, memory_id)
        return self.repo(scope).update("memories", {"id": memory_id}, {"status": "deleted", "updated_at": self.clock.now().isoformat()}) > 0

    def forget_matching(self, scope: Scope, query: str, *, categories: tuple[str, ...] | None = None, min_relevance: float = 0.6) -> list[str]:
        """Delete memories that match ``query`` strongly. Returns the ids removed (so callers can report exactly what was forgotten)."""
        hits = self.recall(scope, query, categories=categories, limit=20, min_relevance=min_relevance, touch=False)
        ids = [h["memory"]["id"] for h in hits if h["parts"]["relevance"] >= min_relevance]
        for i in ids:
            self.forget(scope, i)
        return ids

    def prune(self, scope: Scope) -> int:
        """Mark expired memories deleted. Returns the number removed."""
        repo = self.repo(scope)
        n = 0
        for r in repo.select("memories", {"status": "active"}):
            if self._expired(r):
                repo.update("memories", {"id": r["id"]}, {"status": "deleted"})
                n += 1
        return n

    def inspect(self, scope: Scope, *, include_inactive: bool = False, limit: int = 200) -> dict:
        rows = self.repo(scope).select("memories", None)
        counts: dict[str, int] = {}
        for r in rows:
            if r["status"] == "active" and not self._expired(r):
                counts[r["category"]] = counts.get(r["category"], 0) + 1
        shown = [r for r in rows if include_inactive or (r["status"] == "active" and not self._expired(r))]
        shown.sort(key=lambda r: r["created_at"], reverse=True)
        return {"active_by_category": counts, "total_rows": len(rows), "memories": shown[:limit]}
