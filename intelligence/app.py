"""AVOENIX application core: builds the twelve engines and runs one conversational turn through them.

This module is independent of any web framework. ``Avoenix.process_turn`` is the single entry point used by the API service,
the evaluation runner and the tests. Every stage is timed for real and reported in the returned ``TurnResult.trace``;
a stage that fails is recorded and the turn degrades instead of crashing.
"""

from __future__ import annotations

import zlib

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .core.contracts import Conclusion, ContentPlan, EmotionSignal, InputPacket, LanguageResult, ReasoningResult, StageTrace, TurnResult
from .core.engine import Engine
from .core.errors import AvoenixError, InputError, NotFoundError, UnsupportedLanguageError
from .core.types import Clock, Scope, SystemClock
from .engines.context.engine import ContextEngine, ConversationState
from .engines.emotion.engine import EmotionEngine
from .engines.evaluation.engine import EvaluationEngine
from .engines.input.engine import InputProcessingEngine
from .engines.knowledge.engine import KnowledgeEngine, SelfModel
from .engines.knowledge.integrity import classify_claim
from .engines.language.engine import LanguageEngine
from .engines.learning.engine import LearningEngine
from .engines.memory.engine import MemoryEngine
from .engines.personality.engine import PersonalityEngine
from .engines.planning.engine import PlanningEngine
from .engines.reasoning.engine import ReasoningEngine
from .engines.reasoning.facts import fact_data
from .engines.response.engine import ResponseGenerationEngine
from .engines.response.planner import build_plan
from .meaning.engine import MeaningLayer
from .meaning.dialogue import DialogueState as _DS


class DialogueSnapshot:
    @staticmethod
    def of(d: dict) -> dict:
        return _DS(d).snapshot()
from .representation import Entity, Intention, Proposition
from .storage.backend import Backend
from .storage.scoped import ScopedRepo
from .version import ACR_SCHEMA_VERSION, API_VERSION, DATABASE_SCHEMA_VERSION, PLATFORM_VERSION

CAPABILITIES = ["compare people or things (older, taller, faster...) and work out who is the oldest or youngest",
                "answer simple facts I know or that you've told me", "do exact arithmetic", "keep track of what you tell me within and across conversations"]
_SELF_PATTERNS = [
    (r"\b(who|what)\s+(are|r)\s+you\b|\btell me about (yourself|you)\b|\bintroduce yourself\b|\bwhat is avoenix\b|\bwhat'?s avoenix\b", "identity"),
    (r"\b(can|could) you (please )?(help|assist)\b|\bwhat can you do\b|\bwhat are your (capabilities|abilities|skills)\b|\bhow can you help\b|\bwhat are you (good|able)\b", "capabilities"),
    (r"\bwhat (version|release) (are you|is this)\b|\bwhich version\b", "version"),
    (r"\bwhat are your (limits|limitations|weaknesses)\b|\bwhat can'?t you do\b", "limitations"),
]
_SELF_KIND = re.compile(r"\bare you (?:a |an |the )?(?P<k>large language model|language model|llm|chatbot|chat bot|neural network|gpt|robot|human|person|ai|artificial intelligence|algorithm)\b", re.I)
_KIND_CANON = {"large language model": "large language model", "language model": "large language model", "llm": "large language model", "gpt": "large language model",
               "chatbot": "scripted chatbot", "chat bot": "scripted chatbot", "neural network": "neural network"}

def _is_open_claim(r) -> bool:
    """A world statement the user made: it is reported as a claim with its verification state (never simply 'noted'), even when it turns out to agree with knowledge."""
    return bool(r.fact) and r.fact.claim_type == "world"


_RECALL = re.compile(r"\bwhat (do|did) you (remember|know) about (me|us)\b|\bdo you remember (me|anything)\b|\bwhat have i told you\b|\bwhat do you know about me\b", re.I)


@dataclass
class AvoenixConfig:
    max_input_chars: int = 4000
    history_turns: int = 40
    clock: Clock = field(default_factory=SystemClock)
    seed_knowledge: bool = True
    deterministic_seed: int | None = None          # tests/evaluation: fixed response seed base
    meaning_enabled: bool = True                   # the meaning layer (frames, dialogue state, composition); False reproduces the v0.0.1 pipeline exactly
    lexicon_store: str | None = None               # path to a processed lexical store (intelligence/ingest) that extends the seed lexicon, read-only
    diagnostics: bool = False                      # attach the full meaning-layer inspection record to TurnResult.response_meta["meaning"] (never set by public endpoints)


class _Stages:
    def __init__(self) -> None:
        self.trace: list[StageTrace] = []
        self.errors: list[dict] = []

    def run(self, engine: str, op: str, fn: Callable[[], Any], summarize: Callable[[Any], dict] | None = None, *, default: Any = None) -> Any:
        t0 = time.perf_counter()
        try:
            out = fn()
            self.trace.append(StageTrace(engine, op, (time.perf_counter() - t0) * 1000, True, summarize(out) if summarize and out is not None else {}))
            return out
        except UnsupportedLanguageError as e:
            self.trace.append(StageTrace(engine, op, (time.perf_counter() - t0) * 1000, False, {}, f"UnsupportedLanguageError: {e}"))
            raise
        except InputError as e:
            self.trace.append(StageTrace(engine, op, (time.perf_counter() - t0) * 1000, False, {}, f"InputError: {e}"))
            raise
        except Exception as e:  # noqa: BLE001 - stage failures are reported, the turn degrades
            msg = f"{type(e).__name__}: {e}"
            self.trace.append(StageTrace(engine, op, (time.perf_counter() - t0) * 1000, False, {}, msg))
            self.errors.append({"engine": engine, "operation": op, "error": msg})
            return default


class Avoenix:
    """Composition root. ``backend`` is any storage Backend (in-memory for tests, PostgreSQL in production)."""

    def __init__(self, backend: Backend, config: AvoenixConfig | None = None):
        self.config = config or AvoenixConfig()
        self.backend = backend
        clock = self.config.clock
        self.input = InputProcessingEngine(max_chars=self.config.max_input_chars, clock=clock)
        self.language = LanguageEngine()
        self.context = ContextEngine()
        self.memory = MemoryEngine(backend, clock)
        self.knowledge = KnowledgeEngine(backend, self_model=SelfModel(self._engine_summaries))
        self.reasoning = ReasoningEngine(self.knowledge)
        self.learning = LearningEngine(backend, self.knowledge, self.memory, language=self.language)
        self.emotion = EmotionEngine()
        self.planning = PlanningEngine(self.memory)
        self.personality = PersonalityEngine(self.memory)
        self.response = ResponseGenerationEngine()
        self.evaluation = EvaluationEngine(backend)
        if self.config.lexicon_store:
            from .meaning.lexicon import use_store
            use_store(self.config.lexicon_store)
        self.meaning = MeaningLayer(self.knowledge)
        if self.config.seed_knowledge:
            self.knowledge.seed()

    # ---- registry -------------------------------------------------------------------------------------------------------------
    @property
    def engines(self) -> dict[str, Engine]:
        return {"input": self.input, "language": self.language, "context": self.context, "memory": self.memory, "knowledge": self.knowledge,
                "reasoning": self.reasoning, "learning": self.learning, "emotion": self.emotion, "planning": self.planning,
                "personality": self.personality, "response": self.response, "evaluation": self.evaluation}

    def _engine_summaries(self) -> list[dict]:
        return [{"key": k, "name": e.info.name, "status": e.info.status.value, "summary": e.info.summary} for k, e in self.engines.items()] if hasattr(self, "language") else []

    def version_info(self) -> dict:
        return {"platform": PLATFORM_VERSION, "api": API_VERSION, "acr_schema": ACR_SCHEMA_VERSION, "database_schema": DATABASE_SCHEMA_VERSION}

    def engines_info(self) -> list[dict]:
        return [{**e.info.to_dict(), "metrics": e.metrics.to_dict()} for e in self.engines.values()]

    def health(self) -> dict:
        ok, detail = self.backend.ping()
        engines = [e.health().to_dict() for e in self.engines.values()]
        worst = "ok" if all(e["status"] == "ok" for e in engines) and ok else ("failed" if not ok or any(e["status"] == "failed" for e in engines) else "degraded")
        return {"status": worst, "version": PLATFORM_VERSION, "storage": {"ok": ok, "detail": detail}, "engines": engines}

    # ---- conversations ------------------------------------------------------------------------------------------------------
    def create_conversation(self, scope: Scope, title: str | None = None) -> dict:
        now = self.config.clock.now().isoformat()
        cid = "c_" + uuid.uuid4().hex[:16]
        state = {"context": self.context.new_state(cid).to_dict(), "response": self.response.new_state()}
        return ScopedRepo(self.backend, scope).insert("conversations", {"id": cid, "title": title, "state": state, "archived": False, "created_at": now, "updated_at": now})

    def list_conversations(self, scope: Scope, *, include_archived: bool = False, limit: int = 100) -> list[dict]:
        rows = ScopedRepo(self.backend, scope).select("conversations", None if include_archived else {"archived": False})
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        return [{k: r[k] for k in ("id", "title", "archived", "created_at", "updated_at")} for r in rows[:limit]]

    def get_conversation(self, scope: Scope, conversation_id: str) -> dict:
        row = ScopedRepo(self.backend, scope).get("conversations", {"id": conversation_id})
        if not row:
            raise NotFoundError("conversation not found")
        return row

    def messages(self, scope: Scope, conversation_id: str, limit: int | None = 500) -> list[dict]:
        """Messages in order. ``limit=None`` returns the complete conversation (used by export)."""
        self.get_conversation(scope, conversation_id)
        rows = ScopedRepo(self.backend, scope).select("messages", {"conversation_id": conversation_id})
        rows.sort(key=lambda r: (r["turn_index"], 0 if r["role"] == "user" else 1))
        return rows if limit is None else rows[:limit]

    def delete_conversation(self, scope: Scope, conversation_id: str) -> bool:
        self.get_conversation(scope, conversation_id)
        repo = ScopedRepo(self.backend, scope)
        repo.delete("turn_traces", {"conversation_id": conversation_id})
        repo.delete("messages", {"conversation_id": conversation_id})
        return repo.delete("conversations", {"id": conversation_id}) > 0

    def get_trace(self, scope: Scope, message_id: str) -> dict:
        row = ScopedRepo(self.backend, scope).get("turn_traces", {"message_id": message_id})
        if not row:
            raise NotFoundError("trace not found")
        return row

    # ---- the turn -------------------------------------------------------------------------------------------------------------
    def process_turn(self, scope: Scope, text: str, conversation_id: str | None = None, *, client_context: dict | None = None, persist: bool = True) -> TurnResult:
        t_start = time.perf_counter()
        ctx = client_context or {}
        st = _Stages()
        repo = ScopedRepo(self.backend, scope)
        turn_id = "t_" + uuid.uuid4().hex[:12]
        if conversation_id is None:
            conv = self.create_conversation(scope, (text or "").strip()[:60] or None)
        else:
            conv = self.get_conversation(scope, conversation_id)
        cid = conv["id"]
        state_blob = conv.get("state") or {}
        cstate = ConversationState.from_dict(state_blob["context"]) if state_blob.get("context") else self.context.new_state(cid)
        rstate = state_blob.get("response") or self.response.new_state()
        prior_msgs = repo.count("messages", {})
        had_conversations = repo.count("conversations", {}) > 1
        capability_text = CAPABILITIES

        # 1) input ------------------------------------------------------------------------------------------------------------------
        try:
            packet: InputPacket = st.run("input", "process", lambda: self.input.process(text), lambda p: {"language": p.language, "words": p.metadata.get("words"), "warnings": p.warnings})
        except (UnsupportedLanguageError, InputError) as e:
            code = "unsupported_language" if isinstance(e, UnsupportedLanguageError) else ("empty_input" if "empty" in str(e).lower() else "too_long" if "long" in str(e).lower() else "invalid_input")
            return self._finish_error(scope, cid, cstate, rstate, text, code, str(e), st, t_start, turn_id, persist, repo, conv)

        # 2) language ----------------------------------------------------------------------------------------------------------------
        lr: LanguageResult | None = st.run("language", "analyze", lambda: self.language.analyze(packet),
                                           lambda r: {"speech_acts": r.speech_acts, "coverage": round(r.coverage, 3), "interpretation_confidence": round(r.interpretation_confidence, 3),
                                                      "sentences": r.sentences, "corrections": len(r.corrections), "unsupported": r.unsupported})
        if lr is None:
            return self._finish_error(scope, cid, cstate, rstate, text, "language_failure", "the language stage failed", st, t_start, turn_id, persist, repo, conv)

        # 2b) meaning layer: frames, dialogue state, composition. Declines (returns None) when it lacks the structure to understand the turn. ------
        if self.config.meaning_enabled:
            seed_m = None if self.config.deterministic_seed is None else self.config.deterministic_seed + cstate.turn * 131 + zlib.crc32(scope.user_id.encode())
            prefs_m = self.memory.preferences(scope)
            mo = st.run("meaning", "handle", lambda: self.meaning.handle(scope, packet.text, lr, cstate.dialogue, cstate.premises, conversation_id=cid, seed=seed_m,
                                                                         explain=bool(prefs_m.get("behavior.show_steps"))),
                        lambda o: {"handled": bool(o.text), "rewrite": o.rewrite, "confidence": round(o.confidence, 3), "acts": [a["type"] for a in o.acts]})
            if mo is not None and mo.rewrite:
                try:
                    packet = self.input.process(mo.rewrite)
                    lr2 = self.language.analyze(packet)
                    if lr2 is not None:
                        lr = lr2
                        st.trace.append(StageTrace("meaning", "rewrite", 0.0, True, {"canonical_question": mo.rewrite}))
                except (UnsupportedLanguageError, InputError):
                    pass
            elif mo is not None and mo.text:
                return self._finish_meaning(scope, repo, conv, cid, cstate, rstate, text, packet, lr, mo, st, t_start, turn_id, persist)

        # 3) context -----------------------------------------------------------------------------------------------------------------
        report = st.run("context", "resolve", lambda: self.context.resolve(lr.doc, cstate),
                        lambda r: {"resolved": len(r.resolved), "ambiguous": len(r.ambiguous), "unresolved": len(r.unresolved), "ellipsis": bool(r.ellipsis)})
        # 4) emotion -------------------------------------------------------------------------------------------------------------------
        emotion: EmotionSignal | None = st.run("emotion", "analyze", lambda: self.emotion.analyze(lr), lambda e: {"label": e.label, "valence": e.valence, "arousal": e.arousal, "certainty": e.certainty})
        # 5) personality observation ------------------------------------------------------------------------------------------------------
        st.run("personality", "observe", lambda: self.personality.observe(scope, lr), lambda s: {"messages_observed": s.get("n")})

        # 6) task routing -------------------------------------------------------------------------------------------------------------------
        social = self._social_acts(lr)
        questions, statements = self._split_intentions(lr)
        norm = packet.text
        learn_class = self.learning.classify(norm) if not questions else None
        if learn_class and learn_class.get("kind") == "fact_correction":
            # A correction about the WORLD ("No, the capital is X") is a claim, not something to learn: it goes through the Knowledge Integrity
            # path (validated, provenance kept, earlier claim revised) instead of being applied as learned knowledge.
            try:
                facts, _ = self.learning._statement_to_facts(scope, learn_class["statement"])
            except AvoenixError:
                facts = []
            if facts and all(classify_claim(f[0], f[1]) == "world" for f in facts):
                learn_class = None
        self_q = self._self_question(norm, lr, questions)
        recall_q = bool(_RECALL.search(norm))
        goal_text = None if (questions or learn_class or self_q) else self.planning.detect_goal(norm)
        task = self._task(lr, social, questions, statements, learn_class, self_q, recall_q, goal_text)

        conclusions: list[Conclusion] = []
        reasoning: ReasoningResult | None = None
        stored: list[dict] = []
        learning: list[dict] = []
        goal_msg: dict | None = None
        self_msg: dict | None = None
        recall_items: list[str] | None = None
        clarify: dict | None = None
        stored_facts_meta: list[dict] = []

        if learn_class:
            r = st.run("learning", "learn_from_message", lambda: self.learning.learn_from_message(scope, norm, conversation_id=cid),
                       lambda r: {"kind": r["kind"], "status": r["status"], "verified": r["verified"]} if r else {})
            if r:
                learning.append(r)
        elif goal_text:
            def mk_goal():
                title, steps = (goal_text.split(":", 1) + [None])[:2] if ":" in goal_text else (goal_text, goal_text if re.search(r"\bthen\b", goal_text) else None)
                title = title.strip()
                g = self.planning.create_goal(scope, title[:1].upper() + title[1:], decompose_text=steps.strip() if steps else None)
                nxt = self.planning.next_actions(scope, g.id)
                return {"title": g.title, "tasks": [t.title for t in g.tasks], "next": nxt[0].title if nxt and g.tasks else None, "id": g.id}
            goal_msg = st.run("planning", "create_goal", mk_goal, lambda g: {"goal": g["id"], "tasks": len(g["tasks"])})
        elif self_q:
            self_msg = st.run("knowledge", "self_description", lambda: self._self_message(self_q, norm), lambda m: {"type": m["type"]})
        elif recall_q:
            recall_items = st.run("memory", "recall_user", lambda: self._recall_items(scope), lambda i: {"items": len(i)}, default=[])
        else:
            ambiguous = report.ambiguous if report else []
            if ambiguous and questions:
                a = ambiguous[0]
                clarify = {"options": list(a.get("candidates", []))[:4], "surface": a.get("word")}
            else:
                reasoning = st.run("reasoning", "reason", lambda: self.reasoning.reason(scope, lr, conversation_id=cid),
                                   lambda r: {"conclusions": len(r.conclusions), "primary_status": r.primary.status if r.primary else None,
                                              "strategy": r.primary.strategy if r.primary else None,
                                              "strategies_applicable": [t["strategy"] for t in r.strategies_tried if t["applicable"]]})
                if reasoning:
                    conclusions = reasoning.conclusions
                blocked = any(c.status == "contradiction" for c in conclusions)
                if statements and not blocked:
                    acts = {n.act for n in lr.doc.of_kind(Intention)}
                    corrected = "correct" in acts or ("deny" in acts and "assert" in acts)       # "No, it is X" revises the user's earlier claim

                    def store_all():
                        out = []
                        for rid in lr.doc.roots:
                            n = lr.doc.nodes[rid]
                            if isinstance(n, Intention) and n.act in ("assert", "inform", "correct", "confirm"):
                                for pid in n.content:
                                    if isinstance(lr.doc.nodes.get(pid), Proposition):
                                        out += self.knowledge.assert_proposition(scope, lr.doc, pid, conversation_id=cid, correction=corrected)
                        return out
                    results = st.run("knowledge", "assert_proposition", store_all,
                                     lambda rs: {"results": [r.status for r in rs], "verification": [r.verification for r in rs]}, default=[]) or []
                    good = [r for r in results if r.status in ("stored", "duplicate", "superseded", "disputed") and r.fact]
                    plain = [r for r in good if not _is_open_claim(r)]
                    claim_results = [r for r in good if _is_open_claim(r)]
                    if plain:
                        status = "superseded" if any(r.status == "superseded" for r in plain) else ("duplicate" if all(r.status == "duplicate" for r in plain) else "stored")
                        stored.append({"facts": [fact_data(r.fact) for r in plain], "status": status})
                        stored_facts_meta = [r.fact.to_dict() for r in plain]
                    for r in claim_results:
                        stored.append({"claim": self._claim_entry(scope, r, norm, cid)})
                        stored_facts_meta.append(r.fact.to_dict())
                    for r in results:
                        if r.status == "disputed" and not r.fact:
                            stored.append({"ok": False, "reason": "it conflicts with something I hold with higher reliability, so I've kept my current information"})
                            break
        actions = [n for n in lr.doc.of_kind(Intention) if n.act == "request_action"]
        if actions and not (conclusions or learning or goal_msg or self_msg or recall_items is not None or clarify):
            conclusions = [Conclusion(strategy="none", status="unsupported", steps=["That is a request to perform an action or produce content, which this version cannot do."])]

        # 7) memory --------------------------------------------------------------------------------------------------------------------------
        st.run("memory", "record_turn", lambda: self.memory.record_turn(scope, cid, "user", norm), lambda m: {"stored": bool(m)})

        # 8) personality profile + response -------------------------------------------------------------------------------------------------
        prof = st.run("personality", "profile", lambda: self.personality.profile(scope, emotion), lambda p: {"reasons": p.reasons}, default=None)
        style = prof.to_dict() if prof else {"formality": 0.45, "warmth": 0.6, "conciseness": 0.5, "expressiveness": 0.4, "initiative": 0.2, "emoji_level": 0.0, "emoji_allowed": False}
        prefs = self.memory.preferences(scope)
        style["show_steps"] = bool(prefs.get("behavior.show_steps"))
        name = prefs.get("user.preferred_name") or self._known_name(scope)
        first_contact = prior_msgs == 0 and not had_conversations
        last_user_msg = None
        if not first_contact:
            rows = repo.select("messages", {"role": "assistant"})
            last_user_msg = max((r["created_at"] for r in rows), default=None)
        now = self.config.clock.now()
        returning = bool(last_user_msg) and (now - _parse_ts(last_user_msg)).total_seconds() > 12 * 3600 or (had_conversations and prior_msgs == 0)
        occasion = {"first_contact": first_contact, "returning": returning, "part_of_day": _part_of_day(ctx.get("local_hour")),
                    "user_greeting": next(({"formality": n.features.get("formality"), "warmth": n.features.get("warmth")} for n in lr.doc.of_kind(Intention) if n.act == "greet" and n.features.get("formality") is not None), None)}
        plan = build_plan(conclusions=conclusions, stored=stored, learning=learning, social=social, clarify=clarify, goal=goal_msg, self_description=self_msg,
                          recall=recall_items, capabilities=capability_text, explain=style["show_steps"], name=name, occasion=occasion)
        if self_q and isinstance(self_q, dict) and self_q.get("kind") == "kind_check":
            plan.messages = [m for m in plan.messages if m["type"] != "self"] + ([self_msg] if self_msg else [])
        seed = None if self.config.deterministic_seed is None else self.config.deterministic_seed + cstate.turn * 101 + zlib.crc32(scope.user_id.encode())
        resp = st.run("response", "generate", lambda: self.response.generate(plan, style, emotion, rstate, seed=seed, name=name, occasion=occasion),
                      lambda r: {"objective": plan.objective, "skeletons": r.variation["skeletons"], "emoji": r.emoji, "repeat": r.variation["repeat"]})
        text_out = resp.text if resp else "I ran into a problem while forming a reply."

        # 9) evaluation + context update + persistence -------------------------------------------------------------------------------------------
        assessment = st.run("evaluation", "assess_turn", lambda: self.evaluation.assess_turn(lr, reasoning, emotion), lambda a: {"band": a["band"], "overall": a["overall"]}, default=None)
        st.run("memory", "record_response", lambda: self.memory.record_turn(scope, cid, "assistant", text_out), lambda m: {"stored": bool(m)})
        st.run("context", "update", lambda: self.context.update(cstate, lr.doc, user_text=norm, system_text=text_out, answered=bool(conclusions)), None)
        total_ms = (time.perf_counter() - t_start) * 1000
        status = "ok" if not st.errors else ("partial" if resp else "error")
        primary = reasoning.primary if reasoning else None
        understanding = {"task": task, "speech_acts": lr.speech_acts, "interpretation_confidence": round(lr.interpretation_confidence, 3), "coverage": round(lr.coverage, 3),
                         "sentences": lr.sentences, "corrections": lr.corrections, "unsupported": lr.unsupported, "notes": lr.notes, "language": packet.language,
                         "acr": lr.doc.to_dict()}
        confidence = assessment or {"overall": None, "band": "not_evaluated", "components": {}, "not_evaluated": ["assessment failed"]}
        result = TurnResult(
            response=text_out, conversation_id=cid, status=status, trace=st.trace, total_ms=total_ms, understanding=understanding,
            reasoning=reasoning.to_dict() if reasoning else None, confidence=confidence, emotion=emotion.to_dict() if emotion else None,
            context={"resolution": report.to_dict() if report else None, "state": self.context.describe(cstate)},
            memory={"stored_facts": stored_facts_meta, "learning": learning, "goal": goal_msg},
            response_meta=({**resp.variation, "plan": plan.to_dict(), "style_reasons": (prof.reasons if prof else [])} if resp else {"plan": plan.to_dict()}),
            errors=st.errors, turn_id=turn_id)
        if persist:
            self._persist(scope, repo, conv, cid, cstate, rstate, text, text_out, result, now, total_ms)
        result.response_meta["reasoning_status"] = primary.status if primary else None
        return result

    def _finish_meaning(self, scope, repo, conv, cid, cstate: ConversationState, rstate, text, packet, lr, mo, st, t_start, turn_id, persist) -> TurnResult:
        """Complete a turn that the meaning layer answered: keep emotion/personality/memory/context continuity and build the same TurnResult shape."""
        norm = packet.text
        emotion = st.run("emotion", "analyze", lambda: self.emotion.analyze(lr), lambda e: {"label": e.label, "valence": e.valence}, default=None)
        st.run("personality", "observe", lambda: self.personality.observe(scope, lr), None)
        st.run("memory", "record_turn", lambda: self.memory.record_turn(scope, cid, "user", norm), None)
        st.run("memory", "record_response", lambda: self.memory.record_turn(scope, cid, "assistant", mo.text), None)
        cstate.dialogue = mo.dialogue or cstate.dialogue
        cstate.premises = mo.premises or cstate.premises
        st.run("context", "update", lambda: self.context.update(cstate, lr.doc, user_text=norm, system_text=mo.text, answered=True), None)
        total_ms = (time.perf_counter() - t_start) * 1000
        status = "ok" if not st.errors else "partial"
        meaning_summary = {"frames": [f.get("frame") for f in mo.trace.get("frames", [])], "acts": [a["type"] for a in mo.acts], "confidence": round(mo.confidence, 3),
                           "uncertainty": mo.uncertainty, "stored": [{"status": s.get("status"), "verification": s.get("verification")} for s in mo.stored if isinstance(s, dict)]}
        if self.config.diagnostics:
            meaning_summary["inspection"] = mo.trace
        band = "high" if mo.confidence >= 0.8 else "medium" if mo.confidence >= 0.55 else "low"
        understanding = {"task": "meaning", "speech_acts": lr.speech_acts, "interpretation_confidence": round(lr.interpretation_confidence, 3), "coverage": round(lr.coverage, 3),
                         "sentences": lr.sentences, "corrections": lr.corrections, "unsupported": lr.unsupported, "notes": lr.notes, "language": packet.language,
                         "acr": lr.doc.to_dict()}
        result = TurnResult(
            response=mo.text, conversation_id=cid, status=status, trace=st.trace, total_ms=total_ms, understanding=understanding,
            reasoning=(mo.trace.get("reasoning") if isinstance(mo.trace.get("reasoning"), dict) else None),
            confidence={"overall": round(mo.confidence, 3), "band": band, "components": {"meaning": round(mo.confidence, 3)}, "not_evaluated": [], "uncertainty": mo.uncertainty},
            emotion=emotion.to_dict() if emotion else None,
            context={"resolution": None, "state": self.context.describe(cstate), "dialogue": (mo.dialogue or {}) and DialogueSnapshot.of(mo.dialogue)},
            memory={"stored_facts": [s["fact"] for s in mo.stored if isinstance(s, dict) and s.get("fact")], "learning": [], "goal": None},
            response_meta={"engine": "meaning", "meaning": meaning_summary, "plan": {"acts": [a["type"] for a in mo.acts]}}, errors=st.errors, turn_id=turn_id)
        if persist:
            self._persist(scope, repo, conv, cid, cstate, rstate, text, mo.text, result, self.config.clock.now(), total_ms)
        return result

    # ---- routing helpers ---------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _social_acts(lr: LanguageResult) -> list[dict]:
        out = []
        for n in lr.doc.of_kind(Intention):
            if n.act in ("greet", "farewell", "thank", "social_inquiry"):
                out.append({"type": n.act, "features": dict(n.features)})
        return out

    @staticmethod
    def _split_intentions(lr: LanguageResult) -> tuple[list[Intention], list[Intention]]:
        qs, ss = [], []
        for rid in lr.doc.roots:
            n = lr.doc.nodes[rid]
            if isinstance(n, Intention):
                if n.act in ("request_information", "request_confirmation"):
                    qs.append(n)
                elif n.act in ("assert", "inform", "correct", "confirm") and n.content:
                    ss.append(n)
        return qs, ss

    def _self_question(self, text: str, lr: LanguageResult, questions: list[Intention]) -> dict | None:
        low = text.lower()
        m = _SELF_KIND.search(low)
        if m:
            return {"kind": "kind_check", "asked": m.group("k").lower()}
        for pat, kind in _SELF_PATTERNS:
            if re.search(pat, low):
                return {"kind": kind}
        return None

    def _self_message(self, q: dict, text: str) -> dict:
        facts = self.knowledge.self_model.facts()
        kind = next(f.args["object"]["label"] for f in facts if f.predicate == "rel.is_a" and f.polarity == "positive")
        not_kinds = [f.args["object"]["label"] for f in facts if f.predicate == "rel.is_a" and f.polarity == "negative"]
        version = next(f.args["value"]["value"] for f in facts if f.predicate == "attr.version")
        implemented = [e.info.name for e in self.engines.values() if e.info.status.value == "implemented"]
        partial = [e.info.name for e in self.engines.values() if e.info.status.value == "partial"]
        base = {"name": "AVOENIX", "kind": kind, "not_kinds": not_kinds, "version": version, "languages": ["English"]}
        k = q["kind"]
        if k == "kind_check":
            asked = q["asked"]
            canon = _KIND_CANON.get(asked)
            return {"type": "self_kind", "asked": asked, "is": asked in ("ai", "artificial intelligence", "algorithm"), "negative_known": canon in not_kinds if canon else False,
                    "kind": kind, "name": "AVOENIX", "version": version, "unknown": asked in ("robot", "human", "person")}
        if k == "identity":
            return {**base, "capabilities": CAPABILITIES[:3], "type": "self"}
        if k == "capabilities":
            return {"type": "self", **base, "capabilities": CAPABILITIES, "only_capabilities": True}
        if k == "version":
            return {"type": "self", **base, "only_version": True}
        return {"type": "self", **base, "limitations": [f"engines still partial: {', '.join(partial)}", "English only", "small built-in world knowledge (the rest comes from what you tell me)"],
                "only_limitations": True, "implemented": implemented}

    def _recall_items(self, scope: Scope) -> list[str]:
        from .engines.response.realizer import realize_fact
        items = [realize_fact(fact_data(f)) for f in self.knowledge.facts_about(scope, "@user") if f.level != "system"][:8]
        for m in self.memory.recent(scope, category="semantic", limit=4):
            if not (m.get("key") or "").startswith("goal:"):
                items.append(m["content"])
        return items

    def _known_name(self, scope: Scope) -> str | None:
        try:
            f = self.knowledge.query(scope, "attr.name", {"owner": "@user"}, include_self=False)
            return f[0].args["value"]["label"] if f else None
        except Exception:
            return None

    def _claim_entry(self, scope: Scope, r, utterance: str, cid: str) -> dict:
        """Structured description of a user claim for the response planner, and the episodic memory of *who said it* (separate from the claim)."""
        f = r.fact
        try:
            if not f.memory_id:
                mem = self.memory.remember(scope, "episodic", f"User said: {utterance[:400]}", data={"fact_id": f.id, "verification": r.verification},
                                           importance=0.4, conversation_id=cid, source="conversation")
                self.knowledge.link_memory(scope, f.id, mem["id"])
        except AvoenixError:
            pass
        established = None
        roles = {k: v.get("key") for k, v in f.args.items() if k != "value"}
        if "value" in f.args:
            for e in self.knowledge.query(scope, f.predicate, roles, established_only=True, conversation_id=cid):
                if e.polarity == f.polarity and e.id != f.id:
                    established = fact_data(e)
                    break
        a = r.assessment or f.assessment or {}
        return {"fact": fact_data(f), "verification": r.verification or f.verification, "level": a.get("level"), "status": r.status,
                "established": established, "fact_id": f.id, "conflict_ids": r.conflict_ids}

    @staticmethod
    def _task(lr: LanguageResult, social: list[dict], questions: list, statements: list, learn: dict | None, self_q: dict | None, recall_q: bool, goal: str | None) -> str:
        if learn:
            return {"preference": "preference_update", "strategy_adjustment": "preference_update", "fact_correction": "fact_correction", "general_knowledge": "teach_knowledge"}[learn["kind"]]
        if self_q:
            return "question_self"
        if recall_q:
            return "question_memory"
        if goal:
            return "goal_statement"
        if questions:
            q = questions[0]
            if lr.math or q.features.get("question_kind") == "arithmetic":
                return "question_arithmetic"
            preds = set()
            for pid in q.content:
                n = lr.doc.nodes.get(pid)
                if isinstance(n, Proposition):
                    preds.add(n.predicate)
            if preds & {"rel.exceeds", "rel.extreme", "rel.equal_on"} or (preds == {"rel.has_property"}):
                return "question_reasoning"
            return "question_factual"
        if any(n.act == "request_action" for n in lr.doc.of_kind(Intention)):
            return "request_action"
        names = {"greet": "greeting", "farewell": "farewell", "thank": "thanks", "social_inquiry": "social_inquiry"}
        # statement content beyond the social act itself (e.g. "Hello, my name is Alex") is the primary task
        if statements and any(n.content and any(isinstance(lr.doc.nodes.get(c), Proposition) for c in n.content) for n in statements):
            return "statement_fact"
        if social:
            return names[social[0]["type"]]
        return "statement_other" if statements else "unknown"

    # ---- finishing ---------------------------------------------------------------------------------------------------------------------------
    def _finish_error(self, scope, cid, cstate, rstate, text, code, detail, st, t_start, turn_id, persist, repo, conv) -> TurnResult:
        plan = build_plan(error={"code": code, "detail": detail[:120]})
        resp = self.response.generate(plan, {"formality": 0.45, "warmth": 0.6, "conciseness": 0.5, "expressiveness": 0.4, "emoji_allowed": False, "emoji_level": 0.0}, None, rstate, seed=0)
        total_ms = (time.perf_counter() - t_start) * 1000
        result = TurnResult(response=resp.text, conversation_id=cid, status="error", trace=st.trace, total_ms=total_ms, understanding={"task": "rejected_input", "error": code},
                            reasoning=None, confidence={"overall": None, "band": "not_evaluated", "components": {}, "not_evaluated": ["input rejected"]}, emotion=None,
                            context={}, memory={}, response_meta={"plan": plan.to_dict()}, errors=[{"engine": "input", "operation": "process", "code": code, "error": detail}], turn_id=turn_id)
        if persist:
            self._persist(scope, repo, conv, cid, cstate, rstate, text if isinstance(text, str) else "", resp.text, result, self.config.clock.now(), total_ms)
        return result

    def _persist(self, scope: Scope, repo: ScopedRepo, conv: dict, cid: str, cstate: ConversationState, rstate: dict, user_text: str, reply: str, result: TurnResult,
                 now: datetime, total_ms: float) -> None:
        try:
            turn_index = repo.count("messages", {"conversation_id": cid}) // 2
            uid, aid = "m_" + uuid.uuid4().hex[:14], "m_" + uuid.uuid4().hex[:14]
            iso = now.isoformat()
            repo.insert("messages", {"id": uid, "conversation_id": cid, "role": "user", "content": user_text[: self.config.max_input_chars], "turn_index": turn_index, "latency_ms": None,
                                     "meta": {"turn_id": result.turn_id}, "created_at": iso})
            repo.insert("messages", {"id": aid, "conversation_id": cid, "role": "assistant", "content": reply, "turn_index": turn_index, "latency_ms": round(total_ms, 2),
                                     "meta": {"turn_id": result.turn_id, "status": result.status, "task": result.understanding.get("task"), "confidence": result.confidence.get("overall"),
                                              "emoji": result.response_meta.get("emoji", [])}, "created_at": iso})
            repo.insert("turn_traces", {"id": "tr_" + uuid.uuid4().hex[:14], "conversation_id": cid, "message_id": aid, "status": result.status, "total_ms": round(total_ms, 3),
                                        "trace": [t.to_dict() for t in result.trace],
                                        "summary": {"understanding": {k: v for k, v in result.understanding.items() if k != "acr"}, "confidence": result.confidence,
                                                    "reasoning": result.reasoning, "emotion": result.emotion, "errors": result.errors, "response_meta": result.response_meta},
                                        "created_at": iso})
            title = conv.get("title") or user_text.strip()[:60] or None
            repo.update("conversations", {"id": cid}, {"state": {"context": cstate.to_dict(), "response": rstate}, "updated_at": iso, "title": title})
            result.response_meta["message_id"] = aid
        except Exception as e:  # persistence failure must be visible, never silent
            result.errors.append({"engine": "storage", "operation": "persist_turn", "error": f"{type(e).__name__}: {e}"})
            result.status = "partial" if result.status == "ok" else result.status


def _parse_ts(ts: Any) -> datetime:
    d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _part_of_day(hour: Any) -> str | None:
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        return None
    return "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening" if 18 <= hour < 22 else None
