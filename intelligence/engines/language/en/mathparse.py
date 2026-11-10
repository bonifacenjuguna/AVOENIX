"""Arithmetic sub-language: finds arithmetic requests inside English text and parses them with a
precedence-climbing parser into an expression tree. No ``eval`` anywhere.

Handles digits and number words, symbols (+ - * / x × ÷ ^), operator words (plus, minus, times,
multiplied by, divided by, over, to the power of, squared, cubed), percentages ("20% of 150",
"20 percent of 150"), "half of", "square root of", and phrasing frames such as "what is", "calculate",
"how much is".
"""

from __future__ import annotations

import re

from .lexicon import NUMBER_WORDS, SCALE_WORDS

_FRAMES = re.compile(r"^(?:please\s+)?(?:(?:what(?:'s| is| are)|whats|how much (?:is|are)|calculate|compute|solve|evaluate|work out|"
                     r"find|tell me|can you (?:calculate|compute|solve|tell me)|could you (?:calculate|compute))\s+)?(?:the (?:value|result|answer) of\s+)?",
                     re.I)
_NUM_TOKEN = re.compile(r"\d[\d,]*\.?\d*|\.\d+")


def _words_to_numbers(text: str) -> str:
    """Replace spelled-out numbers ("twenty five", "two hundred") with digits."""
    tokens = re.findall(r"[A-Za-z]+|\d[\d,]*\.?\d*|[^\sA-Za-z\d]", text)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i].lower()
        if t in NUMBER_WORDS or t in SCALE_WORDS:
            if t == "half" and not (i > 0 and tokens[i - 1].lower() in ("a", "one", "and")) and not (i + 1 < len(tokens) and tokens[i + 1].lower() == "of"):
                out.append(tokens[i]); i += 1; continue
            total, current, j, seen = 0.0, 0.0, i, False
            while j < len(tokens):
                w = tokens[j].lower()
                if w in NUMBER_WORDS and w not in ("half",):
                    current += NUMBER_WORDS[w] if w != "dozen" else 0
                    if w == "dozen":
                        current = (current or 1) * 12
                    seen = True
                elif w in SCALE_WORDS:
                    if SCALE_WORDS[w] == 100:
                        current = (current or 1) * 100
                    else:
                        total += (current or 1) * SCALE_WORDS[w]; current = 0
                    seen = True
                elif w == "-" and seen:
                    pass
                elif w == "and" and seen and j + 1 < len(tokens) and tokens[j + 1].lower() in NUMBER_WORDS and current >= 100:
                    pass
                else:
                    break
                j += 1
            if seen:
                value = total + current
                out.append(str(int(value)) if value == int(value) else str(value))
                i = j
                continue
        out.append(tokens[i]); i += 1
    return " ".join(out)


_OP_WORDS = [
    (r"to the power of|raised to(?: the power of)?", "^"), (r"multiplied by|times|multiply|x(?=\s*\d)", "*"),
    (r"divided by|over|divide by", "/"), (r"plus|add(?:ed to)?|and(?=\s*\d+\s*(?:\?|$))", "+"), (r"minus|subtract(?:ed by)?|less", "-"),
]


def _normalise_ops(text: str) -> str:
    t = text.lower()
    t = t.replace("×", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
    t = re.sub(r"(\d[\d.,]*)\s*(?:%|per\s*cent|percent)\s+of\b", r"\1 pct_of", t)
    t = re.sub(r"(\d[\d.,]*)\s*(?:%|per\s*cent|percent)", r"\1 pct", t)
    t = re.sub(r"\bsquare root of\b", " sqrt ", t)
    t = re.sub(r"\bhalf of\b", " 0.5 * ", t)
    t = re.sub(r"(\d[\d.,]*)\s*(?:squared)\b", r"\1 ^ 2", t)
    t = re.sub(r"(\d[\d.,]*)\s*(?:cubed)\b", r"\1 ^ 3", t)
    for pat, sym in _OP_WORDS:
        t = re.sub(r"\b(?:%s)\b" % pat if not pat.startswith("x(") else pat, f" {sym} ", t)
    return t


class _Parser:
    PREC = {"+": (1, "L"), "-": (1, "L"), "*": (2, "L"), "/": (2, "L"), "^": (4, "R"), "pct_of": (3, "L")}
    NAMES = {"+": "add", "-": "sub", "*": "mul", "/": "div", "^": "pow"}

    def __init__(self, toks: list[str]):
        self.toks, self.i = toks, 0

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> str:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expr(self, min_prec: int = 1):
        left = self.unary()
        while True:
            op = self.peek()
            if op not in self.PREC or self.PREC[op][0] < min_prec:
                break
            prec, assoc = self.PREC[op]
            self.take()
            right = self.expr(prec + 1 if assoc == "L" else prec)
            if op == "pct_of":
                left = ("percent_of", left, right)
            else:
                left = (self.NAMES[op], left, right)
        return left

    def unary(self):
        t = self.peek()
        if t is None:
            raise ValueError("unexpected end")
        if t == "-":
            self.take()
            return ("neg", self.unary())
        if t == "+":
            self.take()
            return self.unary()
        if t == "sqrt":
            self.take()
            return ("sqrt", self.unary())
        return self.atom()

    def atom(self):
        t = self.take()
        if t == "(":
            v = self.expr()
            if self.peek() != ")":
                raise ValueError("missing )")
            self.take()
            return self.postfix(v)
        if _NUM_TOKEN.fullmatch(t):
            return self.postfix(float(t.replace(",", "")) if "." in t else int(t.replace(",", "")))
        raise ValueError(f"unexpected token {t!r}")

    def postfix(self, v):
        if self.peek() == "pct":
            self.take()
            return ("div", v, 100)
        return v


def _tokenise(expr: str) -> list[str]:
    return re.findall(r"pct_of|pct|sqrt|\d[\d,]*\.?\d*|\.\d+|[-+*/^()]", expr)


def find_expression(text: str):
    """Return ``(tree, surface)`` when the text is (or asks for) a pure arithmetic expression."""
    raw = re.sub(r"\b(what|how much)['’]s\b", r"\1 is", text.strip(), flags=re.I)
    raw = re.sub(r"\bwhats\b", "what is", raw, flags=re.I)
    t = _words_to_numbers(raw)
    t = _normalise_ops(t)
    t = re.sub(r"[?!.]+$", "", t.strip())
    t = _FRAMES.sub("", t.strip())
    t = re.sub(r"^the\s+(?=sqrt|\d)", "", t.strip())
    t = re.sub(r"\b(?:equals?|is)\s*$", "", t).strip()
    t = re.sub(r"^(?:the )?(?:sum|product|difference|quotient) of\s+(.*?)\s+(?:and)\s+(.*)$", lambda m: f"{m.group(1)} OP {m.group(2)}", t)
    if "OP" in t:
        return None
    t = t.replace("=", "").strip()
    if not t or not re.search(r"\d", t):
        return None
    leftover = re.sub(r"pct_of|pct|sqrt|\d[\d,]*\.?\d*|\.\d+|[-+*/^()\s]", "", t)
    if leftover:
        return None
    toks = _tokenise(t)
    if len(toks) < 2 or all(_NUM_TOKEN.fullmatch(x) for x in toks):
        return None
    if not any(x in ("+", "-", "*", "/", "^", "pct", "pct_of", "sqrt") for x in toks):
        return None
    try:
        p = _Parser(toks)
        tree = p.expr()
        if p.peek() is not None:
            return None
    except (ValueError, IndexError):
        return None
    return tree, t
