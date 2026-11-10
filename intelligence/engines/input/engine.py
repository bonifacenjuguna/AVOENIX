"""Input Processing Engine.

Receives raw input, validates it, normalises it, identifies whether it is within the supported
language scope (English only in v0.0.0), records input metadata and hands a structured packet to
language understanding. Independent of any frontend or transport.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import datetime

from ...core.contracts import InputPacket
from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import InputError, UnsupportedLanguageError
from ...core.types import Clock, SystemClock

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = re.compile(r"[​‌⁠﻿]")      # NOT ‍: it joins emoji sequences
_SPACES = re.compile(r"[ \t  -   　]+")

# Function-word profiles used for coarse language identification (authored, tiny, closed-class only).
_FUNCTION_WORDS = {
    "en": set("the a an and or but of to in on at for with from by is are was were be been am do does did have has had i you he she it we they my your his her its our their this that these those what who where when why how not no yes if then than because so can will would should could may might".split()),
    "es": set("el la los las un una unos unas y o pero de del al en con por para es son era fue ser estar yo tu usted nosotros ellos que como cuando donde porque no si muy mas hola gracias".split()),
    "fr": set("le la les un une des et ou mais de du au aux en dans avec pour par est sont etait etre je tu il elle nous vous ils elles que qui comment quand ou pourquoi ne pas oui non tres bonjour merci".split()),
    "de": set("der die das ein eine und oder aber von zu in im mit fur auf ist sind war sein ich du er sie es wir ihr nicht kein ja nein wie was wer wo wann warum sehr hallo danke".split()),
    "sw": set("na ya wa kwa ni la za katika hii huyu yule sana habari asante karibu sijui nina una ana tuna wana mimi wewe yeye sisi".split()),
    "pt": set("o a os as um uma e ou mas de do da em com por para e sao era ser eu voce ele ela nos que como quando onde porque nao sim muito ola obrigado".split()),
}
# Words that are also ordinary English must not count as evidence for another language ("as", "no", "me", "a" ...).
_EN_EXTRA = set("as like more most less also just very too there here which while about into over out up down off all any some one two so as "
                "me no on an he him her she more than then now only even much many each both such own same other another after before again "
                "still ever never always often once twice".split())
_FUNCTION_WORDS["en"] |= _EN_EXTRA
for _l in [k for k in _FUNCTION_WORDS if k != "en"]:
    _FUNCTION_WORDS[_l] -= _FUNCTION_WORDS["en"]
_ENGLISH_LETTER_PAIRS = ("th", "he", "in", "er", "an", "re", "on", "at", "en", "nd", "ti", "es", "or", "te", "of", "ed", "is", "it", "al", "ar")


class InputProcessingEngine(Engine):
    info = EngineInfo(
        key="input", name="Input Processing Engine", status=EngineStatus.IMPLEMENTED,
        summary="Validates, normalises and profiles incoming text; scopes it to supported English.",
        depends_on=(),
        capabilities=("type/size validation", "Unicode NFKC normalisation", "control/zero-width character removal",
                      "whitespace collapsing", "elongation and shouting metadata", "function-word + script language identification",
                      "structured packet hand-off"),
        limitations=("Language identification is coarse (script + closed-class word profiles); very short inputs default to English "
                     "with low confidence.", "Only English is supported; other recognised languages are rejected with a clear error."),
    )

    def __init__(self, *, max_chars: int = 4000, clock: Clock | None = None, enforce_language: bool = True):
        super().__init__()
        self.max_chars = max_chars
        self.clock = clock or SystemClock()
        self.enforce_language = enforce_language

    def self_check(self) -> tuple[bool, str]:
        pkt = self.process("Hello   there!!!")
        ok = pkt.text == "Hello there!!!" and pkt.language == "en"
        return ok, "normalisation + language scope probe " + ("passed" if ok else "FAILED")

    # ---- language identification --------------------------------------------------------------------
    def identify_language(self, text: str) -> tuple[str, float, str]:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return "und", 0.0, "no_letters"
        latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
        if latin / len(letters) < 0.6:
            return "other_script", 0.9, "script"
        words = re.findall(r"[a-zA-Z']+", text.lower())
        words = [unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode() for w in words]
        if not words:
            return "und", 0.0, "no_words"
        scores = {lang: sum(1 for w in words if w in fw) / len(words) for lang, fw in _FUNCTION_WORDS.items()}
        best_other = max(((l, s) for l, s in scores.items() if l != "en"), key=lambda x: x[1])
        en = scores["en"]
        accents = sum(1 for c in text if c in "áéíóúñçãõàèìòùâêîôûäöüß¿¡")
        if len(words) < 3:
            if best_other[1] > 0 and best_other[1] >= 0.5 and en == 0:
                return best_other[0], 0.4, "short_function_words"
            return "en", 0.5, "short_default"
        if best_other[1] > en and best_other[1] >= 0.25 and best_other[1] * len(words) >= 2:      # a single shared word ("yo") is not evidence
            return best_other[0], min(0.95, 0.5 + best_other[1]), "function_words"
        if en == 0 and accents:
            return best_other[0], 0.5, "accents"
        pairs = sum(text.lower().count(p) for p in _ENGLISH_LETTER_PAIRS) / max(1, len(text))
        conf = min(0.98, 0.45 + en * 0.9 + min(pairs, 0.2))
        return "en", conf, "function_words"

    # ---- main entry ------------------------------------------------------------------------------------
    @traced("process")
    def process(self, raw: object, *, channel: str = "api", metadata: dict | None = None) -> InputPacket:
        if raw is None or not isinstance(raw, str):
            raise InputError("input must be a string", details={"type": type(raw).__name__})
        warnings: list[str] = []
        if len(raw) > self.max_chars * 4:
            raise InputError(f"input too long ({len(raw)} characters)", details={"max_chars": self.max_chars})
        text = unicodedata.normalize("NFKC", raw)
        text = _CONTROL.sub("", text)
        text = _ZERO_WIDTH.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n+", " ", text)
        text = _SPACES.sub(" ", text).strip()
        text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        if not text:
            raise InputError("input is empty after normalisation")
        if len(text) > self.max_chars:
            raise InputError(f"input too long ({len(text)} > {self.max_chars} characters)", details={"max_chars": self.max_chars})
        letters = [c for c in text if c.isalpha()]
        caps_ratio = (sum(1 for c in letters if c.isupper()) / len(letters)) if len(letters) >= 4 else 0.0
        elongation = len(re.findall(r"(.)\1{2,}", text))
        emoji = [c for c in text if ord(c) >= 0x1F300 or c in "❤✨✅❌☺☹"]
        punct_runs = len(re.findall(r"[!?]{2,}", text))
        lang, conf, method = self.identify_language(text)
        if self.enforce_language and lang not in ("en", "und"):
            raise UnsupportedLanguageError(
                "AVOENIX v0.0.0 supports English only", details={"detected": lang, "confidence": round(conf, 2), "method": method})
        if lang == "und":
            warnings.append("no alphabetic content detected")
        # collapse shouting for downstream analysis but keep the evidence in metadata
        meta = {
            "chars": len(text), "words": len(text.split()), "caps_ratio": round(caps_ratio, 3), "shouting": caps_ratio > 0.7 and len(letters) >= 6,
            "elongations": elongation, "emoji": emoji[:8], "emoji_count": len(emoji), "exclamation_runs": punct_runs,
            "question": text.rstrip().endswith("?"), "truncated": False,
        }
        if metadata:
            meta["client"] = {k: v for k, v in metadata.items() if isinstance(k, str) and len(k) < 40}
        return InputPacket(original=raw, text=text, language="en", language_confidence=conf if lang == "en" else 0.0,
                           language_method=method, received_at=self.clock.now(), channel=channel, metadata=meta, warnings=warnings)
