"""Normalised knowledge terms: the bridge between ACR nodes and stored facts.

A *term* is a small JSON object with a stable ``key`` used for matching::

    {"t": "entity",   "key": "france",       "label": "France",   "type": "class.place"}
    {"t": "kind",     "key": "kind.man",     "label": "man"}
    {"t": "concept",  "key": "dim.age",      "label": "age"}
    {"t": "quantity", "key": "qty:30:year",  "value": 30, "unit": "year", "dimension": "dim.age"}
    {"t": "literal",   "key": "lit:blue",    "value": "blue"}
    {"t": "self",     "key": "@user",        "label": "you"}        # the speaker (scoped to that user)
"""

from __future__ import annotations

import re
from typing import Any

from ...representation import (
    ACRDocument, Concept, Entity, Literal, Logical, Quantity, Reference, Variable,
)

SELF_USER = "@user"
SELF_SYSTEM = "avoenix"


def norm_key(label: str) -> str:
    s = re.sub(r"\s+", " ", label.strip().lower())
    s = re.sub(r"^(the|a|an)\s+", "", s)
    return s


# Surface forms that name the same entity. Keys are normalised (lower-case, article-free); values are (canonical key, canonical label).
# Deliberately small: only unambiguous country/city abbreviations the curated seed uses. Ambiguous names (e.g. "America") are not aliased.
ALIASES: dict[str, tuple[str, str]] = {
    **{a: ("united states", "United States") for a in ("usa", "us", "u.s.", "u.s.a.", "united states of america", "the united states")},
    **{a: ("united kingdom", "United Kingdom") for a in ("uk", "u.k.", "britain", "great britain")},
    **{a: ("washington", "Washington, D.C.") for a in ("washington", "washington dc", "washington d.c.", "washington, dc", "washington, d.c.")},
}


def canonical(label: str) -> tuple[str, str]:
    """(key, label) after alias resolution; unknown names keep their own normalised key and surface label."""
    key = norm_key(label)
    return ALIASES.get(key, (key, label))


def entity_term(label: str, etype: str = "class.entity") -> dict:
    key, lab = canonical(label)
    return {"t": "entity", "key": key, "label": lab, "type": etype}


def kind_term(concept_id: str, label: str | None = None) -> dict:
    return {"t": "kind", "key": concept_id, "label": label or concept_id.split(".", 1)[-1].replace("_", " ")}


def concept_term(concept_id: str, label: str | None = None) -> dict:
    return {"t": "concept", "key": concept_id, "label": label or concept_id.split(".", 1)[-1].replace("_", " ")}


def quantity_term(value: float, unit: str | None, dimension: str | None = None) -> dict:
    v = int(value) if float(value).is_integer() else float(value)
    return {"t": "quantity", "key": f"qty:{v}:{unit or ''}", "value": v, "unit": unit, "dimension": dimension}


def literal_term(value: Any) -> dict:
    return {"t": "literal", "key": f"lit:{str(value).lower()}", "value": value}


def term_from_node(doc: ACRDocument, node_id: str | None) -> dict | None:
    """ACR node -> term. Returns None when the node cannot be represented as a stable term."""
    if node_id is None:
        return None
    node = doc.resolve(node_id) if isinstance(doc.maybe(node_id), Reference) else doc.maybe(node_id)
    if node is None or isinstance(node, Reference):
        return {"t": "unresolved", "key": "?unresolved"}
    if isinstance(node, Entity):
        deixis = node.annotations.get("deixis")
        if deixis == "speaker":
            return {"t": "self", "key": SELF_USER, "label": "you"}
        if deixis == "addressee":
            return entity_term("AVOENIX", "class.entity")
        if "lemma" in node.features and not node.features.get("proper"):
            t = entity_term(node.label, node.entity_type)
            t["instance"] = True              # a common-noun instance ("a book"): not storable as world knowledge
            return t
        return entity_term(node.label, node.entity_type)
    if isinstance(node, Concept):
        if node.concept_id.startswith("kind."):
            return kind_term(node.concept_id, node.label)
        return concept_term(node.concept_id, node.label)
    if isinstance(node, Quantity):
        return quantity_term(node.value, node.unit, node.dimension)
    if isinstance(node, Literal):
        return literal_term(node.value)
    if isinstance(node, Variable):
        return {"t": "variable", "key": f"?{node.name}", "name": node.name, "constraints": node.constraints}
    if isinstance(node, Logical) and node.op in ("and", "or"):
        members = [term_from_node(doc, o) for o in node.operands]
        return {"t": "group", "op": node.op, "key": "grp:" + ",".join(m["key"] for m in members if m), "members": [m for m in members if m]}
    return None


def render_term(term: dict) -> str:
    t = term.get("t")
    if t == "quantity":
        return f"{term['value']} {term.get('unit') or ''}".strip()
    if t == "literal":
        return str(term["value"])
    if t == "variable":
        return "?"
    return term.get("label") or term.get("key", "?")


def render_statement(predicate: str, args: dict[str, dict], polarity: str = "positive", quantifier: str | None = None) -> str:
    """Compact English-ish rendering used for retrieval and inspection (not for user-facing prose)."""
    parts = " ".join(f"{k}={render_term(v)}" for k, v in args.items())
    neg = "NOT " if polarity == "negative" else ""
    q = f"[{quantifier}] " if quantifier else ""
    return f"{q}{neg}{predicate}({parts})"


def is_storable_term(term: dict | None) -> bool:
    return bool(term) and term.get("t") not in ("unresolved", "variable") and not term.get("instance")
