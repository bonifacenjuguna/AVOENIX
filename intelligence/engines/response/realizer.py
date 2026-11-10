"""English surface realisation of structured facts.

Everything here is *deterministic given its inputs*: it turns language-neutral structures (predicate + labelled arguments)
into English clauses using morphology rules and the gradable-adjective lexicon. Variation between alternative phrasings is
decided one level up (``engine.py``); this module guarantees that every variant says the same thing.
"""

from __future__ import annotations

from ..language.en.lexicon import GRADABLE
from ..language.en.morphology import comparative_form, indefinite_article, pluralize, superlative_form


def adjective_for(dimension: str, pole: str | int = "high") -> str | None:
    """Base adjective for a dimension pole ('high'/+1 -> old, tall...; 'low'/-1 -> young, short...). First lexicon entry wins (stable order)."""
    sign = 1 if pole in ("high", 1, "+") else -1
    for base, (dim, s, comp, sup) in GRADABLE.items():
        if dim == dimension and s == sign and comp:
            return base
    return None


def dim_noun(dimension: str) -> str:
    return dimension.split(".", 1)[-1].replace("_", " ")


def join_list(items: list[str], conj: str = "and") -> str:
    items = [str(i) for i in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conj} {items[1]}"
    return f"{', '.join(items[:-1])} {conj} {items[-1]}"


def be(subject: str, contract: bool = False, neg: bool = False) -> str:
    """Agreement of 'to be' with a subject string (you/I/plural lists)."""
    s = subject.strip()
    low = s.lower()
    plural = low in ("you", "they", "we") or " and " in low
    if low == "i":
        v = "am"
    elif plural:
        v = "are"
    else:
        v = "is"
    if neg:
        return {"is": "isn't" if contract else "is not", "are": "aren't" if contract else "are not", "am": "am not"}[v]
    return v


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def kind_phrase(label: str, *, plural: bool = False, article: bool = True) -> str:
    if plural:
        return pluralize(label)
    return f"{indefinite_article(label)} {label}" if article else label


def realize_fact(d: dict, *, contract: bool = False, force_neg: bool = False) -> str:
    """One clause (no final punctuation, not capitalised) for a structured fact dict {predicate,args,polarity,quantifier,pole}."""
    p, a = d["predicate"], d.get("args", {})
    neg = d.get("polarity") == "negative" or force_neg
    q = d.get("quantifier")
    if p == "rel.exceeds":
        adj = adjective_for(a.get("dimension", ""), "high")
        if adj is None:
            return f"{a['greater']} {'does not exceed' if neg else 'exceeds'} {a['lesser']} in {dim_noun(a.get('dimension', ''))}"
        return f"{a['greater']} {be(a['greater'], contract, neg)} {comparative_form(adj)} than {a['lesser']}"
    if p == "rel.equal_on":
        adj = adjective_for(a.get("dimension", ""), "high")
        if adj is None:
            return f"{a['first']} and {a['second']} {'differ' if neg else 'are equal'} in {dim_noun(a.get('dimension', ''))}"
        return f"{a['first']} {be(a['first'], contract, neg)} as {adj} as {a['second']}"
    if p == "rel.extreme":
        adj = adjective_for(a.get("dimension", ""), d.get("pole") or "high")
        if adj is None:
            return f"{a['subject']} {'is not' if neg else 'is'} at the {'top' if d.get('pole') != 'low' else 'bottom'} in {dim_noun(a.get('dimension', ''))}"
        return f"{a['subject']} {be(a['subject'], contract, neg)} the {superlative_form(adj)}"
    if p == "rel.is_a":
        s, o = a["subject"], a["object"]
        if d.get("generic") and neg:
            return f"{pluralize(s)} {'aren' + chr(39) + 't' if contract else 'are not'} {pluralize(o)}"
        if q in ("all", "no") or d.get("generic"):
            if neg:
                return f"no {s} is {indefinite_article(o)} {o}" if q == "all" else f"{pluralize(s)} are not {pluralize(o)}"
            return f"{pluralize(s)} are {pluralize(o)}" if q != "no" else f"no {s} is {indefinite_article(o)} {o}"
        return f"{s} {be(s, contract, neg)} {kind_phrase(o)}"
    if p == "rel.located_in":
        return f"{a['figure']} {be(a['figure'], contract, neg)} in {a['ground']}"
    if p == "rel.has_property":
        s, prop = a.get("subject", "?"), a.get("property", "?")
        prop = prop.replace("prop.", "")
        if q == "all":
            return f"all {pluralize(s)} {'are not' if neg else 'are'} {prop}"
        if a.get("value"):
            return f"{s} {be(s, contract, neg)} {a['value']}"
        return f"{s} {be(s, contract, neg)} {prop}"
    if p.startswith("attr."):
        attr = p[5:].replace("_", " ")
        owner = a.get("owner", "?")
        val = a.get("value", "?")
        if owner == "you":
            return f"your {attr} {be('it', contract, neg)} {val}"
        return f"the {attr} of {owner} {be('it', contract, neg)} {val}"
    args = ", ".join(f"{k}={v}" for k, v in a.items())
    return f"{'not ' if neg else ''}{p}({args})"


def summary_to_fact(summary: dict) -> dict | None:
    """Query summary (from the Reasoning Engine) -> structured fact dict, or None if it cannot be restated."""
    p = summary.get("predicate")
    if not p:
        return None
    terms, keys = summary.get("terms", {}), summary.get("term_keys", {})
    args: dict = {}
    for role, label in terms.items():
        if role in ("dimension", "property"):
            args[role] = keys.get(role) or label
        else:
            args[role] = label if not isinstance(label, list) else join_list(label, "or")
    if p == "rel.exceeds" and not {"greater", "lesser", "dimension"} <= set(args):
        return None
    if p == "rel.extreme" and not {"subject", "dimension"} <= set(args):
        return None
    return {"predicate": p, "args": args, "polarity": summary.get("polarity") or "positive", "quantifier": summary.get("quantifier"),
            "pole": summary.get("pole"), "generic": summary.get("quantifier") == "all"}


def realize_query_prop(summary: dict, *, contract: bool = False, force_neg: bool = False) -> str | None:
    d = summary_to_fact(summary)
    return realize_fact(d, contract=contract, force_neg=force_neg) if d else None
