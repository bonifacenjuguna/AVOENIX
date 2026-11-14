"""Shallow syntactic analysis over the language engine's tagged tokens: noun/verb/adjective/prepositional chunks and clauses.

This is deliberately a *statistical-free, rule-based chunker over POS tags*, repaired with the concept lexicon: the tagger is wrong on
unfamiliar words ("afford", "use" tagged as nouns), so a content word that the lexicon knows as a verb is promoted to VERB when its position
(after a modal/auxiliary/negation or a subject pronoun) says it is acting as one. The result is a list of :class:`Clause` objects with
subject, verb group (negation, tense, aspect, modality, voice-free), complements in order, subordinator and mood.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .lexicon import ConceptGraph, default_graph

MODALS = {"can": "ability", "could": "ability", "will": "future", "would": "conditional", "shall": "future", "should": "obligation",
          "may": "possibility", "might": "possibility", "must": "obligation"}
BE = {"be", "am", "is", "are", "was", "were", "been", "being"}
IRREGULAR_PAST = {"bought", "had", "went", "got", "lost", "spent", "gave", "took", "made", "ate", "drank", "ran", "sold", "paid", "found", "won", "left", "came", "saw", "said",
                  "told", "knew", "thought", "brought", "sent", "built", "kept", "lent", "met", "put", "read", "set", "wrote", "drove", "flew", "rode", "began", "was", "were", "did"}
SUBJECT_PRONOUNS = {"i", "you", "he", "she", "it", "we", "they"}
WH = {"what", "who", "whom", "where", "when", "why", "how", "which", "whose"}
SUBORDINATORS = {"if", "because", "when", "while", "although", "unless", "since", "that", "so", "whenever", "once", "after", "before", "as"}


@dataclass
class Chunk:
    kind: str                         # NP | VG | ADJP | PP | ADVP | WH | CC | SC | INTJ | NEG | OTHER
    start: int
    end: int                          # exclusive, token index
    text: str
    head: str = ""
    f: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "head": self.head, **({"f": self.f} if self.f else {})}


@dataclass
class Clause:
    sentence: int
    subject: Chunk | None
    vg: Chunk | None
    items: list[Chunk]
    wh: str | None = None
    subordinator: str | None = None
    inverted: bool = False
    elided_subject: bool = False
    punct_question: bool = False
    tokens: tuple[int, int] = (0, 0)
    text: str = ""

    @property
    def negated(self) -> bool:
        return bool(self.vg and self.vg.f.get("neg"))

    @property
    def tense(self) -> str:
        return (self.vg.f.get("tense") if self.vg else None) or "present"

    def nps(self) -> list[Chunk]:
        return [c for c in self.items if c.kind == "NP"]

    def pps(self, *preps: str) -> list[Chunk]:
        return [c for c in self.items if c.kind == "PP" and (not preps or c.f.get("prep") in preps)]

    def to_dict(self) -> dict:
        return {"text": self.text, "sentence": self.sentence, "subject": self.subject.to_dict() if self.subject else None,
                "verb_group": self.vg.to_dict() if self.vg else None, "items": [c.to_dict() for c in self.items], "wh": self.wh,
                "subordinator": self.subordinator, "negated": self.negated, "tense": self.tense, "inverted": self.inverted}


_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
          "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def words_to_number(text: str):
    """"thirty" -> 30, "twenty five" / "twenty-five" -> 25, "two hundred" -> 200; None if not a number phrase."""
    parts = text.lower().replace("-", " ").split()
    if not parts:
        return None
    total, cur = 0, 0
    for w in parts:
        if w in _UNITS:
            cur += _UNITS[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = max(cur, 1) * 100
        else:
            return None
    return total + cur


def _num(text: str):
    w = words_to_number(text)
    if w is not None and not text.replace(",", "").replace(".", "").isdigit():
        return w
    try:
        v = float(text.replace(",", ""))
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


class Chunker:
    def __init__(self, graph: ConceptGraph | None = None):
        self.graph = graph or default_graph()

    # ---- POS repair ------------------------------------------------------------------------------------------------------------------------
    def _repair(self, toks: list[dict]) -> list[dict]:
        out = [dict(t) for t in toks]
        for i, t in enumerate(out):
            lem = (t.get("lemma") or t["text"]).lower()
            if t["pos"] in ("NOUN", "ADJ", "PROPN") and self.graph.concepts_of(lem, "verb", strict=True) and t["pos"] != "PROPN":
                j = i - 1
                while j >= 0 and out[j]["pos"] in ("ADV", "PART"):
                    j -= 1
                prev = out[j] if j >= 0 else None
                is_verb_context = prev is not None and (prev["pos"] == "AUX" and (prev["lemma"] in MODALS or prev["lemma"] in ("do", "have", "be"))
                                                       or (prev["pos"] == "PRON" and prev["lemma"] in SUBJECT_PRONOUNS) or prev["pos"] == "PART" and prev["lemma"] == "to")
                nxt = out[i + 1]["pos"] if i + 1 < len(out) else None
                if is_verb_context and not (t["pos"] == "ADJ" and prev and prev["lemma"] == "be"):
                    t["pos"] = "VERB"
                elif prev and prev["pos"] == "PRON" and nxt in ("DET", "PRON", "NUM", "ADJ", "ADP"):
                    t["pos"] = "VERB"
            if lem and len(lem) > 3 and lem[-1] == lem[-2] and lem not in self.graph.lemma_index and lem[:-1] in self.graph.lemma_index:
                t["lemma"] = lem = lem[:-1]                                           # lemmatiser doubled the consonant ("cancell")
                out[i] = t
            if lem == "more" or t["text"].lower() in ("more", "extra"):
                t["pos"] = "ADV"
            if t["pos"] == "NOUN" and self.graph.concepts_of(lem, "verb", strict=True) and i > 0 and out[i - 1]["pos"] in ("NOUN", "PROPN") and i + 1 < len(out) \
                    and out[i + 1]["pos"] in ("NUM", "DET") and not self.graph.concepts_of(lem, "noun", strict=True) or (
                    t["pos"] == "NOUN" and lem in ("cost", "costs") and i > 0 and out[i - 1]["pos"] in ("NOUN", "PROPN") and i + 1 < len(out) and out[i + 1]["pos"] == "NUM"):
                t["pos"] = "VERB"
            if t["pos"] in ("VERB", "NOUN") and i > 0 and out[i - 1]["pos"] == "AUX" and out[i - 1]["lemma"] == "be" and self.graph.concepts_of(t["text"].lower(), "adj", strict=True):
                t["pos"], t["lemma"] = "ADJ", t["text"].lower()                       # "I'm broke": surface form is the adjective, not the verb "break"
            if t["pos"] == "VERB" and lem in ("do", "have") and i + 2 < len(out) and out[i + 1]["pos"] in ("PRON", "PROPN", "DET", "NOUN") and any(
                    x["pos"] in ("VERB", "NOUN", "ADJ") for x in out[i + 2:i + 4]) and t["text"].lower() in ("do", "does", "did") :
                t["pos"] = "AUX"
            if t["pos"] == "NOUN" and lem in ("out", "short", "low", "broke", "enough", "open", "closed", "penniless", "empty"):
                t["pos"] = "ADJ"
        return out

    # ---- chunking --------------------------------------------------------------------------------------------------------------------------
    def chunks(self, toks: list[dict], base: int = 0) -> list[Chunk]:
        toks = self._repair(toks)
        n = len(toks)
        out: list[Chunk] = []
        i = 0

        def span_text(a, b):
            return " ".join(t["text"] for t in toks[a:b]).replace(" '", "'").replace(" n't", "n't")

        while i < n:
            t = toks[i]
            pos, lem, low = t["pos"], (t.get("lemma") or t["text"]).lower(), t["text"].lower()
            if pos == "CCONJ":
                out.append(Chunk("CC", base + i, base + i + 1, t["text"], lem)); i += 1; continue
            if pos == "SCONJ" or (low in SUBORDINATORS and pos in ("ADP", "SCONJ") and low not in ("as", "since", "before", "after")):
                out.append(Chunk("SC", base + i, base + i + 1, t["text"], low)); i += 1; continue
            if pos == "INTJ":
                out.append(Chunk("INTJ", base + i, base + i + 1, t["text"], lem)); i += 1; continue
            if pos == "ADP":
                j = i + 1
                np_chunk, j2 = self._np(toks, j, base, allow_pron=True)
                if np_chunk:
                    out.append(Chunk("PP", base + i, base + j2, span_text(i, j2), np_chunk.head, {"prep": low, "np": np_chunk}))
                    i = j2
                else:
                    out.append(Chunk("PP", base + i, base + i + 1, t["text"], "", {"prep": low, "np": None}))   # stranded preposition ("use it for")
                    i += 1
                continue
            if low in WH and pos in ("PRON", "ADV", "DET"):
                if low in ("which", "whose", "what") and i + 1 < n and toks[i + 1]["pos"] in ("NOUN", "PROPN", "ADJ"):
                    np_chunk, j2 = self._np(toks, i, base)
                    if np_chunk:
                        np_chunk.f["wh"] = low
                        out.append(np_chunk); i = j2; continue
                if low == "how" and i + 1 < n and toks[i + 1]["lemma"] in ("many", "much") :
                    j = i + 2
                    np_chunk, j2 = self._np(toks, j, base)
                    if np_chunk:
                        np_chunk.f["wh"] = "how_" + toks[i + 1]["lemma"]
                        np_chunk.start = base + i
                        out.append(np_chunk); i = j2; continue
                    out.append(Chunk("WH", base + i, base + i + 2, span_text(i, i + 2), "how_" + toks[i + 1]["lemma"])); i += 2; continue
                if low == "how" and i + 1 < n and toks[i + 1]["pos"] in ("ADJ", "ADV"):
                    out.append(Chunk("WH", base + i, base + i + 2, span_text(i, i + 2), "how_" + toks[i + 1]["lemma"])); i += 2; continue
                out.append(Chunk("WH", base + i, base + i + 1, t["text"], low)); i += 1; continue
            if pos == "ADV" and lem == "never" and i + 1 < n and toks[i + 1]["pos"] in ("VERB", "AUX"):
                vg, j = self._vg(toks, i, base)
                if vg:
                    out.append(vg); i = j; continue
            if pos == "AUX" or pos == "VERB" or (pos == "PART" and lem == "not"):
                vg, j = self._vg(toks, i, base)
                if vg:
                    out.append(vg); i = j; continue
            if pos == "ADV" or (pos == "PART"):
                out.append(Chunk("ADVP", base + i, base + i + 1, t["text"], lem)); i += 1; continue
            np_chunk, j = self._np(toks, i, base, allow_pron=True)
            if np_chunk:
                out.append(np_chunk); i = j; continue
            if pos == "ADJ":
                j = i + 1
                while j < n and toks[j]["pos"] == "ADJ":
                    j += 1
                out.append(Chunk("ADJP", base + i, base + j, span_text(i, j), (toks[j - 1].get("lemma") or toks[j - 1]["text"]).lower(), {"lemmas": [(x.get("lemma") or x["text"]).lower() for x in toks[i:j]]}))
                i = j; continue
            out.append(Chunk("OTHER", base + i, base + i + 1, t["text"], lem)); i += 1
        return self._attach_possessive(out, toks, base)

    def _np(self, toks, i, base, allow_pron=False):
        n = len(toks)
        if i >= n:
            return None, i
        t = toks[i]
        if t["pos"] == "PRON" and allow_pron and t["text"].lower() not in WH:
            low = t["text"].lower()
            return Chunk("NP", base + i, base + i + 1, t["text"], (t.get("lemma") or low).lower(), {"pron": low, "person": 1 if low in ("i", "me", "we", "us") else 2 if low == "you" else 3,
                                                                                         "number": "plural" if low in ("we", "they", "them", "us") else "singular"}), i + 1
        j = i
        f: dict = {"adjs": [], "nouns": [], "names": []}
        if toks[j]["pos"] == "DET":
            d = toks[j]["text"].lower()
            if d in ("my", "your", "his", "her", "our", "their", "its"):
                f["poss"] = d
            elif d == "no":
                f["neg_det"] = True
            else:
                f["det"] = d
            j += 1
        while j < n and (toks[j]["pos"] == "NUM" or (toks[j]["text"].lower() in _UNITS or toks[j]["text"].lower() in _TENS)):
            v = _num(toks[j]["text"])
            if v is not None:
                f["num"] = (f.get("num", 0) + v) if "num" in f and f["num"] < 100 and v < 10 and f["num"] % 10 == 0 else v
            j += 1
        # post-numeric determiners ("80 km each hour") are left to the caller
        while j < n and (toks[j]["pos"] == "ADJ" or (toks[j]["pos"] == "ADV" and toks[j]["lemma"] in ("very", "really", "quite", "so", "too") and j + 1 < n and toks[j + 1]["pos"] == "ADJ")):
            if toks[j]["pos"] == "ADJ":
                f["adjs"].append((toks[j].get("lemma") or toks[j]["text"]).lower())
            j += 1
        k = j
        while j < n and toks[j]["pos"] in ("NOUN", "PROPN"):
            tk = toks[j]
            (f["names"] if tk["pos"] == "PROPN" else f["nouns"]).append(tk["text"] if tk["pos"] == "PROPN" else (tk.get("lemma") or tk["text"]).lower())
            j += 1
        if j == k:
            if "num" in f and k > i:                  # bare number phrase ("4", "50")
                return Chunk("NP", base + i, base + j, " ".join(t["text"] for t in toks[i:j]), "", f), j
            if f.get("adjs") and k > i and not f.get("det") and not f.get("poss"):
                return None, i
            return None, i
        head = f["names"][-1] if f["names"] and not f["nouns"] else (f["nouns"][-1] if f["nouns"] else f["names"][-1])
        if f["nouns"] and f["names"] and toks[k]["pos"] == "NOUN" and toks[j - 1]["pos"] == "PROPN":
            head = " ".join(f["names"])                  # "uncle Peter": role noun + name -> the name is the head, the noun its role
            f["role_noun"] = f["nouns"][0]
        elif f["names"] and not f["nouns"]:
            head = " ".join(f["names"])
        elif f["nouns"]:
            head = f["nouns"][-1]
            if len(f["nouns"]) > 1:
                f["compound"] = " ".join(f["nouns"])
        text = " ".join(t["text"] for t in toks[i:j])
        return Chunk("NP", base + i, base + j, text, head, f), j

    def _vg(self, toks, i, base):
        n = len(toks)
        j = i
        f: dict = {"aux": [], "neg": False, "modal": None, "tense": "present", "aspect": "simple", "verb": None, "copula": False}
        seen_main = False
        while j < n:
            t = toks[j]
            lem, low, pos = (t.get("lemma") or t["text"]).lower(), t["text"].lower(), t["pos"]
            if pos == "PART" and lem in ("not", "n't"):
                f["neg"] = not f["neg"] if f["neg"] else True; j += 1; continue
            if pos == "ADV" and lem in ("never",):
                f["neg"] = True; j += 1; continue
            if pos == "ADV" and not seen_main and j + 1 < n and toks[j + 1]["pos"] in ("AUX", "VERB", "PART"):
                f.setdefault("adv", []).append(lem); j += 1; continue
            if pos == "AUX":
                if lem in MODALS:
                    f["modal"] = MODALS[lem]
                    if lem in ("will", "shall"):
                        f["tense"] = "future"
                    elif low in ("could", "would"):
                        f["tense"] = "past" if lem == "can" and False else f["tense"]
                canon = lem if lem in MODALS else ("be" if low in BE or lem in BE else "do" if lem in ("do", "does", "did") or low in ("does", "did") else "have" if lem in ("have", "has", "had") or low in ("has", "had") else lem)
                f["aux"].append(canon)
                if lem in ("be",):
                    f["copula"] = True
                if low in ("was", "were", "did", "had"):
                    f["tense"] = "past"
                j += 1; continue
            if pos == "VERB" and not seen_main:
                seen_main = True
                f["verb"] = lem
                if low in IRREGULAR_PAST or (low.endswith("ed") and lem != low and "do" not in f["aux"] and not any(a in ("will", "shall") for a in f["aux"])):
                    if "have" in f["aux"] or "has" in f["aux"] and f["tense"] != "past":
                        f["aspect"] = "perfect"
                    else:
                        f["tense"] = "past"
                if low.endswith("ing") and f["copula"]:
                    f["aspect"] = "progressive"
                if f["aux"] and f["aux"][-1] in ("have", "has") and low in ("got", "gotten", "been"):
                    f["aspect"] = "perfect"
                j += 1
                break
            break
        if j == i:
            return None, i
        if f["verb"] is None and f["aux"]:
            # copula / bare auxiliary: "is", "am", "do" (inverted question: the main verb follows the subject)
            f["verb"] = "be" if f["copula"] else (f["aux"][-1] if f["aux"][-1] not in MODALS else None)
            if f["verb"] == "have" and f["tense"] != "past" and not f["neg"] and toks[i]["text"].lower() in ("have", "has", "had"):
                f["verb"] = "have"
        return Chunk("VG", base + i, base + j, " ".join(t["text"] for t in toks[i:j]), f["verb"] or "", f), j

    @staticmethod
    def _attach_possessive(chunks: list[Chunk], toks, base) -> list[Chunk]:
        """Resolve the 's token: possessive ("Uganda's capital is …") or a contraction of "is" ("My name's Zuri")."""
        out: list[Chunk] = []
        i = 0
        while i < len(chunks):
            c = chunks[i]
            if c.kind == "OTHER" and toks[c.start - base]["pos"] == "POSS" and out and out[-1].kind == "NP" and i + 1 < len(chunks) and chunks[i + 1].kind == "NP":
                owner, nxt = out[-1], chunks[i + 1]
                rest = chunks[i + 2:]
                is_pron = bool(owner.f.get("pron"))
                possessive = not is_pron and bool(rest) and rest[0].kind in ("VG", "PP", "ADVP") and not (owner.f.get("poss") and not rest)
                if owner.f.get("poss") and not rest:
                    possessive = False
                if not rest and not is_pron and not owner.f.get("poss") and owner.f.get("names") and nxt.end - nxt.start >= 2:
                    # "Peter's dog barks": the tagger fused the verb into the noun phrase; a name + 's + noun + verb-form is a possessive
                    # clause. Only a final word that is demonstrably verb-shaped ("barks", "runs") is split off; otherwise it stays "Peter is <NP>".
                    from ..engines.language.en.morphology import verb_analysis
                    last = toks[nxt.end - 1 - base]
                    va = verb_analysis(last["text"].lower()) if last["text"].lower().endswith("s") else None
                    if va:
                        lemma = va[0] if isinstance(va, (tuple, list)) else getattr(va, "lemma", None) or str(va)
                        nxt_np = Chunk("NP", nxt.start, nxt.end - 1, " ".join(t["text"] for t in toks[nxt.start - base:nxt.end - 1 - base]), nxt.head,
                                       {**nxt.f, "possessor": owner.head, "possessor_np": owner})
                        nxt_np.start = owner.start
                        nxt_np.text = f"{owner.text}'s {nxt_np.text}"
                        nxt_np.head = toks[nxt.end - 2 - base]["text"]
                        vg = Chunk("VG", nxt.end - 1, nxt.end, last["text"], lemma,
                                   {"aux": [], "neg": False, "modal": None, "tense": "present", "aspect": "simple", "verb": lemma, "copula": False})
                        out.pop(); out.append(nxt_np); out.append(vg)
                        i += 2
                        continue
                if possessive:
                    nxt.f["possessor"] = owner.head
                    nxt.f["possessor_np"] = owner
                    nxt.start = owner.start
                    nxt.text = f"{owner.text}'s {nxt.text}"
                    out.pop()
                    out.append(nxt)
                    i += 2
                    continue
                out.append(Chunk("VG", c.start, c.end, "'s", "be", {"aux": ["is"], "neg": False, "modal": None, "tense": "present", "aspect": "simple", "verb": "be", "copula": True}))
                i += 1
                continue
            out.append(c)
            i += 1
        return out

    # ---- clauses ---------------------------------------------------------------------------------------------------------------------------
    def parse(self, tokens: list[dict], question_mark: bool = False) -> list[Clause]:
        by_sent: dict[int, list[tuple[int, dict]]] = {}
        for i, t in enumerate(tokens):
            by_sent.setdefault(t.get("sentence", 0), []).append((i, t))
        clauses: list[Clause] = []
        for s, items in sorted(by_sent.items()):
            idxs = [i for i, _ in items]
            toks = [t for _, t in items]
            chunks = self.chunks(toks, base=idxs[0])
            clauses.extend(self._assemble(chunks, s, tokens, question_mark and s == max(by_sent)))
        return clauses

    def _assemble(self, chunks: list[Chunk], sentence: int, tokens: list[dict], question_mark: bool) -> list[Clause]:
        # split into clause candidates at CC / SC / INTJ boundaries (a CC splits only when a new verb group follows)
        segs: list[tuple[str | None, list[Chunk], bool]] = []
        cur: list[Chunk] = []
        sub: str | None = None
        for idx, c in enumerate(chunks):
            if c.kind == "SC":
                if cur:
                    segs.append((sub, cur, False)); cur = []
                sub = c.head
                continue
            if c.kind == "CC":
                has_later_vg = any(x.kind == "VG" for x in chunks[idx + 1:])
                has_cur_vg = any(x.kind == "VG" for x in cur)
                if cur and has_cur_vg and has_later_vg:
                    segs.append((sub, cur, False)); cur = []
                    continue
                if not cur:
                    cur.append(c)
                    continue
            if c.kind == "INTJ" and not cur:
                continue
            if c.kind == "ADVP" and c.head in ("then", "so") and not cur:
                continue
            cur.append(c)
        if cur:
            segs.append((sub, cur, False))
        # reported speech without "that": "My teacher says the capital of Canada is Toronto" -> [My teacher says] [that the capital of Canada is Toronto]
        reported: list[tuple[str | None, list[Chunk], bool]] = []
        for sub, seg, flag in segs:
            vgs = [k for k, c in enumerate(seg) if c.kind == "VG"]
            if len(vgs) >= 2 and self.graph.concepts_of(seg[vgs[0]].f.get("verb") or "", "verb", strict=True) and any(
                    m.concept in ("c.say", "c.think") for m in self.graph.concepts_of(seg[vgs[0]].f.get("verb") or "", "verb", strict=True)):
                k0 = vgs[0] + 1
                if k0 < vgs[1] and seg[k0].kind == "NP":
                    reported.append((sub, seg[:k0], False)); reported.append(("that", seg[k0:], False)); continue
            reported.append((sub, seg, flag))
        segs = reported
        # a subordinate clause that has its own verb ends where the main clause's subject begins:  "If the shop is open I buy bread"
        expanded: list[tuple[str | None, list[Chunk]]] = []
        for sub, seg, _ in segs:
            vgs = [k for k, c in enumerate(seg) if c.kind == "VG"]
            if sub and len(vgs) >= 2:
                k = vgs[1] - 1
                cut = k if k > vgs[0] and seg[k].kind == "NP" else None
                if cut is not None:
                    expanded.append((sub, seg[:cut])); expanded.append((None, seg[cut:])); continue
            expanded.append((sub, seg))
        clauses: list[Clause] = []
        prev_subject: Chunk | None = None
        for sub, seg in expanded:
            cl = self._clause(seg, sentence, sub, tokens, question_mark, prev_subject)
            if cl:
                if cl.subject is not None:
                    prev_subject = cl.subject
                clauses.append(cl)
        return clauses

    def _clause(self, seg: list[Chunk], sentence: int, sub: str | None, tokens, question_mark: bool, prev_subject: Chunk | None) -> Clause | None:
        if not seg:
            return None
        seg = [c for c in seg if not (c.kind == "CC" and c is seg[0])]
        wh = None
        body = list(seg)
        lead_wh = [c for c in body if c.kind == "WH" or (c.kind == "NP" and c.f.get("wh"))]
        if lead_wh:
            wh = lead_wh[0].head if lead_wh[0].kind == "WH" else lead_wh[0].f["wh"]
        vg_idx = next((k for k, c in enumerate(body) if c.kind == "VG"), None)
        subject = None
        inverted = False
        items: list[Chunk] = []
        vg = None
        if vg_idx is None:
            items = [c for c in body if c.kind != "WH"] if not wh else [c for c in body if c.kind != "WH" or c is not lead_wh[0]]
            nps = [c for c in items if c.kind in ("NP", "ADJP")]
            cl = Clause(sentence, None, None, items, wh=wh, subordinator=sub, punct_question=question_mark)
        else:
            vg = body[vg_idx]
            before = body[:vg_idx]
            after = body[vg_idx + 1:]
            if vg.f.get("verb") in ("do",) and vg.f.get("aux") and not any(x in MODALS for x in vg.f["aux"]) or (vg.f.get("modal") and vg.f.get("verb") is None) \
                    or (vg.f.get("aux") and vg.f.get("verb") in ("be", "have") and after and after[0].kind == "NP" and after[0].f.get("pron") and not [b for b in before if b.kind == "NP" and not b.f.get("wh")]) \
                    or (vg.f.get("verb") == "be" and vg_idx == 0 and after and after[0].kind == "NP" and not after[0].f.get("wh")):
                # inverted question: AUX + subject + (main verb)
                if after and after[0].kind == "NP" and not after[0].f.get("wh"):
                    subj = after[0]
                    rest = after[1:]
                    adv_skipped = []
                    while rest and rest[0].kind == "ADVP":
                        adv_skipped.append(rest[0]); rest = rest[1:]
                    if rest and rest[0].kind == "VG" and vg.f.get("verb") in ("do",) or (rest and rest[0].kind == "VG" and (vg.f.get("modal") or vg.f.get("verb") == "have")):
                        merged = rest[0]
                        mf = dict(merged.f)
                        mf["neg"] = mf["neg"] or vg.f.get("neg", False)
                        mf["aux"] = vg.f["aux"] + mf.get("aux", [])
                        mf["modal"] = vg.f.get("modal") or mf.get("modal")
                        mf["tense"] = "past" if vg.f.get("tense") == "past" else mf.get("tense", "present")
                        vg = Chunk("VG", vg.start, merged.end, f"{vg.text} {subj.text} {merged.text}", merged.f.get("verb") or "", mf)
                        subject, inverted, items = subj, True, adv_skipped + rest[1:]
                        items = [c for c in before if c.kind != "WH" and not c.f.get("wh")] + items
                    elif vg.f.get("copula") or vg.f.get("verb") == "be":
                        subject, inverted, items = subj, True, rest
                        items = [c for c in before if c.kind != "WH" and not c.f.get("wh")] + items
            if subject is None:
                nps_before = [c for c in before if c.kind == "NP" and not c.f.get("wh")]
                subject = nps_before[-1] if nps_before else None
                if subject is None and wh in ("who", "what", "which") and before and before[0].kind in ("WH",):
                    subject = None            # wh-subject question: "Who makes it?"
                items = [c for c in before if c is not subject and c.kind not in ("WH",) and not (c.kind == "NP" and c.f.get("wh") and c is lead_wh[0] and wh in ("who",))] + after if False else \
                        [c for c in before if c is not subject and c.kind != "WH"] + after
            cl = Clause(sentence, subject, vg, items, wh=wh, subordinator=sub, inverted=inverted, punct_question=question_mark)
            cl.items = [c for c in cl.items if c.kind not in ("CC",)]
            if subject is None and prev_subject is not None and not wh and not inverted and vg is not None:
                cl.subject = prev_subject
                cl.elided_subject = True
        if lead_wh and lead_wh[0].kind == "NP":
            cl.items = [c for c in cl.items if c is not lead_wh[0]]
            cl.items.insert(0, lead_wh[0])
        cl.tokens = (seg[0].start, seg[-1].end)
        cl.text = " ".join(t["text"] for t in tokens[seg[0].start:seg[-1].end])
        return cl
