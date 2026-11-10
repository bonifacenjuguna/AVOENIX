"""Emoji intelligence: decide *whether* to use an emoji, *which*, and *where*. Often the answer is none.

Inputs considered: personality profile (allowed / level / formality), occasion, emotional situation of the user,
the emoji the user recently used, and the emoji AVOENIX itself used recently (never repeat back-to-back).
Hard rules: never in errors, contradictions, refusals, unknown/underdetermined answers or when the user seems upset;
never more than one (two only for an enthusiastic user who is using several themselves).
"""

from __future__ import annotations

import random

# occasion -> (candidate emoji, base probability multiplier)
POOLS: dict[str, tuple[list[str], float]] = {
    "greet": (["👋", "🙂", "😊"], 0.9),
    "farewell": (["👋", "🙂", "😊"], 0.8),
    "thanks_reply": (["😊", "🙂", "🙌"], 0.9),
    "celebrate": (["🎉", "😊", "👍"], 0.8),
    "answer": (["🙂", "👍"], 0.25),
    "stored": (["👍", "🙂"], 0.4),
    "learned": (["👍", "🙂"], 0.4),
    "social": (["🙂", "😊"], 0.8),
}
NEVER = {"error", "contradiction", "unsupported", "unknown", "underdetermined", "clarify", "rejected"}
USER_POSITIVE = {"😀", "😃", "😄", "😁", "😊", "🙂", "😍", "🥰", "😂", "🤣", "👍", "🎉", "❤", "🙏", "🙌", "👋"}


def choose(occasion: str, *, allowed: bool, level: float, formality: float, expressiveness: float, user_emoji: list[str], recent_emoji: list[str],
           user_valence: float, user_arousal: float, rng: random.Random) -> tuple[list[str], str]:
    """Return (emoji list, reason). Empty list means none."""
    if occasion in NEVER:
        return [], f"never used for {occasion}"
    if not allowed:
        return [], "emoji disabled by user preference"
    if occasion not in POOLS:
        return [], "no pool for this occasion"
    if user_valence < -0.3:
        return [], "user seems upset"
    pool, mult = POOLS[occasion]
    p = level * mult * (1.0 - 0.8 * max(0.0, formality - 0.5) * 2)       # formal registers suppress emoji
    p *= 0.8 + 0.4 * expressiveness
    if user_emoji:
        p = min(1.0, p * 1.5)
    p = max(0.0, min(1.0, p))
    if rng.random() >= p:
        return [], f"no emoji (probability {p:.2f})"
    mirrored = [e for e in user_emoji if e in USER_POSITIVE and e not in recent_emoji[:2]]
    candidates = [e for e in pool if e not in recent_emoji[:2]] or pool
    if mirrored and occasion in ("greet", "thanks_reply", "celebrate", "social", "answer", "stored") and rng.random() < 0.6:
        choice, why = mirrored[0], "mirrors the user's own emoji"
    else:
        choice, why = rng.choice(candidates), f"fits occasion '{occasion}'"
    out = [choice]
    if level > 0.7 and expressiveness > 0.6 and len(user_emoji) >= 2 and rng.random() < 0.4:
        out.append(rng.choice([e for e in candidates if e != choice] or candidates))
        why += "; user is using several"
    return out, why
