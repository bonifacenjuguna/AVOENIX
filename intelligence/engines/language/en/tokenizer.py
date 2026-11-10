"""English tokenisation, contraction splitting and sentence segmentation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "u.s.", "u.k.",
                 "no.", "inc.", "ltd.", "co.", "approx.", "dept.", "est.", "a.m.", "p.m.", "jan.", "feb.", "mar.", "apr.",
                 "jun.", "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec."}

_EMOJI = (
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF❤✨✅❌]️?(?:‍[\U0001F300-\U0001FAFF♀♂❤]️?)*"
)
_PATTERN = re.compile(
    r"""
    (?P<url>https?://[^\s<>"']+|www\.[^\s<>"']+) |
    (?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+) |
    (?P<emoji>%s) |
    (?P<time>\b\d{1,2}:\d{2}(?:\s?[ap]\.?m\.?)?\b) |
    (?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:st|nd|rd|th)?) |
    (?P<abbr>(?:[A-Za-z]{1,4}\.){2,}|\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|Inc|Ltd|Co|no|approx|dept|est|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.) |
    (?P<word>[A-Za-z]+(?:['’\-][A-Za-z]+)*|['’][A-Za-z]+) |
    (?P<punct>\.\.\.|[.!?,;:()\[\]{}"“”\-–—/@#$%%&*+=<>^~|\\]|['’`])
    """ % _EMOJI,
    re.VERBOSE | re.UNICODE,
)

_CONTRACTION_SPLITS = {
    "can't": ["can", "not"], "cannot": ["can", "not"], "won't": ["will", "not"], "shan't": ["shall", "not"],
    "ain't": ["is", "not"], "let's": ["let", "us"], "gonna": ["going", "to"], "wanna": ["want", "to"],
    "gotta": ["got", "to"], "y'all": ["you", "all"],
    # apostrophe-less informal spellings
    "whats": ["what", "is"], "hows": ["how", "is"], "wheres": ["where", "is"], "whos": ["who", "is"], "thats": ["that", "is"],
    "dont": ["do", "not"], "doesnt": ["does", "not"], "didnt": ["did", "not"], "isnt": ["is", "not"], "arent": ["are", "not"],
    "wasnt": ["was", "not"], "werent": ["were", "not"], "cant": ["can", "not"], "wont": ["will", "not"], "havent": ["have", "not"],
    "hasnt": ["has", "not"], "shouldnt": ["should", "not"], "wouldnt": ["would", "not"], "couldnt": ["could", "not"],
    "im": ["i", "am"], "youre": ["you", "are"], "theyre": ["they", "are"], "weve": ["we", "have"], "ive": ["i", "have"],
}
_CLITICS = ("n't", "'re", "'ve", "'ll", "'d", "'m", "'s")


@dataclass
class Token:
    i: int
    text: str
    norm: str
    start: int
    end: int
    kind: str                       # word | number | time | punct | emoji | url | email | abbr | clitic
    pos: str = "X"
    lemma: str = ""
    feats: dict[str, Any] = field(default_factory=dict)
    cands: list[str] = field(default_factory=list)
    value: float | None = None      # for numbers

    @property
    def is_word(self) -> bool:
        return self.kind in ("word", "abbr", "clitic")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.text}/{self.pos}"


def _parse_number(text: str) -> tuple[float | None, str | None]:
    m = re.match(r"^(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(st|nd|rd|th)?$", text)
    if not m:
        return None, None
    value = float(m.group(1).replace(",", ""))
    return value, m.group(2)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    for m in _PATTERN.finditer(text):
        kind = m.lastgroup or "word"
        raw = m.group(0)
        start, end = m.start(), m.end()
        if kind == "word":
            raw_l = raw.lower().replace("’", "'")
            if raw_l in _CONTRACTION_SPLITS:
                parts = _CONTRACTION_SPLITS[raw_l]
                span = (end - start) / len(parts)
                for k, part in enumerate(parts):
                    tokens.append(Token(len(tokens), part if k else (raw[: len(part)] if raw[0].isupper() else part),
                                        part, int(start + k * span), int(start + (k + 1) * span), "word"))
                continue
            clitic = next((c for c in _CLITICS if raw_l.endswith(c) and len(raw_l) > len(c)), None)
            if clitic:
                stem = raw[: len(raw) - len(clitic)]
                if clitic == "n't":
                    tokens.append(Token(len(tokens), stem, stem.lower(), start, start + len(stem), "word"))
                    tokens.append(Token(len(tokens), "n't", "not", start + len(stem), end, "word"))
                else:
                    tokens.append(Token(len(tokens), stem, stem.lower(), start, start + len(stem), "word"))
                    tokens.append(Token(len(tokens), clitic, clitic, start + len(stem), end, "clitic"))
                continue
            tokens.append(Token(len(tokens), raw, raw_l, start, end, "word"))
        elif kind == "number":
            value, ordinal = _parse_number(raw)
            tok = Token(len(tokens), raw, raw.lower(), start, end, "number", value=value)
            if ordinal:
                tok.feats["ordinal"] = True
            tokens.append(tok)
        elif kind == "abbr":
            tokens.append(Token(len(tokens), raw, raw.lower(), start, end, "abbr"))
        elif kind in ("url", "email", "emoji", "time"):
            tokens.append(Token(len(tokens), raw, raw.lower(), start, end, kind))
        else:
            tokens.append(Token(len(tokens), raw, raw, start, end, "punct"))
    return tokens


_OPENERS = set("\"“([{'‘")
_TERMINATORS = {".", "!", "?", "...", "?!", "!!"}


def split_sentences(tokens: list[Token]) -> list[list[Token]]:
    """Split a token stream into sentences.

    A terminator ends a sentence when what follows could begin one: end of text, an
    upper-case word, a digit, an opening quote, or an emoji. Abbreviations ("Dr.") are
    tokenised with their period so they never terminate a sentence on their own.
    """
    sentences: list[list[Token]] = []
    current: list[Token] = []
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        current.append(tok)
        if tok.kind == "punct" and tok.norm in _TERMINATORS:
            # absorb stacked terminators and closing quotes/brackets
            while i + 1 < n and tokens[i + 1].kind == "punct" and tokens[i + 1].norm in (_TERMINATORS | set("\"”)]}'’")):
                i += 1
                current.append(tokens[i])
            nxt = tokens[i + 1] if i + 1 < n else None
            boundary = (
                nxt is None
                or nxt.kind in ("emoji", "number", "time")
                or (nxt.kind == "word" and nxt.text[:1].isupper())
                or (nxt.kind == "punct" and nxt.text in _OPENERS)
            )
            if boundary:
                sentences.append(current)
                current = []
        i += 1
    if current:
        sentences.append(current)
    # re-index tokens inside each sentence
    out = []
    for sent in sentences:
        for k, t in enumerate(sent):
            t.i = k
        out.append(sent)
    return out
