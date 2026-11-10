"""English analysis pipeline: text -> tokens -> tags -> parse -> ACR."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from ....algorithms.arithmetic import ArithmeticError_, evaluate, render
from ....algorithms.text_similarity import damerau
from ....representation import ACRBuilder, ACRDocument, Provenance
from . import lexicon as L
from .lexicon_open import ADJECTIVES, NOUN_VERB
from .mathparse import find_expression
from .morphology import singularize, verb_analysis
from .parser import Parser
from .semantics import SemanticBuilder
from .syntax import ParsedSentence
from .tagger import KNOWN_NOUNS, tag_sentence
from .tokenizer import Token, split_sentences, tokenize
from . import gazetteer


@lru_cache(maxsize=1)
def vocabulary() -> frozenset[str]:
    vocab: set[str] = set()
    for group in (L.DETERMINERS, L.POSSESSIVE_DETS, L.PRONOUNS, L.INTERJECTIONS, L.NUMBER_WORDS, L.SCALE_WORDS, L.GRADABLE, L.VERBS,
                  L.IRREGULAR_VERBS, L.UNITS, L.COMPARATIVE_FORMS, L.ORDINALS):
        vocab.update(k for k in group if isinstance(k, str))
    for group in (L.PREPOSITIONS, L.CCONJ, L.SCONJ, L.MODALS, L.ADVERBS_COMMON, L.WH_WORDS, ADJECTIVES, KNOWN_NOUNS, L.MALE_NAMES,
                  L.FEMALE_NAMES, gazetteer.PLACES, L.WEEKDAYS, L.MONTHS, L.EXTRA_VERBS):
        vocab.update(group)
    vocab.update(L.AUX_BE); vocab.update(L.AUX_HAVE); vocab.update(L.AUX_DO)
    vocab.update(L.DEICTIC_DAYS)
    return frozenset(w for w in vocab if w.isalpha() and len(w) > 1)


@lru_cache(maxsize=1)
def _by_length() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for w in vocabulary():
        out.setdefault(len(w), []).append(w)
    return out


def _known(word: str) -> bool:
    w = word.lower()
    if w in vocabulary():
        return True
    lemma, _ = singularize(w)
    if lemma in vocabulary():
        return True
    if verb_analysis(w):
        return True
    from .morphology import degree_analysis
    return degree_analysis(w) is not None


def repair_token(tok: Token, first: bool = False) -> dict | None:
    """Elongation ("heyyy") and single-edit typo repair for lower-case unknown words.

    Capitalised words are never "corrected" (they are probably names). A correction needs a *unique*
    best candidate; ties are left alone rather than guessed.
    """
    if tok.kind != "word" or len(tok.norm) < 3 or _known(tok.norm) or "'" in tok.norm or "-" in tok.norm:
        return None
    capitalised = tok.text[:1].isupper()
    if capitalised and not first:
        return None
    w = tok.norm
    runs = [(m.group(1), len(m.group(0))) for m in re.finditer(r"(.)\1*", w)]
    long_idx = [i for i, (_, n) in enumerate(runs) if n >= 3]
    if long_idx:
        from itertools import product
        for combo in product((1, 2), repeat=min(len(long_idx), 4)):
            sizes = [n for _, n in runs]
            for k, size in zip(long_idx, combo):
                sizes[k] = size
            cand = "".join(ch * sz for (ch, _), sz in zip(runs, sizes))
            if cand != w and _known(cand):
                return {"from": w, "to": cand, "kind": "elongation"}
    # transpositions / single edit among vocabulary words of nearby length
    best: list[tuple[int, str]] = []
    limit = 1 if len(w) <= 7 else 2
    for ln in range(len(w) - limit, len(w) + limit + 1):
        for cand in _by_length().get(ln, ()):
            if cand[0] != w[0] and cand[1:2] != w[1:2] and sorted(cand[:2]) != sorted(w[:2]):
                continue
            d = damerau(w, cand)
            if d <= limit:
                best.append((d, cand))
    if not best:
        return None
    best.sort()
    top = [c for d, c in best if d == best[0][0]]
    if len(top) != 1:
        return None
    if capitalised and top[0] not in L.INTERJECTIONS and top[0] not in L.PRONOUNS and top[0] not in L.WH_WORDS and top[0] not in L.DETERMINERS:
        return None          # a capitalised sentence-initial word is only repaired towards function words/greetings
    return {"from": w, "to": top[0], "kind": "typo", "distance": best[0][0]}


@dataclass
class TokenInfo:
    text: str
    lemma: str
    pos: str
    sentence: int
    corrected_from: str | None = None


@dataclass
class EnglishAnalysis:
    doc: ACRDocument
    sentences: list[ParsedSentence]
    tokens: list[TokenInfo]
    corrections: list[dict]
    math: dict | None
    coverage: float
    notes: list[str] = field(default_factory=list)


class EnglishPipeline:
    def __init__(self) -> None:
        self.parser = Parser()

    def analyze(self, text: str, *, now: datetime | None = None, repair: bool = True) -> EnglishAnalysis:
        tokens = tokenize(text)
        corrections: list[dict] = []
        if repair:
            for idx, t in enumerate(tokens):
                fix = repair_token(t, first=idx == 0 or (idx > 0 and tokens[idx - 1].kind == "punct" and tokens[idx - 1].norm in (".", "!", "?")))
                if fix:
                    corrections.append({**fix, "position": t.start})
                    t.feats["corrected_from"] = t.norm
                    t.norm = fix["to"]
                    t.text = fix["to"].capitalize() if t.text[:1].isupper() else fix["to"]
        sentences_tokens = split_sentences(tokens)
        parsed: list[ParsedSentence] = []
        infos: list[TokenInfo] = []
        for k, toks in enumerate(sentences_tokens):
            tag_sentence(toks)
            surface = " ".join(t.text for t in toks)
            ps = self.parser.parse(toks, surface, index=k)
            parsed.append(ps)
            for t in toks:
                if t.kind in ("word", "clitic", "number", "abbr", "time", "emoji"):
                    infos.append(TokenInfo(t.text, t.lemma or t.norm, t.pos, k, t.feats.get("corrected_from")))
        math = self._math(text, now)
        builder = SemanticBuilder(parsed, now=now, text=text)
        if math is not None:
            doc = self._math_doc(text, math, now)
        else:
            doc = builder.build()
        words = [p.coverage for p in parsed if p.tokens]
        coverage = sum(words) / len(words) if words else 0.0
        notes = [n for p in parsed for n in p.notes]
        if math is not None:
            coverage = 1.0
        return EnglishAnalysis(doc, parsed, infos, corrections, math, coverage, notes)

    # ---- arithmetic requests ------------------------------------------------------------------------
    def _math(self, text: str, now: datetime | None) -> dict | None:
        found = find_expression(text)
        if not found:
            return None
        tree, surface = found
        try:
            value = evaluate(tree)
        except ArithmeticError_ as exc:
            return {"tree": tree, "surface": surface, "error": str(exc)}
        return {"tree": tree, "surface": surface, "value": render(value)}

    def _math_doc(self, text: str, math: dict, now: datetime | None) -> ACRDocument:
        b = ACRBuilder(default_provenance=Provenance("user_statement", method="language.en.math"))
        speaker = b.entity("speaker", "class.person", features={"animacy": "animate"}, annotations={"deixis": "speaker"})
        addressee = b.entity("AVOENIX", "class.entity", features={"animacy": "animate"}, annotations={"deixis": "addressee"})

        def build(tree: Any) -> str:
            if isinstance(tree, tuple):
                op, *args = tree
                return b.expression(op, [build(a) for a in args])
            return b.quantity(float(tree) if isinstance(tree, float) else int(tree))

        expr = build(math["tree"])
        b.doc.nodes[expr].annotations["surface_expression"] = math["surface"]
        asking = "?" in text or bool(re.match(r"\s*(what|how|calculate|compute|solve|evaluate|work|find|tell)", text, re.I))
        b.intention("request_information" if asking else "assert", agent=speaker, addressee=addressee, content=[expr],
                    features={"question_kind": "arithmetic", "focus": expr}, root=True)
        doc = b.build()
        doc.meta["text"] = text
        return doc
