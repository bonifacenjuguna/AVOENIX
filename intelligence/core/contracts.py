"""Typed data contracts passed between engines.

Engines never reach into each other's internals; they exchange these dataclasses (all JSON-serialisable
through ``to_dict``) or ACR documents. This is what keeps the twelve engines decoupled and individually testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from ..representation import ACRDocument


@dataclass
class InputPacket:
    original: str
    text: str                                   # normalised text handed to language understanding
    language: str                               # always "en" in v0.0.1
    language_confidence: float
    language_method: str
    received_at: datetime
    channel: str = "api"
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["received_at"] = self.received_at.isoformat()
        return d


@dataclass
class LanguageResult:
    packet: InputPacket
    doc: ACRDocument
    tokens: list[dict]
    corrections: list[dict]
    coverage: float
    interpretation_confidence: float
    confidence_components: dict[str, float]
    notes: list[str]
    speech_acts: list[str]
    sentences: int
    math: dict | None = None
    unsupported: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tokens": self.tokens, "corrections": self.corrections, "coverage": round(self.coverage, 3),
            "interpretation_confidence": round(self.interpretation_confidence, 3),
            "confidence_components": {k: round(v, 3) for k, v in self.confidence_components.items()},
            "notes": self.notes, "speech_acts": self.speech_acts, "sentences": self.sentences,
            "math": self.math, "unsupported": self.unsupported, "acr": self.doc.to_dict(),
        }


@dataclass
class Evidence:
    """One piece of support used in a reasoning conclusion."""

    kind: str                   # user_statement | knowledge | memory | derived | arithmetic | context
    statement: str              # rendered, human-readable
    source: str | None = None   # provenance source type
    ref: str | None = None
    confidence: float = 1.0
    data: dict[str, Any] | None = None   # structured fact (predicate, labelled args, polarity) so responses can restate premises faithfully

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Conclusion:
    """Outcome of reasoning about a question or statement."""

    status: str                         # answered | yes | no | unknown | contradiction | underdetermined | needs_clarification | error | unsupported | consistent | inconsistent
    strategy: str
    answer: dict[str, Any] = field(default_factory=dict)      # structured, language-neutral answer
    confidence: float | None = None
    steps: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    derived_facts: list[dict] = field(default_factory=list)   # candidate propositions (ACR dicts) derived by this reasoning
    notes: list[str] = field(default_factory=list)
    query: dict[str, Any] = field(default_factory=dict)       # what was asked/stated (predicate, term labels, adjective...) so a response can restate it faithfully

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class ReasoningResult:
    conclusions: list[Conclusion]
    strategies_tried: list[dict]
    elapsed_ms: float
    primary: Conclusion | None = None

    def to_dict(self) -> dict:
        return {"conclusions": [c.to_dict() for c in self.conclusions], "strategies_tried": self.strategies_tried,
                "elapsed_ms": round(self.elapsed_ms, 3), "primary": self.primary.to_dict() if self.primary else None}


@dataclass
class EmotionSignal:
    valence: float                      # -1..1
    arousal: float                      # 0..1
    label: str                          # positive | negative | neutral | mixed
    emotions: list[dict]                # [{"name": "joy", "score": 0.6}]
    certainty: float                    # how much evidence supports this reading (not a probability of truth)
    cues: list[str]
    flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContentPlan:
    """Language-neutral description of what a response must communicate (the Response Engine realises it)."""

    objective: str                       # answer | confirm | deny | inform_unknown | acknowledge | greet | farewell | thank | social | clarify | refuse | error | store_ack | explain
    messages: list[dict] = field(default_factory=list)       # ordered semantic messages, each {"type": ..., ...}
    certainty: str = "certain"           # certain | likely | uncertain | unknown
    explanation: list[str] = field(default_factory=list)
    follow_up: dict | None = None        # {"type": "ask_clarification", ...}
    tone_hint: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResponseResult:
    text: str
    plan: ContentPlan
    variation: dict[str, Any]            # which choices were made, for repetition analysis (real, recorded)
    emoji: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"text": self.text, "plan": self.plan.to_dict(), "variation": self.variation, "emoji": self.emoji}


@dataclass
class StageTrace:
    engine: str
    operation: str
    ms: float
    ok: bool
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ms"] = round(self.ms, 3)
        return d


@dataclass
class TurnResult:
    response: str
    conversation_id: str | None
    status: str                           # ok | partial | error
    trace: list[StageTrace]
    total_ms: float
    understanding: dict[str, Any]
    reasoning: dict[str, Any] | None
    confidence: dict[str, Any]
    emotion: dict[str, Any] | None
    context: dict[str, Any]
    memory: dict[str, Any]
    response_meta: dict[str, Any]
    errors: list[dict] = field(default_factory=list)
    turn_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id, "response": self.response, "conversation_id": self.conversation_id, "status": self.status,
            "total_ms": round(self.total_ms, 3), "trace": [t.to_dict() for t in self.trace], "understanding": self.understanding,
            "reasoning": self.reasoning, "confidence": self.confidence, "emotion": self.emotion, "context": self.context,
            "memory": self.memory, "response_meta": self.response_meta, "errors": self.errors,
        }
