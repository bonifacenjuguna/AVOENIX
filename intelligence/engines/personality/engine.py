"""Personality Engine: a stable base character, adapted per user, per message and per emotional situation.

Base character (v0.0.0): warm, plain-spoken, moderately concise, lightly expressive, rarely takes initiative.
Adaptation inputs, in order of authority:
  1. explicit user preferences (stored through the Memory Engine: ``style.formality``, ``style.emoji``, ``style.length``, ``style.warmth``)
  2. observed user style (running averages of message length, informality and emoji use)
  3. the emotional situation of the current message (e.g. distress => no emoji, calmer, warmer)
The result is a ``StyleProfile`` with human-readable ``reasons`` so any style choice can be inspected. Style never changes facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ...core.contracts import EmotionSignal, LanguageResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.types import Scope
from ..memory.engine import MemoryEngine

BASE = {"formality": 0.45, "warmth": 0.6, "conciseness": 0.5, "expressiveness": 0.4, "initiative": 0.25, "emoji_affinity": 0.25}
OBS_KEY = "observed.style"
FORMAL_MARKERS = {"please", "kindly", "would", "could", "regards", "sir", "madam", "thank", "appreciate"}
INFORMAL_MARKERS = {"hey", "hi", "yo", "lol", "gonna", "wanna", "gotta", "cuz", "btw", "pls", "thx", "yeah", "yep", "nope", "dude", "bro", "omg", "haha"}


@dataclass
class StyleProfile:
    formality: float
    warmth: float
    conciseness: float
    expressiveness: float
    initiative: float
    emoji_level: float                  # 0 = none ... 1 = frequent
    emoji_allowed: bool = True
    reasons: list[str] = field(default_factory=list)
    recent_user_emoji: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class PersonalityEngine(Engine):
    info = EngineInfo(
        key="personality", name="Personality Engine", status=EngineStatus.PARTIAL,
        summary="Base character plus per-user adaptation (explicit preferences, observed style, emotional situation) as an inspectable StyleProfile.",
        depends_on=("memory", "emotion"),
        capabilities=("five style dimensions + emoji level", "explicit preference overrides", "running observation of user style (stored in memory)",
                      "emotion-aware moderation", "explainable reasons list"),
        limitations=("Only English surface cues are observed.", "Observed style is a crude running average, not a user model.",
                     "No long-term personality drift or multiple selectable personas in v0.0.0."),
    )

    def self_check(self) -> tuple[bool, str]:
        p = self.profile(Scope("_selfcheck", "_selfcheck"))
        ok = all(0.0 <= v <= 1.0 for v in (p.formality, p.warmth, p.conciseness, p.expressiveness))
        return ok, "profile values within [0, 1]" if ok else "profile value outside [0, 1]"

    def __init__(self, memory: MemoryEngine):
        super().__init__()
        self.memory = memory

    # ---- observation ------------------------------------------------------------------------------------------------
    def _observed(self, scope: Scope) -> dict:
        rows = self.memory.repo(scope).select("memories", {"category": "preference", "key": OBS_KEY, "status": "active"})
        return (rows[0].get("data") or {}) if rows else {}

    @traced("observe")
    def observe(self, scope: Scope, lr: LanguageResult) -> dict:
        """Update running style statistics for this user from one message. Rows are updated in place (no row growth)."""
        words = [t["text"].lower() for t in lr.tokens if t.get("pos") != "PUNCT"]
        md = lr.packet.metadata
        if not words:
            return self._observed(scope)
        st = self._observed(scope) or {"n": 0, "avg_words": 0.0, "informal": 0.4, "emoji_rate": 0.0, "recent_emoji": []}
        n = st["n"] + 1
        a = max(0.15, 1.0 / n)                                         # EMA with a floor so it still adapts later
        informal_hits = sum(w in INFORMAL_MARKERS for w in words) + (0.5 if md.get("elongations") else 0) + (0.5 if lr.packet.original.islower() and len(words) > 3 else 0)
        formal_hits = sum(w in FORMAL_MARKERS for w in words) + (0.5 if lr.packet.original[:1].isupper() and lr.packet.original.rstrip()[-1:] in ".?!" else 0)
        score = _clamp(0.4 + 0.25 * informal_hits - 0.25 * formal_hits)
        has_emoji = 1.0 if md.get("emoji_count", 0) else 0.0
        st.update(n=n, avg_words=(1 - a) * st["avg_words"] + a * len(words), informal=(1 - a) * st["informal"] + a * score,
                  emoji_rate=(1 - a) * st["emoji_rate"] + a * has_emoji)
        if md.get("emoji"):
            st["recent_emoji"] = (list(md["emoji"]) + st.get("recent_emoji", []))[:8]
        rows = self.memory.repo(scope).select("memories", {"category": "preference", "key": OBS_KEY, "status": "active"})
        if rows:
            self.memory.repo(scope).update("memories", {"id": rows[0]["id"]}, {"data": st, "updated_at": self.memory.clock.now().isoformat()})
        else:
            self.memory.remember(scope, "preference", "Observed communication style statistics", key=OBS_KEY, data=st, importance=0.2, source="observation")
        return st

    # ---- profile ------------------------------------------------------------------------------------------------------
    @traced("profile")
    def profile(self, scope: Scope, emotion: EmotionSignal | None = None) -> StyleProfile:
        prefs = self.memory.preferences(scope)
        obs = self._observed(scope)
        p = dict(BASE)
        reasons: list[str] = []
        emoji_level = BASE["emoji_affinity"]
        if obs.get("n", 0) >= 2:
            p["formality"] = _clamp(0.5 * BASE["formality"] + 0.5 * (1 - obs["informal"]))
            reasons.append(f"mirrors user's observed formality ({obs['informal']:.2f} informal over {obs['n']} messages)")
            if obs["avg_words"] < 6:
                p["conciseness"] = _clamp(p["conciseness"] + 0.2)
                reasons.append("user writes short messages -> more concise")
            elif obs["avg_words"] > 25:
                p["conciseness"] = _clamp(p["conciseness"] - 0.2)
                reasons.append("user writes long messages -> fuller replies")
            emoji_level = _clamp(0.15 + 0.7 * obs["emoji_rate"])
            if obs["emoji_rate"] > 0.3:
                p["expressiveness"] = _clamp(p["expressiveness"] + 0.15)
                reasons.append("user uses emoji often")
        allowed = True
        f = prefs.get("style.formality")
        if f in ("formal", "casual"):
            p["formality"] = 0.85 if f == "formal" else 0.15
            reasons.append(f"explicit preference: {f}")
        length = prefs.get("style.length")
        if length in ("short", "long"):
            p["conciseness"] = 0.9 if length == "short" else 0.15
            reasons.append(f"explicit preference: {length} answers")
        w = prefs.get("style.warmth")
        if w in ("warm", "neutral"):
            p["warmth"] = 0.85 if w == "warm" else 0.3
            reasons.append(f"explicit preference: {w} tone")
        e = prefs.get("style.emoji")
        if e == "none":
            allowed, emoji_level = False, 0.0
            reasons.append("explicit preference: no emoji")
        elif e == "more":
            emoji_level = _clamp(max(emoji_level, 0.6))
            reasons.append("explicit preference: more emoji")
        if emotion is not None:
            if emotion.label == "negative" and (emotion.arousal > 0.6 or emotion.flags.get("distress_words")):
                p["warmth"] = _clamp(p["warmth"] + 0.2); p["expressiveness"] = _clamp(p["expressiveness"] - 0.2); p["initiative"] = 0.0
                emoji_level = 0.0
                reasons.append("user seems upset -> calm, warm, no emoji")
            elif emotion.label == "negative":
                emoji_level = _clamp(emoji_level - 0.2)
                p["warmth"] = _clamp(p["warmth"] + 0.1)
                reasons.append("negative tone -> softer, fewer emoji")
            elif emotion.label == "positive" and emotion.certainty > 0.4:
                p["expressiveness"] = _clamp(p["expressiveness"] + 0.1)
                emoji_level = _clamp(emoji_level + 0.1)
                reasons.append("positive tone -> slightly livelier")
        return StyleProfile(formality=p["formality"], warmth=p["warmth"], conciseness=p["conciseness"], expressiveness=p["expressiveness"],
                            initiative=p["initiative"], emoji_level=emoji_level if allowed else 0.0, emoji_allowed=allowed, reasons=reasons,
                            recent_user_emoji=list(obs.get("recent_emoji", []))[:5])
