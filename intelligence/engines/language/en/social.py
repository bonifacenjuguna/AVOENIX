"""Structural detection of social/phatic speech acts.

Detection is structural over the parsed sentence (interjection lexicon entries with formality and
warmth values, copular "how are you" frames, "thank you", "good <part of day>", "nice to meet you",
"see you later"); there is no list of whole canned utterances.
"""

from __future__ import annotations

from . import lexicon as L
from .syntax import ParsedSentence

_PARTS_OF_DAY = {"morning": "greet", "afternoon": "greet", "evening": "greet", "night": "farewell", "day": "greet"}


def _words(sent: ParsedSentence) -> list[str]:
    return [t.norm for t in sent.tokens if t.kind in ("word", "clitic", "number", "abbr")]


def detect_social(sent: ParsedSentence) -> tuple[str, dict] | None:
    words = _words(sent)
    if not words:
        return None
    feats: dict = {}
    first_clause = sent.clauses[0] if sent.clauses else None
    # --- "how are you / how is it going / how do you do / how have you been" -------------------
    if first_clause is not None and first_clause.wh_adv == "how" and first_clause.subject is not None and first_clause.vg is not None:
        sub = first_clause.subject.head.norm if first_clause.subject.head else ""
        lemma = first_clause.vg.lemma
        if sub == "you" and lemma in ("be", "do", "feel", "have"):
            return "social_inquiry", {"target": "addressee", "formality": 0.5, "warmth": 0.6}
        if sub in ("it", "everything", "things") and (lemma in ("go", "be")):
            return "social_inquiry", {"target": "addressee", "formality": 0.3, "warmth": 0.5}
    if words[:2] == ["what", "'s"] and "up" in words or words[:3] == ["what", "is", "up"] or words[:2] == ["whats", "up"] or words == ["sup"]:
        return "social_inquiry", {"target": "addressee", "formality": 0.0, "warmth": 0.4}
    # --- thanks -----------------------------------------------------------------------------------
    if "thanks" in words or "thx" in words or ("thank" in words and "you" in words) or "cheers" in words and len(words) <= 2:
        return "thank", {"formality": 0.5 if "thank" in words else 0.2, "warmth": 0.7, "emphatic": "very" in words or "much" in words or "so" in words or "lot" in words}
    if "appreciate" in words and ("it" in words or "that" in words) and len(words) <= 5:
        return "thank", {"formality": 0.5, "warmth": 0.7}
    if words[:2] in (["you", "'re"], ["you", "are"]) and "welcome" in words:
        return "acknowledge", {"role": "youre_welcome", "formality": 0.4, "warmth": 0.6}
    if "welcome" in words and len(words) <= 2:
        return "greet", {"formality": 0.6, "warmth": 0.7, "role": "welcome"}
    # --- apologies ----------------------------------------------------------------------------------
    if words and words[0] in ("sorry", "apologies", "pardon") and len(words) <= 6:
        return "apologize", {"formality": 0.5, "warmth": 0.5}
    if "apologize" in words or "apologise" in words or ("my" in words and "bad" in words and len(words) <= 3):
        return "apologize", {"formality": 0.6, "warmth": 0.5}
    # --- greetings / farewells ------------------------------------------------------------------------
    if len(words) >= 2 and words[0] in ("good", "nice", "happy") and words[1] in _PARTS_OF_DAY and (len(words) == 2 or words[2] in ("to", "everyone", "all", "there")):
        return _PARTS_OF_DAY[words[1]], {"formality": 0.7, "warmth": 0.6, "part_of_day": words[1]}
    if words[:3] == ["nice", "to", "meet"] or words[:3] == ["pleased", "to", "meet"] or words[:3] == ["great", "to", "meet"] or words[:3] == ["good", "to", "see"]:
        return "greet", {"formality": 0.6, "warmth": 0.7, "role": "meeting"}
    if "see" in words and "you" in words and any(w in words for w in ("later", "soon", "tomorrow", "then", "around")):
        return "farewell", {"formality": 0.3, "warmth": 0.6}
    if "take" in words and "care" in words and len(words) <= 3:
        return "farewell", {"formality": 0.4, "warmth": 0.8}
    if "have" in words and "a" in words and ("good" in words or "nice" in words or "great" in words) and any(w in words for w in ("day", "night", "weekend", "evening")) and len(words) <= 6:
        return "farewell", {"formality": 0.5, "warmth": 0.7}
    # --- interjections --------------------------------------------------------------------------------
    marker_words = [t.norm for t in sent.discourse_markers]
    lead = marker_words[0] if marker_words else (words[0] if len(words) <= 3 else None)
    if lead in L.INTERJECTIONS:
        act, formality, warmth = L.INTERJECTIONS[lead]
        if act in ("greet", "farewell", "affirm", "deny", "acknowledge", "exclaim", "apologize"):
            return act, {"formality": formality, "warmth": warmth, "word": lead}
        if act == "thank_or_farewell":
            return "thank", {"formality": formality, "warmth": warmth}
        if act == "thank":
            return "thank", {"formality": formality, "warmth": warmth}
    return None
