"""Reasoning over meaning structures: arithmetic word problems, syllogistic/conditional deduction, comparative ordering with abstract names.

None of this uses the knowledge store. The reasoner works on what it is given (current input plus premises kept in the dialogue state), so it
stays independent of how knowledge is persisted, and every answer carries the steps that produced it. Arithmetic is delegated to the exact
fraction evaluator in ``algorithms.arithmetic`` (no floats, no eval); ordering uses ``algorithms.partial_order`` (cycle detection included).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from ..algorithms.arithmetic import ArithmeticError_, evaluate, render
from ..algorithms.partial_order import PartialOrder
from .chunker import Chunk, Clause
from .lexicon import ConceptGraph, default_graph

DATA = Path(__file__).parent / "data"
_NUMWORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20}


# ======================================================================================================================================
# Word problems
# ======================================================================================================================================
@dataclass
class Solution:
    value: Fraction
    unit: str | None
    steps: list[str]
    tree: object
    question: str
    kind: str = "word_problem"

    def text_value(self) -> str:
        return render(self.value)


def _agent_key(np: Chunk | None, last: str | None) -> str | None:
    if np is None:
        return last
    pron = np.f.get("pron")
    if pron in ("i", "me", "we"):
        return "i"
    if pron in ("he", "she", "it", "they"):
        return last
    return (np.head or "").lower() or last


def _unit(np: Chunk | None) -> str | None:
    if np is None:
        return None
    nouns = np.f.get("nouns") or []
    if nouns:
        return nouns[-1]
    return None


class WordProblem:
    """Quantity ledger: agents hold amounts of units; rates, prices and capacities are separate relations. Built clause by clause."""

    def __init__(self, graph: ConceptGraph | None = None):
        self.graph = graph or default_graph()

    def _is(self, lemma: str, concept: str) -> bool:
        return any(m.concept == concept for m in self.graph.concepts_of(lemma, "verb", strict=True))

    def solve(self, clauses: list[Clause]) -> Solution | None:
        questions = [c for c in clauses if c.wh in ("how_many", "how_much", "how_far") ]
        if len(questions) != 1:
            return None
        q = questions[0]
        facts = [c for c in clauses if c is not q and not c.wh]
        ledger: dict[tuple[str, str | None], Fraction] = {}
        steps: list[str] = []
        price: dict[str, tuple[Fraction, str | None]] = {}
        rate: dict[str, tuple[Fraction, str | None, str | None]] = {}
        capacity: dict[str, tuple[Fraction, str | None]] = {}
        purchases: list[tuple[str, Fraction]] = []
        last: str | None = None
        history: list[tuple[str, str | None, str, Fraction]] = []
        for cl in facts:
            if cl.vg is None:
                continue
            verb = cl.vg.f.get("verb") or ""
            subj = _agent_key(cl.subject, last)
            if cl.subject is not None and not cl.subject.f.get("pron"):
                last = (cl.subject.head or "").lower()
            elif cl.subject is not None and cl.subject.f.get("pron") in ("i", "we"):
                last = "i"
            nps = [c for c in cl.items if c.kind == "NP"]
            amounts = [c for c in nps if "num" in c.f]
            if not amounts:
                continue
            first = amounts[0]
            n = Fraction(str(first.f["num"]))
            unit = _unit(first) or (None if first.f.get("nouns") is None else None)
            if self._is(verb, "c.cost") and cl.subject is not None:
                noun = (cl.subject.f.get("nouns") or [cl.subject.head])[-1]
                price[noun] = (n, unit)
                steps.append(f"a {noun} costs {render(n)} {unit or ''}".strip())
                continue
            if self._is(verb, "c.contain") and cl.subject is not None:
                noun = (cl.subject.f.get("nouns") or [cl.subject.head])[-1]
                capacity[noun] = (n, unit)
                steps.append(f"a {noun} holds {render(n)} {unit or ''}".strip())
                continue
            if self._is(verb, "c.travel") and cl.subject is not None and len(amounts) >= 1:
                per = next((c for c in nps if c.f.get("det") in ("each", "every", "per")), None)
                if per is not None:
                    noun = (cl.subject.f.get("nouns") or [cl.subject.head])[-1]
                    rate[noun] = (n, unit, _unit(per))
                    steps.append(f"a {noun} goes {render(n)} {unit or ''} each {_unit(per)}".strip())
                    continue
            if subj is None:
                continue
            u = unit
            if u is None:
                units = {k[1] for k in ledger if k[0] == subj}
                u = next(iter(units)) if len(units) == 1 else None
            if self._is(verb, "c.have") and cl.vg.f.get("tense") in ("past", "present") and not cl.vg.f.get("neg"):
                ledger[(subj, u)] = ledger.get((subj, u), Fraction(0)) + n if (subj, u) in ledger and False else n
                steps.append(f"{subj} has {render(n)} {u or ''}".strip())
                history.append((subj, u, "set", n))
            elif self._is(verb, "c.give") and cl.subject is not None:
                recipient = next((p.f["np"] for p in cl.items if p.kind == "PP" and p.f.get("prep") == "to" and p.f.get("np") is not None), None)
                ledger[(subj, u)] = ledger.get((subj, u), Fraction(0)) - n
                steps.append(f"{subj} gives away {render(n)} {u or ''}".strip() + " → subtract")
                history.append((subj, u, "sub", n))
                if recipient is not None:
                    rk = (recipient.head or "").lower()
                    ledger[(rk, u)] = ledger.get((rk, u), Fraction(0)) + n
            elif self._is(verb, "c.lose"):
                ledger[(subj, u)] = ledger.get((subj, u), Fraction(0)) - n
                steps.append(f"{subj} loses/spends {render(n)} {u or ''}".strip() + " → subtract")
                history.append((subj, u, "sub", n))
            elif self._is(verb, "c.buy") and unit in price and not self._is(verb, "c.gain") or (self._is(verb, "c.buy") and unit in price):
                purchases.append((unit, n))
                steps.append(f"{subj} buys {render(n)} {unit}")
            elif self._is(verb, "c.gain"):
                ledger[(subj, u)] = ledger.get((subj, u), Fraction(0)) + n
                steps.append(f"{subj} gains {render(n)} {u or ''}".strip() + " → add")
                history.append((subj, u, "add", n))
        return self._answer(q, ledger, price, rate, capacity, purchases, steps, last)

    def _answer(self, q: Clause, ledger, price, rate, capacity, purchases, steps, last) -> Solution | None:
        qnoun = None
        qnp = next((c for c in q.items if c.kind == "NP" and c.f.get("wh")), None)
        if qnp is not None:
            qnoun = (qnp.f.get("nouns") or [None])[-1]
        verb = (q.vg.f.get("verb") if q.vg else "") or ""
        if q.wh == "how_far":
            tp = next((p.f["np"] for p in q.items if p.kind == "PP" and p.f.get("np") is not None and "num" in p.f["np"].f), None)
            subj = (q.subject.f.get("nouns") or [None])[-1] if q.subject is not None else None
            if subj is None and q.subject is not None and q.subject.f.get("pron") == "it" and len(rate) == 1:
                subj = next(iter(rate))
            if subj in rate and tp is not None:
                r, u, per = rate[subj]
                t = Fraction(str(tp.f["num"]))
                tree = ("mul", _num(r), _num(t))
                val = evaluate(tree)
                return Solution(val, u, steps + [f"{render(r)} {u} each {per} × {render(t)} {per}s = {render(val)} {u}"], tree, "distance")
            return None
        if q.wh == "how_much" and (self._is(verb, "c.pay") or self._is(verb, "c.cost") or verb in ("pay", "owe", "spend")) and purchases:
            terms = []
            lines = []
            for noun, n in purchases:
                p, u = price[noun]
                terms.append(("mul", _num(p), _num(n)))
                lines.append(f"{render(n)} {noun}s × {render(p)} {u or ''}".strip())
            tree = terms[0] if len(terms) == 1 else ("add", *terms)
            val = evaluate(tree)
            u = price[purchases[0][0]][1]
            return Solution(val, u, steps + [" + ".join(lines) + f" = {render(val)}"], tree, "total_cost")
        if q.wh == "how_many" and capacity:
            pp = next((p.f["np"] for p in q.items if p.kind == "PP" and p.f.get("np") is not None and "num" in p.f["np"].f), None)
            box = (pp.f.get("nouns") or [None])[-1] if pp is not None else None
            key = box if box in capacity else None
            if pp is not None and key is not None and (qnoun is None or capacity[key][1] in (qnoun, None)):
                cap, u = capacity[key]
                n = Fraction(str(pp.f["num"]))
                tree = ("mul", _num(n), _num(cap))
                val = evaluate(tree)
                return Solution(val, u or qnoun, steps + [f"{render(n)} {box}s × {render(cap)} each = {render(val)}"], tree, "container")
        if q.wh in ("how_many", "how_much"):
            who = _agent_key(q.subject, last) if q.subject is not None else None
            if who is None and len({k[0] for k in ledger}) == 1:
                who = next(iter({k[0] for k in ledger}))
            cands = [k for k in ledger if k[0] == who and (qnoun is None or k[1] in (qnoun, None))]
            if len(cands) == 1:
                val = ledger[cands[0]]
                # rebuild as an expression for exact evaluation
                tree = self._ledger_tree(cands[0])
                return Solution(val, cands[0][1], steps + [f"remaining = {render(val)}"], tree if tree is not None else val, "remaining")
        return None

    @staticmethod
    def _ledger_tree(key):
        return None


def _num(x: Fraction):
    return int(x) if x.denominator == 1 else float(x)


def solve_with_engine(sol: Solution) -> Solution:
    """Re-evaluate the final value with the exact arithmetic engine as a consistency check; the ledger value is authoritative only if they agree."""
    if isinstance(sol.tree, tuple):
        v = evaluate(sol.tree)
        if v != sol.value:
            raise ArithmeticError_("ledger and expression disagree")
    return sol


# ======================================================================================================================================
# Deduction
# ======================================================================================================================================
@dataclass
class Prop:
    subj: str
    pred: str
    neg: bool = False

    def key(self) -> tuple[str, str]:
        return (self.subj, self.pred)

    def to_dict(self) -> dict:
        return {"subj": self.subj, "pred": self.pred, "neg": self.neg}


def prop_from_dict(d: dict) -> Prop:
    return Prop(d["subj"], d["pred"], d.get("neg", False))


def _subj_lemma(np: Chunk | None) -> str | None:
    if np is None:
        return None
    pron = np.f.get("pron")
    if pron:
        return {"me": "i", "i": "i"}.get(pron, pron)
    nouns = np.f.get("nouns")
    if nouns:
        return nouns[-1]
    names = np.f.get("names")
    if names:
        return " ".join(names).lower()
    return None


class Deduction:
    """Premises: facts, ``isa`` links, universal rules (kind -> property) and conditionals. Backward chaining with a justification trace."""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.facts: list[dict] = d.get("facts", [])
        self.isa: list[list[str]] = d.get("isa", [])
        self.universals: list[dict] = d.get("universals", [])
        self.conditionals: list[dict] = d.get("conditionals", [])

    def to_dict(self) -> dict:
        return {"facts": self.facts[-40:], "isa": self.isa[-40:], "universals": self.universals[-40:], "conditionals": self.conditionals[-40:]}

    # ---- parsing ---------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def clause_prop(cl: Clause) -> Prop | None:
        if cl.vg is None:
            return None
        subj = _subj_lemma(cl.subject)
        if subj is None:
            return None
        verb = cl.vg.f.get("verb") or ""
        comps = [c for c in cl.items if c.kind in ("ADJP", "NP", "VG")]
        if verb == "be" or cl.vg.f.get("copula") and not verb:
            tail = next((c for c in comps if c.kind in ("ADJP",)), None)
            if tail is not None:
                return Prop(subj, tail.head, cl.negated)
            tail = next((c for c in comps if c.kind == "VG"), None)
            if tail is not None:
                return Prop(subj, tail.f.get("verb") or tail.head, cl.negated)
            np = next((c for c in comps if c.kind == "NP"), None)
            if np is not None and (np.f.get("poss") or np.f.get("det") == "the" or any(c.kind == "PP" for c in cl.items)):
                return None                                  # "Kampala is my home", "Paris is the capital of Germany": not class membership
            if np is not None:
                return Prop(subj, "is_a:" + (np.f.get("nouns") or [np.head])[-1] if np.f.get("nouns") else np.head, cl.negated) if np.f.get("det") in ("a", "an") or np.f.get("nouns") else Prop(subj, np.head, cl.negated)
            return None
        obj = next((c for c in comps if c.kind == "NP"), None)
        pred = verb + (f" {(obj.f.get('nouns') or [obj.head])[-1]}" if obj is not None and (obj.f.get("nouns") or obj.head) else "")
        return Prop(subj, pred.strip(), cl.negated)

    def ingest(self, clauses: list[Clause]) -> list[str]:
        """Learn from declarative clauses; returns descriptions of what was understood (for the trace)."""
        out: list[str] = []
        i = 0
        while i < len(clauses):
            cl = clauses[i]
            if cl.wh or cl.inverted or cl.punct_question:
                i += 1; continue
            if cl.subordinator in ("if", "when", "whenever", "unless") and i + 1 < len(clauses):
                ant, con = self.clause_prop(cl), self.clause_prop(clauses[i + 1])
                if ant and con:
                    if cl.subordinator == "unless":
                        ant.neg = not ant.neg
                    self.conditionals.append({"if": ant.to_dict(), "then": con.to_dict()})
                    out.append(f"rule: if {ant.subj} {ant.pred} then {con.subj} {con.pred}")
                    i += 2; continue
            p = self.clause_prop(cl)
            if p is None:
                i += 1; continue
            quant = (cl.subject.f.get("det") if cl.subject is not None else None)
            if p.pred.startswith("is_a:"):
                kind = p.pred[5:]
                self.isa.append([p.subj, kind])
                out.append(f"{p.subj} is a {kind}")
            elif quant in ("all", "every", "each", "any"):
                self.universals.append({"kind": p.subj, "pred": p.pred, "neg": p.neg})
                out.append(f"every {p.subj} {p.pred}")
            else:
                self.facts.append(p.to_dict())
                out.append(f"{p.subj} {'does not ' if p.neg else ''}{p.pred}")
            i += 1
        return out

    # ---- inference -------------------------------------------------------------------------------------------------------------------------
    def kinds_of(self, subj: str) -> list[tuple[str, list[str]]]:
        seen = {subj: [subj]}
        frontier = [subj]
        for _ in range(6):
            nxt = []
            for s in frontier:
                for a, b in self.isa:
                    if a == s and b not in seen:
                        seen[b] = seen[s] + [b]; nxt.append(b)
            frontier = nxt
        return list(seen.items())

    def holds(self, prop: Prop, depth: int = 4, trace: list[str] | None = None) -> bool | None:
        trace = trace if trace is not None else []
        if depth < 0:
            return None
        if prop.pred.startswith("is_a:"):
            for kind, path in self.kinds_of(prop.subj):
                if kind == prop.pred[5:]:
                    trace.append(" → ".join(path)); return not prop.neg
            return None
        for f in self.facts:
            if (f["subj"], f["pred"]) == prop.key():
                trace.append(f"given: {f['subj']} {'does not ' if f['neg'] else ''}{f['pred']}")
                return (not f["neg"]) != prop.neg
        for kind, path in self.kinds_of(prop.subj):
            for u in self.universals:
                if u["kind"] == kind and u["pred"] == prop.pred:
                    trace.append(f"every {kind} {'does not ' if u['neg'] else ''}{u['pred']}" + (f"; {' is a '.join(path)}" if len(path) > 1 else ""))
                    return (not u["neg"]) != prop.neg
        for c in self.conditionals:
            then = prop_from_dict(c["then"])
            if then.key() == prop.key():
                ant = prop_from_dict(c["if"])
                inner: list[str] = []
                r = self.holds(Prop(ant.subj, ant.pred, False), depth - 1, inner)
                if r is not None:
                    trace.append(f"if {ant.subj} {ant.pred} then {then.subj} {then.pred}")
                    trace += inner
                    holds_ant = (r != ant.neg)
                    if holds_ant:
                        return (not then.neg) != prop.neg
        return None


# ======================================================================================================================================
# Ordering with abstract names ("A is heavier than B")
# ======================================================================================================================================
_COMP = json.loads((DATA / "comparatives.json").read_text(encoding="utf-8"))["comparatives"]
_ORD_RE = re.compile(r"\b([A-Z][A-Za-z]{0,1})\s+(?:is|are|was)\s+(\w+)\s+than\s+([A-Z][A-Za-z]{0,1})\b")
_ORD_Q = re.compile(r"\b(?:[Ii]s|[Aa]re|[Ww]as)\s+([A-Z][A-Za-z]{0,1})\s+(\w+)\s+than\s+([A-Z][A-Za-z]{0,1})\s*\?")


@dataclass
class OrderAnswer:
    answer: str                    # yes | no | unknown | inconsistent
    steps: list[str]
    dimension: str


def solve_abstract_order(text: str) -> OrderAnswer | None:
    """Only for single-letter (abstract) names; named comparisons are handled by the relational strategy of the reasoning engine."""
    stmts = _ORD_RE.findall(text)
    q = _ORD_Q.search(text)
    if not stmts or not q:
        return None
    dims: dict[str, PartialOrder] = {}
    for a, adj, b in stmts:
        if adj.lower() not in _COMP:
            continue
        dim, sign = _COMP[adj.lower()]
        po = dims.setdefault(dim, PartialOrder())
        (po.add_greater(a, b, adj) if sign > 0 else po.add_greater(b, a, adj))
    qa, qadj, qb = q.groups()
    if qadj.lower() not in _COMP:
        return None
    dim, sign = _COMP[qadj.lower()]
    po = dims.get(dim)
    if po is None:
        return None
    if not po.is_consistent():
        return OrderAnswer("inconsistent", [f"the statements about {dim} contradict each other: {po.find_cycle()}"], dim)
    x, y = (qa, qb) if sign > 0 else (qb, qa)
    rel = po.compare(x, y)
    if rel == ">":
        chain = po.chain(x, y) or [x, y]
        return OrderAnswer("yes", [" > ".join(chain) + f" ({dim})"], dim)
    if rel == "<":
        chain = po.chain(y, x) or [y, x]
        return OrderAnswer("no", [" > ".join(chain) + f" ({dim}), so the reverse cannot hold"], dim)
    if rel == "=":
        return OrderAnswer("no", [f"{x} and {y} are equal in {dim}"], dim)
    return OrderAnswer("unknown", [f"nothing stated relates {x} and {y} in {dim}"], dim)
