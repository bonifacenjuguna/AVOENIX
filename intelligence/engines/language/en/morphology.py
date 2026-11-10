"""English morphology: analysis (lemmatisation) and generation (inflection)."""

from __future__ import annotations

import re

from .lexicon import (
    COMPARATIVE_FORMS, EXTRA_VERBS, GRADABLE, IRREGULAR_VERBS, VERBS,
)

VOWELS = "aeiou"

IRREGULAR_PLURALS = {
    "children": "child", "men": "man", "women": "woman", "people": "person", "mice": "mouse", "feet": "foot",
    "teeth": "tooth", "geese": "goose", "wolves": "wolf", "lives": "life", "knives": "knife", "leaves": "leaf",
    "halves": "half", "shelves": "shelf", "thieves": "thief", "selves": "self", "oxen": "ox", "data": "datum",
    "criteria": "criterion", "phenomena": "phenomenon", "fish": "fish", "sheep": "sheep", "deer": "deer",
    "series": "series", "species": "species", "news": "news", "mathematics": "mathematics", "physics": "physics",
}
_PLURAL_FROM_SINGULAR = {v: k for k, v in IRREGULAR_PLURALS.items() if v not in ("datum", "criterion", "phenomenon")}
_PLURAL_FROM_SINGULAR.update({"person": "people"})
UNCOUNTABLE = {"water", "tea", "coffee", "milk", "money", "news", "information", "music", "knowledge", "advice", "furniture",
               "homework", "bread", "rice", "time", "love", "mathematics", "physics", "software", "equipment", "luggage"}

_VERB_FORMS: dict[str, tuple[str, str]] = {}      # surface -> (lemma, form)
_KNOWN_LEMMAS = set(VERBS) | set(IRREGULAR_VERBS) | EXTRA_VERBS


def gerund(lemma: str) -> str:
    if lemma == "be":
        return "being"
    if lemma.endswith("ie"):
        return lemma[:-2] + "ying"
    if lemma.endswith("e") and not lemma.endswith(("ee", "oe", "ye")) and lemma not in ("be",):
        return lemma[:-1] + "ing"
    if _doubles(lemma):
        return lemma + lemma[-1] + "ing"
    return lemma + "ing"


def _doubles(lemma: str) -> bool:
    """CVC doubling for short stressed-final syllables (run->running, stop->stopping)."""
    if len(lemma) < 3 or lemma[-1] in "wxy" or lemma[-1] in VOWELS:
        return False
    if lemma[-2] not in VOWELS or lemma[-3] in VOWELS:
        return False
    # only single-syllable (one vowel group) words double reliably; multi-syllable ones are ambiguous
    groups = re.findall(r"[aeiou]+", lemma)
    if len(groups) == 1:
        return True
    return lemma.endswith(("begin", "admit", "occur", "prefer", "permit", "commit", "forget", "regret"))


def third_person(lemma: str) -> str:
    if lemma == "be":
        return "is"
    if lemma == "have":
        return "has"
    if lemma == "do":
        return "does"
    if re.search(r"(s|x|z|ch|sh|o)$", lemma):
        return lemma + "es"
    if lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in VOWELS:
        return lemma[:-1] + "ies"
    return lemma + "s"


def past(lemma: str) -> str:
    if lemma in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[lemma][0]
    return _regular_past(lemma)


def participle(lemma: str) -> str:
    if lemma in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[lemma][1]
    return _regular_past(lemma)


def _regular_past(lemma: str) -> str:
    if lemma.endswith("e"):
        return lemma + "d"
    if lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in VOWELS:
        return lemma[:-1] + "ied"
    if _doubles(lemma):
        return lemma + lemma[-1] + "ed"
    return lemma + "ed"


def inflect_verb(lemma: str, form: str, *, person: int = 3, number: str = "sg") -> str:
    """form: base | pres | past | participle | gerund"""
    if lemma == "be":
        if form == "pres":
            return {1: "am"}.get(person, "is") if number == "sg" and person != 2 else "are"
        if form == "past":
            return "was" if number == "sg" and person != 2 else "were"
        return {"base": "be", "participle": "been", "gerund": "being"}[form]
    if form == "base":
        return lemma
    if form == "pres":
        return third_person(lemma) if (person == 3 and number == "sg") else lemma
    if form == "past":
        return past(lemma)
    if form == "participle":
        return participle(lemma)
    if form == "gerund":
        return gerund(lemma)
    raise ValueError(form)


def _build_verb_index() -> None:
    for lemma in _KNOWN_LEMMAS:
        for surface, form in (
            (lemma, "base"), (third_person(lemma), "3sg"), (past(lemma), "past"),
            (participle(lemma), "participle"), (gerund(lemma), "gerund"),
        ):
            # first writer wins for ambiguous forms (e.g. "read": base/past)
            _VERB_FORMS.setdefault(surface, (lemma, form))
    # irregular present/past clashes: keep the base reading for identical base/past ("put", "cut", "read")
    for lemma, (p, pp) in IRREGULAR_VERBS.items():
        _VERB_FORMS[lemma] = (lemma, "base")


_build_verb_index()


def verb_analysis(word: str) -> tuple[str, str, bool] | None:
    """Return (lemma, form, known) for a possible verb form, or None. ``known`` is False for guesses."""
    hit = _VERB_FORMS.get(word)
    if hit:
        return hit[0], hit[1], True
    return None


def guess_verb(word: str) -> tuple[str, str] | None:
    """Rule-based lemma guess for unseen verbs ending in -ing / -ed."""
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in VOWELS + "lsz":
            stem = stem[:-1]
        return stem, "gerund"
    if word.endswith("ied") and len(word) > 4:
        return word[:-3] + "y", "past"
    if word.endswith("ed") and len(word) > 4:
        stem = word[:-2]
        if stem.endswith(("at", "iz", "iv", "us", "ur", "ar", "ov", "ak")) or (len(stem) > 2 and stem[-1] not in VOWELS and stem[-2] in VOWELS and stem[-3:-2] not in VOWELS and stem[-1] in "cgstvz"):
            stem += "e" if not word.endswith("eed") else ""
        if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in VOWELS + "lsz":
            stem = stem[:-1]
        return stem, "past"
    return None


def singularize(word: str) -> tuple[str, bool]:
    """(lemma, was_plural)."""
    w = word.lower()
    if w in IRREGULAR_PLURALS:
        lemma = IRREGULAR_PLURALS[w]
        return lemma, lemma != w
    if w in UNCOUNTABLE or len(w) <= 3 and not w.endswith("s"):
        return w, False
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y", True
    if w.endswith("ves") and len(w) > 4:
        return w[:-3] + "f", True
    if w.endswith(("sses", "xes", "zes", "ches", "shes")) and len(w) > 4:
        return w[:-2], True
    if w.endswith("oes") and len(w) > 4:
        return w[:-2], True
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1], True
    return w, False


def pluralize(noun: str) -> str:
    n = noun.lower()
    if n in _PLURAL_FROM_SINGULAR:
        out = _PLURAL_FROM_SINGULAR[n]
    elif re.search(r"(s|x|z|ch|sh)$", n):
        out = n + "es"
    elif n.endswith("y") and len(n) > 1 and n[-2] not in VOWELS:
        out = n[:-1] + "ies"
    elif n.endswith("fe"):
        out = n[:-2] + "ves"
    elif n.endswith("f") and n not in ("roof", "belief", "chief"):
        out = n[:-1] + "ves"
    else:
        out = n + "s"
    return out if noun.islower() else out.capitalize() if noun[:1].isupper() else out


def indefinite_article(word: str) -> str:
    w = word.lower()
    if w.startswith(("hour", "honest", "heir", "honor")):
        return "an"
    if w.startswith(("uni", "use", "eu", "one", "once", "ubiq")):
        return "a"
    return "an" if w[:1] in VOWELS else "a"


# ---- adjectives -------------------------------------------------------------------------
def degree_analysis(word: str) -> tuple[str, str] | None:
    """Return (base, 'cmp'|'sup') for comparative/superlative forms, else None."""
    w = word.lower()
    if w in COMPARATIVE_FORMS:
        return COMPARATIVE_FORMS[w]
    for suffix, degree in (("est", "sup"), ("er", "cmp")):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            stem = w[: -len(suffix)]
            candidates = [stem, stem + "e"]
            if stem.endswith("i"):
                candidates.append(stem[:-1] + "y")
            if len(stem) > 2 and stem[-1] == stem[-2]:
                candidates.append(stem[:-1])
            for c in candidates:
                if c in GRADABLE:
                    return c, degree
    return None


def guess_degree(word: str) -> tuple[str, str] | None:
    """Unknown comparative like 'nimbler' (used only when context, e.g. 'than', supports it)."""
    w = word.lower()
    if w.endswith("est") and len(w) > 5:
        return _strip_degree(w[:-3]), "sup"
    if w.endswith("er") and len(w) > 4:
        return _strip_degree(w[:-2]), "cmp"
    return None


def _strip_degree(stem: str) -> str:
    if stem.endswith("i"):
        return stem[:-1] + "y"
    if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in VOWELS:
        return stem[:-1]
    if stem.endswith("l") and stem[-2:-1] not in VOWELS and len(stem) > 3:
        return stem + "e"
    return stem


def comparative_form(base: str) -> str:
    """Generate comparative for realisation (uses lexicon, else derives)."""
    if base in GRADABLE and GRADABLE[base][2]:
        return GRADABLE[base][2]  # type: ignore[return-value]
    if len(re.findall(r"[aeiouy]+", base)) >= 3 or base.endswith(("ful", "ous", "ive", "ing", "ed", "al")):
        return "more " + base
    if base.endswith("e"):
        return base + "r"
    if base.endswith("y") and base[-2] not in VOWELS:
        return base[:-1] + "ier"
    if _doubles(base):
        return base + base[-1] + "er"
    return base + "er"


def superlative_form(base: str) -> str:
    if base in GRADABLE and GRADABLE[base][3]:
        return GRADABLE[base][3]  # type: ignore[return-value]
    comp = comparative_form(base)
    if comp.startswith("more "):
        return "most " + base
    return comp[:-2] + "est" if comp.endswith("er") else comp + "est"
