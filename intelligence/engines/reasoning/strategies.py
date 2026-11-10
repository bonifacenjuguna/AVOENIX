"""Reasoning strategies. Each strategy declares what it handles, what family of inference it is, and where it stops.

A strategy receives a ``Query`` (one proposition taken from a question or statement) and a ``FactBase`` and returns a
``Conclusion``. Strategies never invent facts: anything that cannot be derived is reported as ``unknown`` or
``underdetermined`` together with what is missing.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from ...algorithms import arithmetic
from ...algorithms.confidence import chain, laplace
from ...algorithms.constraint import rankings
from ...algorithms.partial_order import PartialOrder
from ...core.contracts import Conclusion, Evidence
from ...representation import ACRDocument, Proposition, Variable
from ..knowledge.terms import SELF_USER, norm_key, render_term, term_from_node
from .facts import FactBase, describe, evidence_for

POLE_WORD = {"high": "highest", "low": "lowest"}


@dataclass
class Query:
    kind: str                         # question | assertion | arithmetic
    doc: ACRDocument
    prop: Proposition | None
    question_kind: str | None = None  # yes_no | wh_identify | arithmetic
    wh: str | None = None
    math: dict | None = None
    terms: dict[str, dict] = field(default_factory=dict)       # role -> term
    variables: dict[str, str] = field(default_factory=dict)    # role -> variable name
    notes: list[str] = field(default_factory=list)

    @property
    def predicate(self) -> str | None:
        return self.prop.predicate if self.prop else None

    def summary(self) -> dict:
        """Language-neutral description of the asked/stated proposition (labels only, no node ids)."""
        def lab(t: dict) -> Any:
            if t.get("t") == "group":
                return [lab(m) for m in t.get("members", [])]
            return "you" if t.get("key") == SELF_USER else (t.get("label") or t.get("value") or t.get("key"))
        ann = self.prop.annotations if self.prop else {}
        return {"kind": self.kind, "predicate": self.predicate, "polarity": self.prop.polarity if self.prop else None,
                "quantifier": self.prop.quantifier if self.prop else None, "question_kind": self.question_kind, "wh": self.wh,
                "terms": {r: lab(t) for r, t in self.terms.items()}, "term_keys": {r: t.get("key") for r, t in self.terms.items()},
                "variables": dict(self.variables), "adjective": ann.get("adjective"), "pole": ann.get("pole"),
                "math": ({"surface": self.math.get("surface")} if self.math else None)}


def build_query(kind: str, doc: ACRDocument, prop: Proposition | None, **kw) -> Query:
    q = Query(kind=kind, doc=doc, prop=prop, **kw)
    if prop is not None:
        for role, ref in prop.args.items():
            node = doc.resolve(ref) if hasattr(doc, "resolve") else doc.nodes[ref]
            if isinstance(node, Variable):
                q.variables[role] = node.name
            else:
                t = term_from_node(doc, ref)
                if t:
                    q.terms[role] = t
    return q


class Strategy:
    name = "abstract"
    family = "deductive"
    handles = ""
    boundaries = ""

    def applies(self, q: Query) -> bool:           # pragma: no cover - interface
        raise NotImplementedError

    def run(self, q: Query, fb: FactBase) -> Conclusion:   # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "family": self.family, "handles": self.handles, "boundaries": self.boundaries}


def _label(t: dict) -> str:
    return "you" if t.get("key") == SELF_USER else render_term(t)


# ====================================================================================================================
# Ordering (relational reasoning)
# ====================================================================================================================
class OrderModel:
    """Weak ordering on one dimension built from stated comparisons, equalities, extremes and numeric measurements."""

    def __init__(self, dim: str, fb: FactBase):
        self.dim = dim
        self.po = PartialOrder()
        self.labels: dict[str, str] = {}
        self.greater: list[tuple[str, str]] = []
        self.not_greater: list[tuple[str, str]] = []
        self.equal: list[tuple[str, str]] = []
        self.facts: dict[tuple[str, str], Any] = {}        # (a, b) -> supporting Fact for a > b
        self.eq_facts: dict[frozenset, Any] = {}
        self.extremes: list[tuple[str, str, Any]] = []
        self.skipped: list[str] = []
        self.numeric: dict[str, tuple[Fraction, str, Any]] = {}
        self._load(fb)

    def _see(self, term: dict) -> str | None:
        if term.get("t") not in ("entity", "self", "kind"):
            return None
        self.labels.setdefault(term["key"], _label(term))
        return term["key"]

    def _load(self, fb: FactBase) -> None:
        for f in fb.get("rel.exceeds"):
            if f.key_of("dimension") != self.dim:
                continue
            a, b = self._see(f.args["greater"]), self._see(f.args["lesser"])
            if a is None or b is None:
                continue
            if f.polarity == "positive":
                self.greater.append((a, b))
                self.facts.setdefault((a, b), f)
                self.po.add_greater(a, b, f)
            else:
                self.not_greater.append((a, b))
                self.po.add_not_greater(a, b, f)
        for f in fb.get("rel.equal_on"):
            if f.key_of("dimension") != self.dim:
                continue
            a, b = self._see(f.args["first"]), self._see(f.args["second"])
            if a is None or b is None:
                continue
            if f.polarity == "positive":
                self.equal.append((a, b))
                self.eq_facts[frozenset((a, b))] = f
                self.po.add_equal(a, b, f)
            else:
                self.skipped.append("negated equality is not used by the ordering strategy")
        # numeric measurements: "John is 30 years old" -> rel.has_property(John, prop.age, 30 year)
        prop_key = "prop." + self.dim.split(".", 1)[1]
        for f in fb.get("rel.has_property"):
            if f.key_of("property") == prop_key and f.polarity == "positive" and (v := f.args.get("value")) and v.get("t") == "quantity":
                k = self._see(f.args["subject"])
                if k is not None:
                    self.numeric[k] = (Fraction(str(v["value"])), v.get("unit") or "", f)
        items = list(self.numeric.items())
        for i, (ka, (va, ua, fa)) in enumerate(items):
            for kb, (vb, ub, fb_) in items[i + 1:]:
                if ua != ub:
                    self.skipped.append(f"cannot compare {va} {ua} with {vb} {ub} (different units)")
                    continue
                if va > vb:
                    self.greater.append((ka, kb)); self.po.add_greater(ka, kb, (fa, fb_)); self.facts.setdefault((ka, kb), (fa, fb_))
                elif vb > va:
                    self.greater.append((kb, ka)); self.po.add_greater(kb, ka, (fa, fb_)); self.facts.setdefault((kb, ka), (fa, fb_))
                else:
                    self.equal.append((ka, kb)); self.po.add_equal(ka, kb, (fa, fb_)); self.eq_facts[frozenset((ka, kb))] = (fa, fb_)
        # asserted extremes ("Ann is the tallest") become constraints against everyone else in the domain
        for f in fb.get("rel.extreme"):
            if f.key_of("dimension") != self.dim or f.polarity != "positive" or f.args["subject"].get("t") == "variable":
                continue
            k = self._see(f.args["subject"])
            if k is not None:
                self.extremes.append((k, f.qualifiers.get("pole") or "high", f))
        for k, pole, f in self.extremes:
            for other in list(self.labels):
                if other == k:
                    continue
                if pole == "high":
                    self.greater.append((k, other)); self.po.add_greater(k, other, f); self.facts.setdefault((k, other), f)
                else:
                    self.greater.append((other, k)); self.po.add_greater(other, k, f); self.facts.setdefault((other, k), f)

    @property
    def items(self) -> list[str]:
        return list(self.labels)

    def consistent(self) -> bool:
        return self.po.is_consistent

    def conflict(self) -> dict | None:
        cyc = self.po.find_cycle()
        if cyc:
            return {"kind": "ordering_cycle", "cycle": [self.labels.get(c, str(c)) for c in cyc], "dimension": self.dim}
        v = self.po.violations()
        if v:
            a, b, _ = v[0]
            return {"kind": "negated_comparison_violated", "pair": [self.labels[a], self.labels[b]], "dimension": self.dim}
        return None

    def facts_on_path(self, a: str, b: str) -> list[Any]:
        path = self.po.chain(a, b) or []
        out: list[Any] = []
        for x, y in zip(path, path[1:]):
            f = self.facts.get((x, y)) or self.eq_facts.get(frozenset((x, y)))
            if f is not None:
                out += list(f) if isinstance(f, tuple) else [f]
        return out

    def path_text(self, a: str, b: str) -> str:
        path = self.po.chain(a, b) or [a, b]
        return " > ".join(self.labels.get(p, p) for p in path)

    def csp(self) -> list[dict] | None:
        return rankings(self.items, self.greater, self.not_greater, self.equal)


def _dim_label(dim: str) -> str:
    return dim.split(".", 1)[-1].replace("_", " ")


def _facts_conf(facts: list[Any]) -> float:
    uniq = {id(f): f for f in facts}
    return chain([f.confidence for f in uniq.values()]) if uniq else 1.0


class OrderingStrategy(Strategy):
    name = "relational_ordering"
    family = "deductive"
    handles = ("Comparisons (older/taller/heavier/...), equalities, superlatives, numeric measurements: who is the oldest/youngest, "
               "who is older than X, is A older than B. Transitive closure with equality classes, cycle detection and a CSP cross-check.")
    boundaries = ("One dimension at a time; at most 8 entities are cross-checked by enumeration; no probabilistic orderings; "
                  "comparatives of non-gradable properties are not ordered.")

    def applies(self, q: Query) -> bool:
        p = q.predicate
        return q.kind in ("question", "assertion") and p in ("rel.exceeds", "rel.equal_on", "rel.extreme", "rel.has_property") and (
            p != "rel.has_property" or self._gradable_query(q) is not None)

    def _gradable_query(self, q: Query) -> tuple[str, int] | None:
        """'Who is older?' parses as has_property(?who, old): interpret it as a superlative over everyone known."""
        if q.kind != "question" or "subject" not in q.variables:
            return None
        from ..language.en.lexicon import GRADABLE
        t = q.terms.get("property")
        if not t:
            return None
        g = GRADABLE.get(t.get("key") or "")
        return (g[0], g[1]) if g else None

    def _dim(self, q: Query) -> str | None:
        if q.predicate == "rel.has_property":
            g = self._gradable_query(q)
            return g[0] if g else None
        t = q.terms.get("dimension")
        return t["key"] if t else None

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        dim = self._dim(q)
        if dim is None:
            return Conclusion(status="unsupported", strategy=self.name, notes=["comparison without a recognised dimension"])
        m = OrderModel(dim, fb)
        notes = list(m.skipped)
        conflict = m.conflict()
        if conflict:
            return Conclusion(status="contradiction", strategy=self.name, confidence=None, contradictions=[conflict],
                              steps=[f"The stated {_dim_label(dim)} relations cannot all hold: {self._explain_conflict(conflict)}"],
                              evidence=[evidence_for(f) for f in self._conflict_facts(m)], notes=notes)
        if q.kind == "assertion":
            return Conclusion(status="consistent", strategy=self.name, answer={"dimension": dim, "entities": m.items}, confidence=1.0,
                              steps=[f"The {_dim_label(dim)} relations stated so far are mutually consistent ({len(m.items)} entities)."], notes=notes)
        if q.predicate == "rel.exceeds":
            return self._exceeds(q, m, dim, notes)
        if q.predicate == "rel.equal_on":
            return self._equal(q, m, dim, notes)
        if q.predicate == "rel.has_property":
            pole = "high" if self._gradable_query(q)[1] > 0 else "low"
            q.notes.append("'Who is <comparative>?' was read as asking for the " + POLE_WORD[pole] + f" {_dim_label(dim)} among everyone known")
            return self._extreme_wh(q, m, dim, pole, notes)
        pole = q.prop.annotations.get("pole") or "high"
        if "subject" in q.variables:
            return self._extreme_wh(q, m, dim, pole, notes)
        return self._extreme_yn(q, m, dim, pole, notes)

    # -- helpers --------------------------------------------------------------------------------------------------
    def _explain_conflict(self, c: dict) -> str:
        if c["kind"] == "ordering_cycle":
            return " > ".join(c["cycle"]) + " (circular)"
        return f"'{c['pair'][0]} is not greater than {c['pair'][1]}' contradicts the other statements"

    def _conflict_facts(self, m: OrderModel) -> list[Any]:
        out: list[Any] = []
        cyc = m.po.find_cycle()
        if cyc:
            if len(cyc) > 1 and cyc[0] == cyc[-1]:
                cyc = cyc[:-1]
            for a, b in zip(cyc, cyc[1:] + cyc[:1]):
                f = m.facts.get((a, b))
                if f is not None:
                    out += list(f) if isinstance(f, tuple) else [f]
        else:
            for a, b, f in m.po.violations():
                out += list(m.facts_on_path(a, b)) + ([f] if hasattr(f, "predicate") else [])
        return out

    def _entity_key(self, m: OrderModel, term: dict | None) -> str | None:
        if term is None:
            return None
        return term["key"] if term["key"] in m.labels else None

    def _crosscheck(self, m: OrderModel, expect_min: str | None = None, expect_max: str | None = None, dom: list[str] | None = None) -> tuple[str, list[dict] | None]:
        rk = m.csp()
        if rk is None:
            return "CSP cross-check skipped (more than 8 entities).", None
        if not rk:
            return "CSP cross-check found NO consistent ranking (conflict with the partial-order result).", rk
        msg = f"CSP cross-check: {len(rk)} consistent ranking(s) enumerated."
        for key, extreme in ((expect_min, "min"), (expect_max, "max")):
            if key is None:
                continue
            target = min if extreme == "min" else max
            d = dom or m.items
            ok = all(r[key] == target(r[x] for x in d) and sum(1 for x in d if r[x] == r[key]) == 1 for r in rk)
            msg += f" '{m.labels[key]}' is the unique {'lowest' if extreme == 'min' else 'highest'} in {'all' if ok else 'NOT all'} of them."
            if not ok:
                msg += " (DISAGREEMENT)"
        return msg, rk

    def _extreme_wh(self, q: Query, m: OrderModel, dim: str, pole: str, notes: list[str]) -> Conclusion:
        dom = list(m.items)
        cand = q.terms.get("candidates")
        if cand:
            keys = [t["key"] for t in cand.get("members", [])]
            absent = [t.get("label") or t["key"] for t in cand.get("members", []) if t["key"] not in m.labels]
            if absent:
                return Conclusion(status="unknown", strategy=self.name, answer={"type": "entity", "value": None},
                                  missing=[f"any {_dim_label(dim)} comparison involving {' or '.join(absent)}"],
                                  steps=[f"I have no {_dim_label(dim)} information about {' or '.join(absent)}."], notes=notes)
            dom = keys
            q.notes.append(f"Choosing among {', '.join(m.labels[k] for k in keys)} only")
        if len(dom) < 2:
            return Conclusion(status="unknown", strategy=self.name, missing=[f"at least two entities compared on {_dim_label(dim)}"],
                              steps=[f"I have {len(dom)} entity(ies) with a {_dim_label(dim)} comparison; a superlative needs at least two."], notes=notes + q.notes)
        winner = m.po.unique_maximum(dom) if pole == "high" else m.po.unique_minimum(dom)
        word = POLE_WORD[pole]
        if winner is not None:
            others = [o for o in dom if o != winner]
            used: list[Any] = []
            steps = []
            for o in others:
                a, b = (winner, o) if pole == "high" else (o, winner)
                used += m.facts_on_path(a, b)
                rel = m.po.compare(winner, o)
                steps.append(f"{m.path_text(a, b)}" if rel in (">", "<") else f"{m.labels[winner]} vs {m.labels[o]}")
            steps.append(f"Therefore {m.labels[winner]} has the {word} {_dim_label(dim)} among {', '.join(m.labels[i] for i in dom)}.")
            msg, rk = self._crosscheck(m, **({"expect_max": winner} if pole == "high" else {"expect_min": winner}), dom=dom)
            conf = _facts_conf(used)
            if "DISAGREEMENT" in msg or (rk is not None and not rk):
                conf *= 0.5
            uniq = {id(f): f for f in used}
            return Conclusion(status="answered", strategy=self.name, confidence=round(conf, 3), steps=steps + [msg],
                              answer={"type": "entity", "value": {"key": winner, "label": m.labels[winner]},
                                      "relation": {"dimension": dim, "pole": pole}, "domain": [m.labels[i] for i in dom]},
                              evidence=[evidence_for(f) for f in uniq.values()], notes=notes + q.notes)
        cands = m.po.maximal(dom) if pole == "high" else m.po.minimal(dom)
        msg, rk = self._crosscheck(m, dom=dom)
        alts = []
        for c in cands:
            if rk:
                tgt = max if pole == "high" else min
                share = sum(1 for r in rk if r[c] == tgt(r[x] for x in dom)) / len(rk)
                alts.append({"label": m.labels[c], "key": c, "consistent_orderings_share": round(share, 3)})
            else:
                alts.append({"label": m.labels[c], "key": c})
        return Conclusion(status="underdetermined", strategy=self.name, confidence=None, alternatives=alts,
                          missing=[f"how {' and '.join(m.labels[c] for c in cands)} compare on {_dim_label(dim)}"],
                          steps=[f"The {word} {_dim_label(dim)} cannot be decided from what is known: {', '.join(m.labels[c] for c in cands)} are not ordered relative to each other.", msg],
                          answer={"type": "candidates", "dimension": dim, "pole": pole}, notes=notes + q.notes)

    def _extreme_yn(self, q: Query, m: OrderModel, dim: str, pole: str, notes: list[str]) -> Conclusion:
        subj = self._entity_key(m, q.terms.get("subject"))
        if subj is None:
            return self._unknown_entity(q, m, dim, q.terms.get("subject"), notes)
        concl = self._extreme_wh(q, m, dim, pole, notes)
        word = POLE_WORD[pole]
        if concl.status == "answered":
            yes = concl.answer["value"]["key"] == subj
            concl.status = "yes" if yes else "no"
            concl.answer = {"type": "boolean", "value": yes, "proposition": f"{m.labels[subj]} has the {word} {_dim_label(dim)}", "actual": concl.answer["value"]}
            return concl
        # not uniquely determined: still decidable if the subject is provably not extreme
        for o in m.items:
            if o != subj and m.po.compare(o, subj) == (">" if pole == "high" else "<"):
                a, b = (o, subj) if pole == "high" else (subj, o)
                return Conclusion(status="no", strategy=self.name, confidence=round(_facts_conf(m.facts_on_path(a, b)), 3),
                                  steps=[m.path_text(a, b), f"So {m.labels[subj]} is not the {word} {_dim_label(dim)}."],
                                  answer={"type": "boolean", "value": False}, evidence=[evidence_for(f) for f in {id(x): x for x in m.facts_on_path(a, b)}.values()], notes=notes)
        concl.status = "unknown"
        concl.answer = {"type": "boolean", "value": None}
        return concl

    def _unknown_entity(self, q: Query, m: OrderModel, dim: str, term: dict | None, notes: list[str]) -> Conclusion:
        name = _label(term) if term else "that"
        return Conclusion(status="unknown", strategy=self.name, missing=[f"any {_dim_label(dim)} comparison involving {name}"],
                          steps=[f"I have no {_dim_label(dim)} information about {name}."], answer={"type": "boolean", "value": None}, notes=notes)

    def _exceeds(self, q: Query, m: OrderModel, dim: str, notes: list[str]) -> Conclusion:
        g, l = q.terms.get("greater"), q.terms.get("lesser")
        if "greater" in q.variables or "lesser" in q.variables:
            return self._who_relative(q, m, dim, notes)
        a, b = self._entity_key(m, g), self._entity_key(m, l)
        if a is None or b is None:
            return self._unknown_entity(q, m, dim, g if a is None else l, notes)
        rel = m.po.compare(a, b)
        adj = q.prop.annotations.get("adjective")
        phrase = f"{m.labels[a]} is {'not ' if q.prop.polarity == 'negative' else ''}greater than {m.labels[b]} in {_dim_label(dim)}"
        if rel == ">":
            facts = m.facts_on_path(a, b)
            return Conclusion(status="yes", strategy=self.name, confidence=round(_facts_conf(facts), 3), steps=[m.path_text(a, b), "By transitivity of the stated comparisons: " + phrase + "."],
                              answer={"type": "boolean", "value": True, "proposition": phrase}, evidence=[evidence_for(f) for f in {id(x): x for x in facts}.values()], notes=notes)
        if rel in ("<", "="):
            if rel == "<":
                facts = m.facts_on_path(b, a)
                step = m.path_text(b, a)
            else:
                facts = [m.eq_facts.get(frozenset((a, b)))] if m.eq_facts.get(frozenset((a, b))) else []
                facts = [x for f in facts for x in (f if isinstance(f, tuple) else [f])]
                step = f"{m.labels[a]} = {m.labels[b]}"
            return Conclusion(status="no", strategy=self.name, confidence=round(_facts_conf(facts), 3), steps=[step, f"So {m.labels[a]} is {'younger/lower than' if rel == '<' else 'equal to'} {m.labels[b]}, not greater."],
                              answer={"type": "boolean", "value": False, "relation": rel, "proposition": phrase}, evidence=[evidence_for(f) for f in {id(x): x for x in facts}.values()], notes=notes)
        return Conclusion(status="unknown", strategy=self.name, answer={"type": "boolean", "value": None},
                          missing=[f"a chain of {_dim_label(dim)} comparisons connecting {m.labels[a]} and {m.labels[b]}"],
                          steps=[f"{m.labels[a]} and {m.labels[b]} are not connected by any stated {_dim_label(dim)} comparison."], notes=notes)

    def _equal(self, q: Query, m: OrderModel, dim: str, notes: list[str]) -> Conclusion:
        a, b = self._entity_key(m, q.terms.get("first")), self._entity_key(m, q.terms.get("second"))
        if a is None or b is None:
            return self._unknown_entity(q, m, dim, q.terms.get("first") if a is None else q.terms.get("second"), notes)
        rel = m.po.compare(a, b)
        if rel == "=":
            return Conclusion(status="yes", strategy=self.name, confidence=0.9, steps=[f"{m.labels[a]} = {m.labels[b]} in {_dim_label(dim)}"], answer={"type": "boolean", "value": True}, notes=notes)
        if rel in (">", "<"):
            return Conclusion(status="no", strategy=self.name, confidence=0.9, steps=[m.path_text(a, b) if rel == ">" else m.path_text(b, a)], answer={"type": "boolean", "value": False}, notes=notes)
        return Conclusion(status="unknown", strategy=self.name, answer={"type": "boolean", "value": None}, missing=[f"how {m.labels[a]} and {m.labels[b]} compare"], notes=notes)

    def _who_relative(self, q: Query, m: OrderModel, dim: str, notes: list[str]) -> Conclusion:
        if "greater" in q.variables:
            ref = self._entity_key(m, q.terms.get("lesser"))
            sel = lambda x: m.po.compare(x, ref) == ">"
            direction = "greater"
        else:
            ref = self._entity_key(m, q.terms.get("greater"))
            sel = lambda x: m.po.compare(ref, x) == ">"
            direction = "lesser"
        if ref is None:
            return self._unknown_entity(q, m, dim, q.terms.get("lesser") or q.terms.get("greater"), notes)
        found = [x for x in m.items if x != ref and sel(x)]
        unknown_rel = [x for x in m.items if x != ref and m.po.compare(x, ref) == "?"]
        if not found:
            return Conclusion(status="unknown", strategy=self.name, answer={"type": "entities", "value": []},
                              steps=[f"No entity is known to be {direction} than {m.labels[ref]} on {_dim_label(dim)}."], missing=[f"{_dim_label(dim)} comparisons involving {m.labels[ref]}"],
                              alternatives=[{"label": m.labels[x], "note": "relation unknown"} for x in unknown_rel], notes=notes)
        facts: list[Any] = []
        for x in found:
            facts += m.facts_on_path(x, ref) if direction == "greater" else m.facts_on_path(ref, x)
        return Conclusion(status="answered", strategy=self.name, confidence=round(_facts_conf(facts), 3),
                          answer={"type": "entities", "value": [{"key": x, "label": m.labels[x]} for x in found], "relation": {"dimension": dim, "direction": direction, "reference": m.labels[ref]}},
                          steps=[(m.path_text(x, ref) if direction == "greater" else m.path_text(ref, x)) for x in found],
                          evidence=[evidence_for(f) for f in {id(x): x for x in facts}.values()],
                          alternatives=[{"label": m.labels[x], "note": "relation unknown"} for x in unknown_rel], notes=notes + ["Only entities I know about are considered."])


# ====================================================================================================================
# Taxonomy, property inheritance (syllogisms) and location
# ====================================================================================================================
class _Graph:
    def __init__(self, fb: FactBase):
        self.up: dict[str, list[tuple[str, Any]]] = {}
        self.neg: list[tuple[str, str, Any]] = []
        self.labels: dict[str, str] = {}
        for f in fb.get("rel.is_a"):
            s, o = f.args.get("subject"), f.args.get("object")
            if not s or not o:
                continue
            self.labels[s["key"]] = _label(s)
            self.labels[o["key"]] = _label(o)
            if f.polarity == "positive":
                self.up.setdefault(s["key"], []).append((o["key"], f))
            else:
                self.neg.append((s["key"], o["key"], f))

    def ancestors(self, start: str) -> dict[str, list[Any]]:
        """node -> list of facts proving start is_a node (shortest path)."""
        out: dict[str, list[Any]] = {start: []}
        queue = deque([start])
        while queue:
            n = queue.popleft()
            for m, f in self.up.get(n, []):
                if m not in out:
                    out[m] = out[n] + [f]
                    queue.append(m)
        return out


def _kind_of(term: dict, g: "_Graph | None" = None) -> str:
    """Key used for taxonomy lookups. A common-noun instance ("the whale") or an entity whose label is a known kind maps to that kind."""
    key = term["key"]
    if term.get("t") == "entity" and (term.get("instance") or (g is not None and f"kind.{key}" in g.labels and key not in g.labels)):
        return "kind." + key
    return key


class TaxonomyStrategy(Strategy):
    name = "taxonomy_syllogism"
    family = "deductive"
    handles = ("is-a questions with transitive closure; universal negatives inherited by subtypes; property inheritance through is-a chains "
               "('All men are mortal. Socrates is a man. Is Socrates mortal?').")
    boundaries = ("Open world: failure to derive is 'unknown', never 'no'. Only universally quantified or kind-level statements are inherited; "
                  "no exceptions/defaults (a stated universal is taken at its word and flagged as a user premise).")

    def applies(self, q: Query) -> bool:
        return q.kind in ("question", "assertion") and q.predicate in ("rel.is_a", "rel.has_property") and (
            q.kind == "assertion" or ("subject" in q.terms and (q.predicate == "rel.is_a" or "property" in q.terms)))

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        g = _Graph(fb)
        if q.kind == "assertion":
            return self._consistency(q, g, fb)
        s = q.terms.get("subject")
        if q.predicate == "rel.is_a":
            return self._is_a(q, g, s, q.terms.get("object"))
        return self._has_property(q, g, fb, s, q.terms["property"])

    def _is_a(self, q: Query, g: _Graph, s: dict, o: dict | None) -> Conclusion:
        if o is None:
            return Conclusion(status="unsupported", strategy=self.name)
        sk, ok = _kind_of(s, g), _kind_of(o, g)
        anc = g.ancestors(sk)
        if ok in anc:
            path = anc[ok]
            chain_txt = " → ".join([g.labels.get(sk, sk)] + [g.labels.get(f.args["object"]["key"], "?") for f in path])
            direct = sk == ok
            return Conclusion(status="yes", strategy=self.name, confidence=round(chain([f.confidence for f in path]) if path else 1.0, 3),
                              steps=[chain_txt if path else "identity"] + (["By transitivity of is-a."] if len(path) > 1 else []),
                              answer={"type": "boolean", "value": True}, evidence=[evidence_for(f) for f in path])
        for a, b, f in g.neg:
            if b == ok and a in anc:
                where = anc[a]
                chain_txt = " → ".join([g.labels.get(sk, sk)] + [g.labels.get(x.args["object"]["key"], "?") for x in where])
                applicable = f.quantifier in ("all", "no") or a == sk
                if applicable:
                    return Conclusion(status="no", strategy=self.name, confidence=round(chain([f.confidence] + [x.confidence for x in where]), 3),
                                      steps=[f"{chain_txt}; and it is stated that {g.labels[a]} is not a kind of {g.labels[b]}."],
                                      answer={"type": "boolean", "value": False}, evidence=[evidence_for(x) for x in where + [f]])
        return Conclusion(status="unknown", strategy=self.name, answer={"type": "boolean", "value": None},
                          steps=[f"No chain of is-a statements links {g.labels.get(sk, _label(s))} to {_label(o)}."], missing=[f"is-a information connecting {_label(s)} and {_label(o)}"])

    def _has_property(self, q: Query, g: _Graph, fb: FactBase, s: dict, prop: dict) -> Conclusion:
        sk, pk = _kind_of(s, g), prop["key"]
        props = fb.get("rel.has_property")
        anc = g.ancestors(sk)
        for f in props:
            subj = f.args.get("subject")
            if not subj or f.key_of("property") != pk or subj["key"] not in anc:
                continue
            if f.args.get("value") is not None:
                continue
            inherits = subj["key"] == sk or f.quantifier in ("all", None) and subj.get("t") == "kind"
            if not inherits:
                continue
            path = anc[subj["key"]]
            yes = f.polarity == "positive"
            steps = [f"{describe(x)}" for x in path] + [describe(f), f"Therefore {_label(s)} {'has' if yes else 'lacks'} the property '{_label(prop)}'."]
            ev = [evidence_for(x) for x in path] + [evidence_for(f)]
            return Conclusion(status="yes" if yes else "no", strategy=self.name,
                              confidence=round(chain([x.confidence for x in path] + [f.confidence]), 3), steps=steps,
                              answer={"type": "boolean", "value": yes, "inherited_from": g.labels.get(subj["key"], subj["key"])}, evidence=ev,
                              assumptions=([f"Taking the universal statement '{describe(f)}' at its word (no exceptions considered)."] if subj["key"] != sk else []))
        return Conclusion(status="unknown", strategy=self.name, answer={"type": "boolean", "value": None},
                          steps=[f"Nothing I know lets me conclude whether {_label(s)} has the property '{_label(prop)}'."], missing=[f"a statement that {_label(s)} or one of its kinds {'has' if True else ''} '{_label(prop)}'"])

    def _consistency(self, q: Query, g: _Graph, fb: FactBase) -> Conclusion:
        """A newly stated is_a/negative is_a/property must not clash with what is derivable."""
        prop = q.prop
        if q.predicate == "rel.is_a" and "subject" in q.terms and "object" in q.terms:
            sk, ok = _kind_of(q.terms["subject"], g), _kind_of(q.terms["object"], g)
            anc = g.ancestors(sk)
            if prop.polarity == "positive":
                for a, b, f in g.neg:
                    if b == ok and a in anc and f.source_id != "turn":
                        return Conclusion(status="contradiction", strategy=self.name, contradictions=[{"kind": "taxonomy", "note": describe(f)}],
                                          steps=[f"This conflicts with: {describe(f)}"], evidence=[evidence_for(f)])
            else:
                if ok in anc and anc[ok]:
                    return Conclusion(status="contradiction", strategy=self.name, contradictions=[{"kind": "taxonomy", "note": "derivable positive is-a"}],
                                      steps=["The opposite already follows from: " + "; ".join(describe(x) for x in anc[ok])], evidence=[evidence_for(x) for x in anc[ok]])
        return Conclusion(status="consistent", strategy=self.name, confidence=1.0, steps=["No conflict with known is-a statements."])


class LocationStrategy(Strategy):
    name = "location_containment"
    family = "deductive"
    handles = "'Is Paris in Europe?' via transitive located_in chains (Paris → France → Europe)."
    boundaries = "Positive containment only; no distances, borders or negative containment inference (unknown is reported)."

    def applies(self, q: Query) -> bool:
        return q.kind == "question" and q.predicate == "rel.located_in" and "figure" in q.terms and "ground" in q.terms

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        f_, g_ = q.terms["figure"]["key"], q.terms["ground"]["key"]
        up: dict[str, list[tuple[str, Any]]] = {}
        for f in fb.get("rel.located_in"):
            if f.polarity == "positive":
                up.setdefault(f.key_of("figure"), []).append((f.key_of("ground"), f))
        out: dict[str, list[Any]] = {f_: []}
        dq = deque([f_])
        while dq:
            n = dq.popleft()
            for m, f in up.get(n, []):
                if m not in out:
                    out[m] = out[n] + [f]
                    dq.append(m)
        if g_ in out and out[g_]:
            path = out[g_]
            labels = [render_term(path[0].args["figure"])] + [render_term(p.args["ground"]) for p in path]
            return Conclusion(status="yes", strategy=self.name, confidence=round(chain([p.confidence * (1 if p.source_type != "seed_curated" else 1.0) for p in path]), 3),
                              steps=[" → ".join(labels)] + (["By transitivity of containment."] if len(path) > 1 else []), answer={"type": "boolean", "value": True},
                              evidence=[evidence_for(p) for p in path])
        # a different capital/country relation can refute only via explicit negative facts
        for f in fb.get("rel.located_in"):
            if f.polarity == "negative" and f.key_of("figure") == f_ and f.key_of("ground") == g_:
                return Conclusion(status="no", strategy=self.name, confidence=f.confidence, steps=[describe(f)], answer={"type": "boolean", "value": False}, evidence=[evidence_for(f)])
        known_in = [render_term(f.args["ground"]) for f in fb.get("rel.located_in") if f.polarity == "positive" and f.key_of("figure") == f_]
        steps = [f"I have no containment chain from {render_term(q.terms['figure'])} to {render_term(q.terms['ground'])}."]
        if known_in:
            steps.append(f"I only know {render_term(q.terms['figure'])} is located in {', '.join(sorted(set(known_in)))}.")
        return Conclusion(status="unknown", strategy=self.name, steps=steps, answer={"type": "boolean", "value": None},
                          missing=[f"where {render_term(q.terms['figure'])} is located"])


# ====================================================================================================================
# Attribute lookup (knowledge retrieval)
# ====================================================================================================================
class AttributeLookupStrategy(Strategy):
    name = "attribute_lookup"
    family = "retrieval"
    handles = "attr.* questions: 'What is the capital of France?', 'What is my name?', 'Is the capital of Kenya Nairobi?'; self-knowledge about AVOENIX."
    boundaries = ("Only stored or stated facts; disputed facts are reported but not asserted; unknown entities produce 'unknown' with fuzzy suggestions "
                  "(never an automatic correction).")

    def applies(self, q: Query) -> bool:
        return q.kind == "question" and bool(q.predicate) and q.predicate.startswith("attr.") and "owner" in q.terms

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        owner = q.terms["owner"]
        facts = [f for f in fb.get(q.predicate) if f.key_of("owner") == owner["key"] and f.polarity == "positive"]
        facts.sort(key=lambda f: (f.level != "turn", -f.reliability))
        what = f"{q.predicate[5:]} of {_label(owner)}"
        disputed = [f for f in fb.disputed(q.predicate) if f.key_of("owner") == owner["key"]]
        notes = []
        if disputed:
            notes.append("Conflicting claims are held as disputed: " + "; ".join(render_term(f.args["value"]) + f" ({f.source_type})" for f in disputed))
        if "value" in q.variables:
            if facts:
                best = facts[0]
                alts = [{"label": render_term(f.args["value"]), "source": f.source_type} for f in facts[1:] if f.key_of("value") != best.key_of("value")]
                conf = best.confidence if (owner.get("key") == SELF_USER and best.source_type == "user_statement") else best.reliability   # users are the authority on themselves
                return Conclusion(status="answered", strategy=self.name, confidence=round(conf, 3), answer={"type": "value", "value": best.args["value"], "attribute": q.predicate, "owner": owner},
                                  steps=[describe(best)], evidence=[evidence_for(best)], alternatives=alts, notes=notes)
            found = fb.knowledge.find_entity(fb.scope, owner.get("label") or owner["key"]) if owner.get("t") == "entity" else {"found": False, "suggestions": []}
            steps = [f"I have no recorded {what}."]
            if found.get("suggestions"):
                steps.append("Similar names I do know: " + ", ".join(s["label"] for s in found["suggestions"]))
            return Conclusion(status="unknown", strategy=self.name, steps=steps, missing=[what], notes=notes, answer={"type": "value", "value": None, "suggestions": found.get("suggestions", [])})
        val = q.terms.get("value")
        if val is None:
            return Conclusion(status="unsupported", strategy=self.name)
        for f in facts:
            if f.key_of("value") == val["key"]:
                return Conclusion(status="yes", strategy=self.name, confidence=round(f.reliability, 3), steps=[describe(f)], answer={"type": "boolean", "value": True}, evidence=[evidence_for(f)], notes=notes)
        if facts and q.predicate in ("attr.capital", "attr.name", "attr.age", "attr.birthday", "attr.currency"):
            f = facts[0]
            return Conclusion(status="no", strategy=self.name, confidence=round(f.reliability, 3), steps=[describe(f), f"{what} has a single value, so it is not {render_term(val)}."],
                              answer={"type": "boolean", "value": False, "actual": f.args["value"]}, evidence=[evidence_for(f)], notes=notes)
        return Conclusion(status="unknown", strategy=self.name, steps=[f"I have no recorded {what} to compare with."], answer={"type": "boolean", "value": None}, missing=[what], notes=notes)


# ====================================================================================================================
# Arithmetic
# ====================================================================================================================
def _explain(tree: Any, steps: list[str]) -> Fraction:
    if isinstance(tree, (int, float, Fraction, str)) and not isinstance(tree, tuple):
        return arithmetic.evaluate(tree)
    op, *args = tree
    vals = [_explain(a, steps) if isinstance(a, tuple) else arithmetic.evaluate(a) for a in args]
    res = arithmetic.evaluate(tree)
    if any(isinstance(a, tuple) for a in args):
        steps.append(f"{op}({', '.join(arithmetic.render(v) for v in vals)}) = {arithmetic.render(res)}")
    return res


class ArithmeticStrategy(Strategy):
    name = "exact_arithmetic"
    family = "mathematical"
    handles = "+ - × ÷, powers, roots, percentages, remainders over exact rationals (no floating point, no eval)."
    boundaries = "Single expressions only; no algebra with unknowns, no word problems with state; irrational results are reported as unsupported."

    def applies(self, q: Query) -> bool:
        return q.kind == "arithmetic" and q.math is not None

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        m = q.math
        if m.get("error"):
            return Conclusion(status="undefined", strategy=self.name, answer={"type": "number", "error": m["error"]}, confidence=1.0,
                              steps=[f"The expression {m.get('surface')} is undefined: {m['error']}."])
        try:
            steps: list[str] = []
            val = _explain(m["tree"], steps)
        except arithmetic.ArithmeticError_ as e:
            return Conclusion(status="undefined", strategy=self.name, answer={"type": "number", "error": str(e)}, confidence=1.0, steps=[f"Cannot evaluate: {e}"])
        shown = arithmetic.render(val)
        steps.append(f"{m.get('surface')} = {shown}")
        exact = f"{val.numerator}/{val.denominator}" if val.denominator != 1 else str(val.numerator)
        return Conclusion(status="answered", strategy=self.name, confidence=1.0, steps=steps, answer={"type": "number", "value": shown, "exact": exact, "expression": m.get("surface")},
                          evidence=[Evidence(kind="arithmetic", statement=f"{m.get('surface')} = {shown}", source="system", confidence=1.0)],
                          notes=["Computed exactly with rational arithmetic."])


# ====================================================================================================================
# Contradiction detection on statements
# ====================================================================================================================
class ContradictionStrategy(Strategy):
    name = "contradiction_detection"
    family = "consistency"
    handles = "New statements against stored/stated knowledge: negation, single-valued attributes, circular comparisons."
    boundaries = "Detects direct and order-based conflicts; not arbitrary logical inconsistency across unrelated predicates."

    def applies(self, q: Query) -> bool:
        return q.kind == "assertion" and q.predicate is not None and (q.predicate.startswith("attr.") or q.predicate in ("rel.is_a", "rel.has_property", "rel.located_in"))

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        prop = q.prop
        found = []
        for f in fb.get(prop.predicate):
            if f.source_id == "turn":
                continue
            same_args = all(f.args.get(r, {}).get("key") == t.get("key") for r, t in q.terms.items())
            if same_args and f.polarity != prop.polarity and f.quantifier == prop.quantifier:
                found.append({"kind": "negation", "with": describe(f), "source": f.source_type})
            elif prop.predicate.startswith("attr.") and prop.polarity == "positive" and f.polarity == "positive" and "owner" in q.terms and f.key_of("owner") == q.terms["owner"]["key"] \
                    and "value" in q.terms and f.key_of("value") != q.terms["value"]["key"]:
                found.append({"kind": "different_value", "with": describe(f), "source": f.source_type})
        if found:
            return Conclusion(status="contradiction", strategy=self.name, contradictions=found, steps=[f"This conflicts with: {c['with']} ({c['source']})" for c in found])
        return Conclusion(status="consistent", strategy=self.name, confidence=1.0, steps=["No stored statement conflicts with this one."])


# ====================================================================================================================
# Induction (generalisation from instances) and abduction (hypotheses)
# ====================================================================================================================
class InductionStrategy(Strategy):
    name = "inductive_generalisation"
    family = "inductive"
    handles = "'Do <kind> have <property>?' answered tentatively from known instances using Laplace's rule of succession; needs >= 3 instances."
    boundaries = "Never returns a certain answer; result status is 'likely'/'unknown' with support counts; deductive knowledge always takes precedence."

    MIN_INSTANCES = 3

    def applies(self, q: Query) -> bool:
        return q.kind == "question" and q.predicate == "rel.has_property" and q.terms.get("subject", {}).get("t") == "kind" and "property" in q.terms

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        kind, prop = q.terms["subject"]["key"], q.terms["property"]["key"]
        members = {}
        for f in fb.get("rel.is_a"):
            if f.polarity == "positive" and f.key_of("object") == kind and f.args["subject"].get("t") == "entity":
                members[f.args["subject"]["key"]] = f.args["subject"]
        pos, neg = [], []
        for f in fb.get("rel.has_property"):
            if f.key_of("property") == prop and f.key_of("subject") in members and f.quantifier is None:
                (pos if f.polarity == "positive" else neg).append(f)
        n = len(pos) + len(neg)
        if n < self.MIN_INSTANCES:
            return Conclusion(status="unknown", strategy=self.name, answer={"type": "boolean", "value": None},
                              steps=[f"I know {n} example(s) of {q.terms['subject']['label']} with a recorded value for this property; I need at least {self.MIN_INSTANCES} to generalise."],
                              missing=["more examples"], notes=["No generalisation attempted."])
        p = laplace(len(pos), n)
        if len(neg) == 0:
            status, word = "likely", "all"
        elif len(pos) == 0:
            status, word = "likely", "none"
            p = 1 - p
        else:
            status, word = "unknown", "mixed"
        steps = [f"{len(pos)} of {n} known {q.terms['subject']['label']} instances have the property; {len(neg)} do not.", f"Laplace support (s+1)/(n+2) = {p:.2f} — a heuristic, not a probability."]
        return Conclusion(status=status, strategy=self.name, confidence=round(p, 3) if status == "likely" else None,
                          answer={"type": "generalisation", "pattern": word, "positive": len(pos), "negative": len(neg)}, steps=steps,
                          evidence=[evidence_for(f) for f in (pos + neg)[:6]], notes=["Inductive: exceptions are possible; this is not a proof."],
                          assumptions=["The known instances are representative."])


class AbductionStrategy(Strategy):
    name = "hypothesis_generation"
    family = "abductive"
    handles = "Why an ordering question is unanswered: lists candidate answers as hypotheses, scores each by the share of consistent orderings supporting it, and names the observation that would decide."
    boundaries = "Hypotheses are scored by counting consistent weak orders (≤ 8 entities); the share is not a probability of being true."

    def applies(self, q: Query) -> bool:
        return q.kind == "question" and q.predicate == "rel.extreme" and "subject" in q.variables

    def run(self, q: Query, fb: FactBase) -> Conclusion:
        dim = q.terms["dimension"]["key"]
        pole = q.prop.annotations.get("pole") or "high"
        m = OrderModel(dim, fb)
        if len(m.items) < 2 or not m.consistent():
            return Conclusion(status="unsupported", strategy=self.name)
        rk = m.csp()
        if rk is None or not rk:
            return Conclusion(status="unsupported", strategy=self.name)
        tgt = max if pole == "high" else min
        hyps = []
        for it in m.items:
            share = sum(1 for r in rk if r[it] == tgt(r.values()) and sum(1 for v in r.values() if v == r[it]) == 1) / len(rk)
            if share > 0:
                hyps.append({"label": m.labels[it], "key": it, "consistent_orderings_share": round(share, 3)})
        hyps.sort(key=lambda h: -h["consistent_orderings_share"])
        if len(hyps) <= 1:
            return Conclusion(status="unsupported", strategy=self.name)
        top = [h["label"] for h in hyps]
        return Conclusion(status="underdetermined", strategy=self.name, alternatives=hyps,
                          steps=[f"{len(rk)} orderings are consistent with the facts; {len(hyps)} different entities could have the {POLE_WORD[pole]} {_dim_label(dim)}."],
                          missing=[f"a comparison between {top[0]} and {top[1]}"], answer={"type": "hypotheses"})


DEFAULT_STRATEGIES: list[type[Strategy]] = [
    ArithmeticStrategy, OrderingStrategy, TaxonomyStrategy, LocationStrategy, AttributeLookupStrategy, ContradictionStrategy, InductionStrategy, AbductionStrategy,
]
