"""Emotion / Sentiment Engine: lexicon-and-rule affect analysis (valence, arousal, emotion categories, certainty).

Method: a small authored affect lexicon (word -> valence, arousal, emotion), negation scope (3 tokens), intensifiers and
diminishers, contrastive "but" re-weighting, emoji and punctuation cues, shouting and elongation. Scores are cue-based
estimates of the *expressed* affect in text, not a diagnosis of how a person feels. ``certainty`` reflects how much
cue evidence there was (0 for text without affect cues) and is not a probability.
"""

from __future__ import annotations

import math

from ...core.contracts import EmotionSignal, LanguageResult
from ...core.engine import Engine, EngineInfo, EngineStatus, traced

# word -> (valence -1..1, arousal 0..1, emotion)
_A = {}
def _add(emotion, valence, arousal, words):
    for w in words.split():
        _A[w] = (valence, arousal, emotion)

_add("joy", 0.8, 0.6, "happy glad delighted thrilled excited wonderful fantastic amazing awesome great excellent love loved lovely brilliant perfect beautiful joy joyful fun enjoy enjoyed cheerful pleased")
_add("joy", 0.5, 0.3, "good nice fine cool pleasant happy-ish okay-ish like liked well better best")
_add("gratitude", 0.7, 0.4, "thanks thank thankful grateful appreciate appreciated cheers")
_add("sadness", -0.7, 0.3, "sad unhappy depressed miserable heartbroken sorry lonely gloomy down upset hurt cry crying grief tearful hopeless disappointed")
_add("anger", -0.8, 0.9, "angry furious mad hate hated annoyed annoying irritated outraged livid rage disgusting stupid idiot terrible awful horrible worst useless")
_add("frustration", -0.6, 0.7, "frustrated frustrating stuck broken fail failed failing wrong bug error problem issue ridiculous pointless waste wasted")
_add("fear", -0.7, 0.8, "afraid scared terrified fear worried worry anxious nervous panic dread frightened")
_add("surprise", 0.1, 0.8, "surprised shocked wow whoa unexpected astonished unbelievable")
_add("confusion", -0.3, 0.4, "confused confusing unclear puzzled lost baffled unsure")
_add("negative", -0.5, 0.4, "bad poor boring tired exhausted bored weak difficult hard painful slow")
_add("positive", 0.5, 0.3, "easy helpful useful smart clever calm relaxed relieved hopeful proud safe")
NEGATORS = {"not", "no", "never", "n't", "nothing", "none", "hardly", "without", "cannot", "neither"}
INTENSIFIERS = {"very": 1.4, "really": 1.4, "so": 1.35, "extremely": 1.7, "totally": 1.5, "absolutely": 1.6, "incredibly": 1.6, "super": 1.5, "too": 1.3, "quite": 1.2, "deeply": 1.5, "truly": 1.4}
DIMINISHERS = {"slightly": 0.6, "somewhat": 0.7, "kinda": 0.7, "bit": 0.7, "little": 0.7, "barely": 0.5, "fairly": 0.85}
EMOJI = {
    "😀": (0.8, 0.6, "joy"), "😃": (0.8, 0.6, "joy"), "😄": (0.8, 0.6, "joy"), "😁": (0.8, 0.6, "joy"), "😊": (0.7, 0.4, "joy"), "🙂": (0.4, 0.2, "joy"),
    "😍": (0.9, 0.7, "joy"), "🥰": (0.9, 0.5, "joy"), "😂": (0.7, 0.7, "joy"), "🤣": (0.7, 0.8, "joy"), "👍": (0.6, 0.3, "positive"), "🎉": (0.8, 0.8, "joy"),
    "❤": (0.8, 0.5, "joy"), "🙏": (0.5, 0.3, "gratitude"), "😢": (-0.7, 0.4, "sadness"), "😭": (-0.8, 0.7, "sadness"), "😞": (-0.6, 0.2, "sadness"),
    "😡": (-0.8, 0.9, "anger"), "😠": (-0.8, 0.8, "anger"), "🤬": (-0.9, 1.0, "anger"), "😱": (-0.6, 0.9, "fear"), "😨": (-0.6, 0.8, "fear"),
    "😕": (-0.3, 0.3, "confusion"), "🤔": (0.0, 0.3, "confusion"), "😮": (0.1, 0.8, "surprise"), "😳": (-0.1, 0.7, "surprise"), "👎": (-0.6, 0.3, "negative"),
    "😐": (-0.1, 0.1, "negative"), "😒": (-0.4, 0.3, "negative"), "🙄": (-0.4, 0.4, "negative"),
}


class EmotionEngine(Engine):
    info = EngineInfo(
        key="emotion", name="Emotion / Sentiment Engine", status=EngineStatus.PARTIAL,
        summary="Lexicon + rule affect analysis: valence, arousal, emotion categories, negation, intensity, emoji and punctuation cues.",
        depends_on=("language",),
        capabilities=("valence/arousal estimation", "negation scope and intensifiers", "emoji and punctuation cues", "contrast clauses ('but')", "mixed-affect detection",
                      "explicit certainty = amount of cue evidence"),
        limitations=("A ~200-word authored lexicon: unusual wording, slang, irony and sarcasm are not understood.",
                     "No speaker modelling: it reports expressed affect in this message only.",
                     "Not validated against a labelled corpus in v0.0.0 (see evaluation docs)."),
    )

    @traced("analyze")
    def self_check(self) -> tuple[bool, str]:
        from ..input.engine import InputProcessingEngine
        from ..language.engine import LanguageEngine
        lr = LanguageEngine().analyze(InputProcessingEngine().process("I am so happy today!"))
        pos = self.analyze(lr)
        neg = self.analyze(LanguageEngine().analyze(InputProcessingEngine().process("I am not happy")))
        ok = pos.valence > 0 > neg.valence
        return ok, "polarity probe: positive text > 0 and negated text < 0" if ok else f"polarity probe failed ({pos.valence:.2f}, {neg.valence:.2f})"

    def analyze(self, lr: LanguageResult) -> EmotionSignal:
        toks = [t for t in lr.tokens if t.get("pos") != "PUNCT"]
        md = lr.packet.metadata
        cues: list[str] = []
        scored: list[tuple[float, float, str, int]] = []      # valence, arousal, emotion, token index
        contrast_at = next((i for i, t in enumerate(toks) if t["lemma"] in ("but", "however", "although") and t["pos"] in ("CCONJ", "SCONJ", "ADV")), None)
        for i, t in enumerate(toks):
            lemma = t["lemma"].lower()
            hit = _A.get(lemma) or _A.get(t["text"].lower())
            if not hit:
                continue
            v, a, e = hit
            mult, negated = 1.0, False
            for back in range(1, 4):
                if i - back < 0:
                    break
                prev = toks[i - back]
                pl = prev["lemma"].lower()
                if pl in NEGATORS or prev["text"].lower() in NEGATORS or prev["text"].lower().endswith("n't"):
                    negated = True
                elif pl in INTENSIFIERS:
                    mult *= INTENSIFIERS[pl]
                elif pl in DIMINISHERS:
                    mult *= DIMINISHERS[pl]
            if negated:
                v, e = -0.6 * v, ("negative" if v > 0 else "relief" if e in ("anger", "sadness", "fear") else e)
                cues.append(f"negated '{t['text']}'")
            else:
                cues.append(f"'{t['text']}'")
            if mult != 1.0:
                cues.append(f"intensity x{mult:.2f} on '{t['text']}'")
            v = max(-1.0, min(1.0, v * mult))
            scored.append((v, min(1.0, a * (1 + 0.2 * (mult - 1))), e, i))
        for ch in md.get("emoji", []):
            if ch in EMOJI:
                v, a, e = EMOJI[ch]
                scored.append((v, a, e, len(toks)))
                cues.append(f"emoji {ch}")
        if not scored:
            flags = self._flags(md, lr, toks)
            return EmotionSignal(valence=0.0, arousal=0.25 + (0.2 if flags.get("shouting") else 0), label="neutral", emotions=[], certainty=0.0,
                                 cues=["no affect cues"], flags=flags)
        weights = []
        for v, a, e, i in scored:
            w = 1.0
            if contrast_at is not None:
                w = 1.5 if i > contrast_at else 0.6      # "but" foregrounds what follows
            weights.append(w)
        wsum = sum(weights)
        valence = sum(s[0] * w for s, w in zip(scored, weights)) / wsum
        arousal = sum(s[1] * w for s, w in zip(scored, weights)) / wsum
        bangs = md.get("exclamation_runs", 0)
        text_bangs = sum(1 for t in lr.tokens if t.get("text") == "!")
        if text_bangs or bangs:
            arousal = min(1.0, arousal + 0.1 + 0.05 * min(3, bangs))
            cues.append("exclamation")
        if md.get("shouting"):
            arousal = min(1.0, arousal + 0.2)
            cues.append("capitals")
        pos_mass = sum(max(0, s[0]) * w for s, w in zip(scored, weights))
        neg_mass = sum(max(0, -s[0]) * w for s, w in zip(scored, weights))
        mixed = pos_mass > 0.4 and neg_mass > 0.4 and min(pos_mass, neg_mass) / max(pos_mass, neg_mass) > 0.5
        after = [v for v, a, e, i in scored if contrast_at is not None and i > contrast_at]
        if mixed and after and abs(sum(after) / len(after)) > 0.2:
            mixed_label = False        # "X but Y": the clause after 'but' decides the overall label; mixed stays flagged
            valence = sum(after) / len(after) * 0.5 + valence * 0.5 if valence * (sum(after) / len(after)) < 0 else valence
        else:
            mixed_label = mixed
        label = "mixed" if mixed_label else (("positive" if (after_sign := (sum(after) / len(after) if after and mixed else valence)) > 0.15 else "negative" if after_sign < -0.15 else "neutral"))
        by_e: dict[str, float] = {}
        for (v, a, e, i), w in zip(scored, weights):
            by_e[e] = by_e.get(e, 0.0) + abs(v) * w
        top = sorted(by_e.items(), key=lambda kv: -kv[1])[:3]
        norm = sum(x for _, x in top) or 1.0
        emotions = [{"name": n, "score": round(x / norm, 3)} for n, x in top if n not in ("positive", "negative") or len(top) == 1]
        certainty = 1 - math.exp(-0.9 * len(scored))
        flags = self._flags(md, lr, toks)
        flags["mixed"] = mixed
        return EmotionSignal(valence=round(valence, 3), arousal=round(arousal, 3), label=label, emotions=emotions, certainty=round(certainty, 3), cues=cues, flags=flags)

    @staticmethod
    def _flags(md: dict, lr: LanguageResult, toks: list[dict]) -> dict:
        return {"shouting": bool(md.get("shouting")), "elongation": md.get("elongations", 0) > 0, "emoji_used": md.get("emoji", []),
                "question": bool(md.get("question")), "distress_words": any(t["lemma"].lower() in ("hopeless", "panic", "terrified", "heartbroken") for t in toks)}
