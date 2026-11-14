"""The meaning layer: language analysis -> semantic frames -> dialogue state -> reasoning/retrieval -> response plan -> realisation.

``MeaningLayer.handle`` is called by the orchestrator after the language engine. It returns ``None`` when it does not understand the turn with
enough structure (the established pipeline then runs unchanged), or an :class:`Outcome` that carries the reply and a complete inspection record
(tokens, chunks, frames, state before/after, retrieved knowledge with provenance, reasoning steps, plan, confidence).

Division of labour:
* personal facts about the speaker (name, residence, job, funds, preferences, possessions) are stored through the Knowledge Engine, so they carry
  source, verification status and revision history, and survive across conversations;
* facts about third parties and conversation objects ("my uncle Peter", "the laptop") live in the dialogue state with per-attribute provenance and
  are scoped to the conversation;
* statements attributed to someone else or hedged ("my teacher says…", "I think…") are claims with attribution and are never stored as fact;
* arithmetic word problems and deduction run in ``reason`` without touching storage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core.types import Scope
from ..engines.knowledge.terms import entity_term, literal_term, render_term, SELF_USER
from .chunker import Chunker, Clause
from .dialogue import DialogueState, kind_of_lemma
from .frames import FrameMatcher, Interp, load_frames
from .lexicon import ConceptGraph, default_graph
from .reason import Deduction, WordProblem, solve_abstract_order, solve_with_engine
from .planning import plan_from_clause
from .realize import ActRealizer, default_lm

WORLD_ATTRS = {"capital": "attr.capital", "currency": "attr.currency", "president": "attr.president", "population": "attr.population"}
CORRECTION_MARKERS = {"actually", "sorry", "correction", "rather", "instead"}
ASK_SLOT_FRAME = {"model": "maker", "use": "purpose", "name": "naming"}


@dataclass
class Outcome:
    text: str
    acts: list[dict]
    trace: dict
    confidence: float
    uncertainty: list[str] = field(default_factory=list)
    rewrite: str | None = None                 # canonical form of the question for the established pipeline
    stored: list[dict] = field(default_factory=list)
    dialogue: dict | None = None
    premises: dict | None = None


class MeaningLayer:
    def __init__(self, knowledge, graph: ConceptGraph | None = None):
        self.kb = knowledge
        self.graph = graph or default_graph()
        self.chunker = Chunker(self.graph)
        self.matcher = FrameMatcher(self.graph)
        self.wp = WordProblem(self.graph)
        self.frames = load_frames()["frames"]

    # ==================================================================================================================================
    def handle(self, scope: Scope, text: str, lr, dialogue: dict | None, premises: dict | None, *, conversation_id: str | None, seed: int | None = None,
               explain: bool = False, recent_out: list[str] | None = None) -> Outcome | None:
        state = DialogueState(dialogue)
        recent_out = list(recent_out or state.recent_out)
        before = state.snapshot()
        state.begin_turn()
        tokens = lr.tokens or []
        if not tokens:
            return None
        clauses = self.chunker.parse(tokens, question_mark=text.strip().endswith("?"))
        trace: dict[str, Any] = {"input": text, "tokens": [{"text": t["text"], "lemma": t.get("lemma"), "pos": t["pos"], "sentence": t.get("sentence", 0)} for t in tokens],
                                 "clauses": [c.to_dict() for c in clauses], "state_before": before}
        if not clauses:
            return None
        ded = Deduction(premises)
        acts: list[dict] = []
        stored: list[dict] = []
        uncertainty: list[str] = []
        reasoning: list[str] = []
        retrieved: list[dict] = []
        conf = 0.9

        # 1) canonical rewrite of attribute questions about the world ----------------------------------------------------------------------
        rw = self._world_question(clauses, text)
        if rw:
            trace.update(stage="rewrite", rewrite=rw, state_after=state.snapshot())
            return Outcome("", [], trace, 0.8, rewrite=rw, dialogue=state.to_dict(), premises=ded.to_dict())

        # 2) arithmetic word problems ------------------------------------------------------------------------------------------------------
        sol = None
        if any(c.wh in ("how_many", "how_much", "how_far") for c in clauses):
            try:
                sol = self.wp.solve(clauses)
                sol = solve_with_engine(sol) if sol else None
            except ArithmeticError:
                sol = None
        if sol:
            q = next(c for c in clauses if c.wh in ("how_many", "how_much", "how_far"))
            adv = "left" if re.search(r"\b(left|remain|remaining)\b", text.lower()) else "now"
            subject = ""
            if q.subject is not None:
                subject = (q.subject.head or "").lower() if not q.subject.f.get("pron") else ("you" if q.subject.f.get("pron") in ("i", "we") else "")
            acts.append({"type": "calc", "kind": sol.kind, "text_value": sol.text_value(), "unit": sol.unit, "subject": subject, "adv": adv, "steps": sol.steps, "explain": explain,
                         "value_n": float(sol.value)})
            reasoning = sol.steps + [f"exact evaluation: {sol.text_value()}"]
            trace["reasoning"] = {"engine": "word_problem→arithmetic", "steps": reasoning}
            return self._finish(text, trace, acts, state, ded, stored, uncertainty, 0.92, seed, recent_out, conversation_id)

        # 2b) task decomposition ("How do I prepare for an exam in three days?") ---------------------------------------------------------
        for cl in clauses:
            plan = plan_from_clause(cl)
            if plan:
                acts.append({"type": "plan", "goal": plan.goal, "object": plan.object, "days": plan.days, "steps": plan.steps})
                trace["reasoning"] = {"engine": "htn_decomposition", "steps": [f"{w}: {t}" for w, t in plan.steps], "method": plan.method}
                return self._finish(text, trace, acts, state, ded, stored, uncertainty, 0.8, seed, recent_out, conversation_id)

        # 3) abstract ordering ("A is heavier than B") --------------------------------------------------------------------------------------
        oa = solve_abstract_order(text)
        if oa:
            acts.append({"type": "deduce", "answer": oa.answer, "trace": oa.steps})
            trace["reasoning"] = {"engine": "partial_order", "steps": oa.steps}
            return self._finish(text, trace, acts, state, ded, stored, uncertainty, 0.9 if oa.answer != "unknown" else 0.6, seed, recent_out, conversation_id)

        # 4) deduction over premises (universal / conditional / isa) -----------------------------------------------------------------------
        interps, unmatched = self.matcher.interpret(clauses, state)
        rule_idx = {k for k, c in enumerate(clauses) if c.subordinator in ("if", "when", "whenever", "unless")}
        rule_idx |= {k + 1 for k in list(rule_idx) if k + 1 < len(clauses)} | {k for k, c in enumerate(clauses) if self._quantified(c)}
        interps = [i for i in interps if i.clause not in rule_idx]            # a conditional/universal is a rule, not an event to store
        matched_idx = {i.clause for i in interps}
        questions = [c for c in clauses if c.wh or c.inverted or c.punct_question]
        statements = [c for k, c in enumerate(clauses) if c not in questions and k not in matched_idx]
        had_rules = bool(ded.universals or ded.conditionals or ded.isa)
        rule_here = bool(rule_idx) or had_rules
        learned = ded.ingest([c for c in statements if self._deductive(c, ded) or rule_here])
        if learned and (any(c.subordinator in ("if", "when") for c in statements) or any(self._quantified(c) for c in statements) or any(r.endswith(("a " + r.split(" a ")[-1])) and " is a " in r for r in learned)):
            reasoning += learned
            for qc in questions:
                p = Deduction.clause_prop(qc)
                if p is None:
                    continue
                steps: list[str] = []
                res = ded.holds(p, trace=steps)
                reasoning += steps
                ans = "yes" if res is True else "no" if res is False else "unknown"
                acts.append({"type": "deduce", "answer": ans, "trace": steps})
                conf = 0.9 if res is not None else 0.5
                if res is None:
                    uncertainty.append("the premises do not settle the question")
            if acts:
                trace["reasoning"] = {"engine": "deduction", "steps": reasoning}
                return self._finish(text, trace, acts, state, ded, stored, uncertainty, conf, seed, recent_out, conversation_id)
            if learned:                                                     # premises only: acknowledge understanding
                acts.append({"type": "ack_rule", "learned": learned})
                trace["reasoning"] = {"engine": "deduction", "steps": learned}
                return self._finish(text, trace, acts, state, ded, stored, uncertainty, 0.85, seed, recent_out, conversation_id)
        elif questions and had_rules:
            for qc in questions:
                p = Deduction.clause_prop(qc)
                if p is None:
                    continue
                steps = []
                res = ded.holds(p, trace=steps)
                if res is not None:
                    acts.append({"type": "deduce", "answer": "yes" if res else "no", "trace": steps})
            if acts:
                trace["reasoning"] = {"engine": "deduction", "steps": steps}
                return self._finish(text, trace, acts, state, ded, stored, uncertainty, 0.88, seed, recent_out, conversation_id)

        # 5) frames ------------------------------------------------------------------------------------------------------------------------
        trace["frames"] = [i.to_dict() for i in interps]
        trace["unmatched"] = unmatched
        interps, unmatched, report_acts = self._reports(scope, clauses, interps, unmatched, state, conversation_id, stored, retrieved, uncertainty)
        trace["reports"] = [a.get("claim") for a in report_acts]
        correction = bool({t["text"].lower() for t in tokens[:3]} & CORRECTION_MARKERS) or any(c.kind == "ADVP" and c.head in CORRECTION_MARKERS for cl in clauses for c in cl.items)
        trace["correction_marker"] = correction
        handled = False
        for it in interps:
            if it.act == "report_head":
                continue
            handled = True
            got = self._apply(scope, it, state, conversation_id, text, correction, retrieved, stored)
            acts += got["acts"]
            uncertainty += got["uncertainty"]
            conf = min(conf, got["confidence"])
        if report_acts:
            handled = True
            acts += report_acts
        # 6) fragment answering a pending question -----------------------------------------------------------------------------------------
        if not handled:
            frag = self._fragment(scope, clauses, tokens, state, conversation_id, stored)
            if frag:
                handled = True
                acts += frag
        if not handled:
            clar = self._clarify(clauses, state)
            if clar:
                trace["retrieved"] = retrieved
                return self._finish(text, trace, [clar], state, ded, stored, ["the reference cannot be resolved from the conversation so far"], 0.4, seed, recent_out, conversation_id)
        if not handled or not acts:
            return None
        if unmatched and not all(self._is_filler(clauses[u["clause"]]) for u in unmatched):
            # part of the input was not understood: say what was understood and do not pretend about the rest
            uncertainty.append("part of the message was not understood: " + "; ".join(u["text"] for u in unmatched))
            acts.append({"type": "partial", "text": [u["text"] for u in unmatched]})
            conf = min(conf, 0.6)
        trace["retrieved"] = retrieved
        return self._finish(text, trace, acts, state, ded, stored, uncertainty, conf, seed, recent_out, conversation_id)

    # ==================================================================================================================================
    def _finish(self, text, trace, acts, state: DialogueState, ded: Deduction, stored, uncertainty, conf, seed, recent_out, conversation_id) -> Outcome:
        realizer = ActRealizer(seed=seed)
        out = realizer.render(acts, recent_out or [])
        state.recent_out = (state.recent_out + [x.strip() for x in re.split(r"(?<=[.?!])\s+", out) if x.strip()])[-8:]
        state.log(acts=[a["type"] for a in acts], frames=[a.get("frame") for a in acts if a.get("frame")])
        trace.update(plan=[{k: v for k, v in a.items() if k not in ("steps",)} for a in acts], realisation=realizer.choices, response=out,
                     state_after=state.snapshot(), confidence={"overall": round(conf, 3), "uncertainty": uncertainty})
        return Outcome(out, acts, trace, conf, uncertainty, stored=stored, dialogue=state.to_dict(), premises=ded.to_dict())

    @staticmethod
    def _is_filler(cl: Clause) -> bool:
        return not cl.items and cl.vg is None or cl.text.lower().strip(" .!") in ("nice", "ok", "okay", "sure", "thanks", "great", "cool")

    def _quantified(self, c: Clause) -> bool:
        return bool(c.subject is not None and c.subject.f.get("det") in ("all", "every", "each", "any"))

    def _deductive(self, c: Clause, ded: Deduction) -> bool:
        if c.vg is None or c.subject is None:
            return False
        if c.subordinator in ("if", "when", "unless"):
            return True
        if self._quantified(c):
            return True
        p = Deduction.clause_prop(c)
        if p is None:
            return False
        if p.pred.startswith("is_a:"):
            return True
        return bool(ded.conditionals or ded.universals)

    # ---- world attribute questions ----------------------------------------------------------------------------------------------------------
    def _world_question(self, clauses: list[Clause], text: str) -> str | None:
        """Paraphrased attribute questions ("Uganda's capital is which city?", "Name the capital of Uganda", "Where is the seat of government of Uganda?")
        -> canonical "What is the <attr> of <X>?" so the established retrieval path answers them. Triggered structurally: an attribute *concept*
        (not a word list: "seat" is in the capital cluster) plus a named owner, inside a question or an information-seeking imperative."""
        raw = text.strip()
        if not (raw.endswith("?") or re.match(r"(?i)^(tell|give|show|name|state|say|list)\b", raw)):
            return None
        attr_of = {"c.capital": "capital", "c.currency": "currency", "c.population": "population", "c.president": "president"}
        for cl in clauses:
            nps = ([cl.subject] if cl.subject is not None else []) + [c for c in cl.items if c.kind == "NP"] + [c.f["np"] for c in cl.items if c.kind == "PP" and c.f.get("np") is not None]
            for np in nps:
                heads = (np.f.get("nouns") or [])
                attr = None
                for h in heads:
                    for m in self.graph.concepts_of(h, "noun", strict=True):
                        if m.concept in attr_of:
                            attr = attr_of[m.concept]
                if not attr:
                    continue
                owner = np.f.get("possessor")
                if owner is None:
                    pps = [p.f["np"] for p in cl.items if p.kind == "PP" and p.f.get("prep") == "of" and p.f.get("np") is not None and p.f["np"].f.get("names")]
                    owner = " ".join(pps[-1].f["names"]) if pps else None
                if owner is None and cl.subject is not None and cl.subject is not np and (cl.subject.f.get("names") or []):
                    owner = " ".join(cl.subject.f["names"])
                if not owner or owner.lower() in ("you", "me", "i"):
                    continue
                canonical = f"What is the {attr} of {owner}?"
                if canonical.lower().rstrip("?") == raw.lower().rstrip("?"):
                    return None
                return canonical
        return None

    # ---- reported speech --------------------------------------------------------------------------------------------------------------------
    def _world_claim(self, cl: Clause) -> tuple[str, str, str] | None:
        """"the capital of Canada is Toronto" / "Canada's capital is Toronto" -> (attribute, owner, value)."""
        if cl.vg is None or not (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be") or cl.subject is None:
            return None
        s = cl.subject
        heads = s.f.get("nouns") or []
        attr = next((a for a in WORLD_ATTRS if a in heads), None)
        if not attr:
            return None
        owner = s.f.get("possessor") or next((p.f["np"].head for p in cl.items if p.kind == "PP" and p.f.get("prep") == "of" and p.f.get("np") is not None), None)
        comp = next((c for c in cl.items if c.kind == "NP" and c.f.get("names")), None)
        if not owner or comp is None:
            return None
        return attr, owner, " ".join(comp.f["names"])

    def _reports(self, scope, clauses: list[Clause], interps: list[Interp], unmatched: list[dict], state, cid, stored, retrieved, unc) -> tuple[list[Interp], list[dict], list[dict]]:
        """"<source> says/thinks that <clause>": the embedded content is a *claim with attribution*. It is validated against what is known, kept with
        its source and a hedge, and never presented as fact."""
        acts: list[dict] = []
        heads = {i.clause: i for i in interps if i.act == "report_head"}
        consumed: set[int] = set()
        for k, head in heads.items():
            comp_idx = k + 1
            if comp_idx >= len(clauses):
                continue
            comp = clauses[comp_idx]
            src_ref = head.roles["source"]
            verb = head.extra.get("verb") or "say"
            subj = clauses[k].subject
            you = subj is not None and subj.f.get("pron") in ("i", "we")
            src_label = "you" if you else (re.sub(r"(?i)^my\b", "your", subj.text) if subj is not None else "someone").lower()
            wc = self._world_claim(comp)
            if wc:
                attr, owner, value = wc
                pred = WORLD_ATTRS[attr]
                okey = entity_term(owner)["key"]
                known = [f for f in self.kb.query(scope, pred, {"owner": okey}, established_only=True, include_self=True)]
                known_val = (known[0].args.get("value") or {}).get("label") if known else None
                res = self.kb.assert_fact(scope, pred, {"owner": entity_term(owner), "value": entity_term(value)}, confidence=0.5, source_type="user_statement", conversation_id=cid,
                                          qualifiers={"attributed_to": src_label, "attitude": verb})
                stored.append({"fact": res.fact.to_dict() if res.fact else None, "status": res.status, "verification": res.verification})
                if known_val and known_val.lower() != value.lower():
                    status = "conflict"
                elif known_val:
                    status = "match"
                else:
                    status = "unverified"
                retrieved.append({"source": "knowledge", "established": known_val, "claim_status": res.status, "verification": res.verification})
                if status != "match":
                    unc.append(f"claim by {src_label} is {res.verification or 'unverified'}")
                acts.append({"type": "report", "source": src_label, "claim": f"the {attr} of {owner} is {value}", "verb": verb if verb in ("think", "believe", "say") else "say",
                             "status": status, "known": known_val, "hedge": verb in ("think", "believe", "suppose", "reckon", "guess")})
            else:
                inner = [i for i in interps if i.clause == comp_idx]
                if not inner and not wc:
                    continue
                acts.append({"type": "report", "source": src_label, "claim": comp.text.lower(), "verb": verb if verb in ("think", "believe", "say") else "say", "status": "unverified", "known": None,
                             "hedge": verb in ("think", "believe", "suppose", "reckon", "guess")})
                consumed.add(comp_idx)
                unc.append("reported statement kept as an attributed claim")
            consumed.add(comp_idx)
        keep = [i for i in interps if i.act != "report_head" and i.clause not in consumed]
        return keep, [u for u in unmatched if u["clause"] not in consumed and u["clause"] not in heads], acts

    # ---- applying a frame interpretation ----------------------------------------------------------------------------------------------------
    def _ref_label(self, ref: dict, state: DialogueState) -> dict:
        if ref.get("t") == "self":
            return {"kind": "self"}
        if ref.get("t") == "entity":
            e = state.entities[ref["id"]]
            return {"kind": "entity", "label": e.get("label"), "gender": e.get("gender"), "person": e.get("person"), "pron_ok": ref.get("how") == "pronoun", "id": ref["id"],
                    "role": e.get("role"), "owner": e.get("owner")}
        if ref.get("t") == "new":
            return {"kind": "entity", "label": ref.get("label"), "gender": ref.get("gender"), "person": ref.get("person"), "pron_ok": False}
        return {"kind": "entity", "label": ref.get("label") or "it", "pron_ok": True}

    def _materialise(self, ref: dict, state: DialogueState) -> dict:
        """Create the entity described by a ``new`` reference (assertions only) and return an ``entity`` reference."""
        if ref.get("t") != "new":
            return ref
        if ref.get("unknown_type"):
            ref = {**ref, "kind": "named"}
        owner = ref.get("owner")
        label = ref["label"]
        if ref.get("role") and ref.get("names"):
            label = " ".join(ref["names"])
        eid = state.add_entity(ref.get("kind", "thing"), label, concept=ref.get("concept"), role=ref.get("role"), owner=owner, gender=ref.get("gender"),
                               names=ref.get("names"), adjs=ref.get("adjs"), person=bool(ref.get("person")))
        return {"t": "entity", "id": eid, "how": "introduced", "conf": 1.0}

    def _apply(self, scope: Scope, it: Interp, state: DialogueState, cid: str | None, text: str, correction: bool, retrieved: list[dict], stored: list[dict]) -> dict:
        spec = self.frames[it.frame] if it.frame in self.frames else None
        acts: list[dict] = []
        unc: list[str] = []
        conf = it.confidence
        roles = it.roles
        # unresolved / ambiguous references -> clarification, never a guess
        for name, r in list(roles.items()):
            if r.get("t") == "unresolved":
                cands = [state.entities[c].get("label") for c in state.entities if state.entities[c].get("salience", 0) > 0.2][:3]
                return {"acts": [{"type": "clarify", "options": [], "surface": r.get("pron") or "it"}], "uncertainty": [f"could not resolve '{r.get('pron')}'"], "confidence": 0.3}
            if r.get("t") == "entity" and (r.get("conf") or 1) < 0.6:
                opts = [state.entities[c].get("label") for c in r.get("cands", [])[:3]]
                return {"acts": [{"type": "clarify", "options": opts, "surface": r.get("pron") or "it"}], "uncertainty": ["ambiguous reference"], "confidence": 0.4}
        agent_ref = roles.get(spec["owner"] if spec else "agent") or roles.get("agent")
        if it.frame == "funds":
            return self._funds(scope, it, state, cid, retrieved, stored)
        if it.act == "assert":
            return self._assert(scope, it, spec, state, cid, correction, retrieved, stored)
        return self._query(scope, it, spec, state, cid, retrieved)

    def _clarify(self, clauses: list[Clause], state: DialogueState) -> dict | None:
        """A pronoun subject (he/she, or "it" in a question/predication) that no active entity can satisfy: ask instead of guessing."""
        for cl in clauses:
            s = cl.subject
            if s is None or cl.vg is None:
                continue
            pron = s.f.get("pron")
            if pron in ("he", "she", "it", "they") and (pron != "it" or cl.inverted or cl.punct_question or any(c.kind == "ADJP" for c in cl.items)):
                eid, cands, conf = state.resolve_pronoun(pron)
                if eid is None or conf < 0.6:
                    return {"type": "clarify", "options": [state.entities[c].get("label") for c in cands[:3]], "surface": pron}
        return None

    # ---- helpers for storage --------------------------------------------------------------------------------------------------------------
    def _term(self, role_value: dict, role_name: str) -> dict:
        v = role_value.get("value")
        if role_name == "place":
            return entity_term(str(v), "class.place")
        if role_name in ("thing", "maker"):
            return entity_term(str(v))
        return literal_term(str(v))

    def _owner_term(self, ref: dict, state: DialogueState) -> dict | None:
        if ref.get("t") == "self":
            return {"t": "self", "key": SELF_USER, "label": "you"}
        return None

    def _kb_value(self, scope: Scope, pred: str, owner_term: dict, conversation_id: str | None) -> tuple[Any, list]:
        facts = [f for f in self.kb.query(scope, pred, {"owner": owner_term["key"]}, conversation_id=conversation_id, include_self=False) if f.status in ("active", "disputed")]
        facts.sort(key=lambda f: f.created_at or "", reverse=True)
        return (facts[0] if facts else None), facts

    def _assert(self, scope, it: Interp, spec: dict, state: DialogueState, cid, correction, retrieved, stored) -> dict:
        roles = it.roles
        agent = roles.get(spec["owner"])
        value_role = spec["value"]
        acts: list[dict] = []
        unc: list[str] = []
        verb = it.extra.get("verb") or None
        if it.frame == "acquisition":
            return self._acquire(scope, it, spec, state, cid, retrieved, stored)
        if it.frame in ("purpose", "maker"):
            ent = self._materialise(roles["thing"], state)
            eid = ent["id"]
            val = roles[value_role]["value"] if value_role in roles else None
            if val is None:
                return {"acts": [], "uncertainty": [], "confidence": 0.3}
            state.set_attr(eid, "use" if it.frame == "purpose" else "maker", val, evidence=text_snip(it))
            self._persist_entity_attr(scope, state, eid, "attr.use" if it.frame == "purpose" else "attr.maker", val, cid, stored)
            state.touch(eid)
            acts.append({"type": "ack", "frame": it.frame, "agent": {"kind": "self"}, "value": val, "thing_np": f"your {state.entities[eid]['label'].split()[-1]}", "novelty": "new", "tense": it.tense})
            return {"acts": acts, "uncertainty": unc, "confidence": it.confidence}
        if agent is None:
            return {"acts": [], "uncertainty": [], "confidence": 0.3}
        value = roles[value_role]
        val_term = None
        if agent.get("t") == "self":
            if it.frame in ("preference", "consumption"):
                val_term = self._term({"value": value.get("value")}, "thing") if value.get("t") == "literal" else None
                if value.get("t") == "new":
                    val_term = entity_term(value.get("head") or value["label"].split()[-1])
                    value = {"t": "literal", "value": value.get("head") or value["label"].split()[-1]}
            else:
                val_term = self._term(value, value_role)
            prior, _ = self._kb_value(scope, spec["predicate"], {"key": SELF_USER}, cid) if spec.get("functional") else (None, [])
            novelty = "new"
            old = None
            if prior is not None and prior.key_of("value") == val_term["key"]:
                novelty = "repeat"
            elif prior is not None:
                novelty = "revised"
                old = (prior.args.get("value") or {}).get("label") or (prior.args.get("value") or {}).get("value")
            res = self.kb.assert_fact(scope, spec["predicate"], {"owner": {"t": "self", "key": SELF_USER, "label": "you"}, "value": val_term}, polarity=it.polarity,
                                      confidence=min(0.95, it.confidence), source_type="user_statement", conversation_id=cid, correction=(novelty == "revised"),
                                      qualifiers={"time": it.time} if it.time else None)
            stored.append({"fact": res.fact.to_dict() if res.fact else None, "status": res.status, "verification": res.verification})
            if res.status == "disputed":
                unc.append("stored as a disputed claim")
            acts.append({"type": "ack", "frame": it.frame, "agent": {"kind": "self"}, "value": value.get("value"), "polarity": it.polarity, "novelty": novelty, "old": old,
                         "tense": it.tense, "time": it.time, "verb_lemma": self._user_verb(it), "valence": 0})
            if novelty == "revised":
                state.corrections.append({"frame": it.frame, "old": old, "new": value.get("value"), "turn": state.turn})
            return {"acts": acts, "uncertainty": unc, "confidence": it.confidence}
        # third party / conversation entity
        ent = self._materialise(agent, state)
        eid = ent["id"]
        label = value.get("value") if value.get("t") == "literal" else None
        slot = {"residence": "residence", "occupation": "occupation", "naming": "name"}.get(it.frame, it.frame)
        if label is None:
            return {"acts": [], "uncertainty": [], "confidence": 0.3}
        prior = state.entities[eid]["attrs"].get(slot)
        novelty = "new" if prior is None else ("repeat" if prior["value"] == label else "revised")
        state.set_attr(eid, slot, label, evidence=text_snip(it))
        if slot == "name":
            state.entities[eid]["names"] = [label]
        state.touch(eid)
        ref = self._ref_label({"t": "entity", "id": eid, "how": agent.get("how")}, state)
        if agent.get("how") in ("introduced", "name"):
            ref["pron_ok"] = False
        ref["label"] = self._full_label(state.entities[eid])
        acts.append({"type": "ack", "frame": it.frame, "agent": ref, "value": label, "polarity": it.polarity, "novelty": novelty, "old": prior["value"] if prior and novelty == "revised" else None,
                     "tense": it.tense})
        # a freshly named pet/person: nothing to ask; an artifact with open slots: ask next
        nxt = state.next_open_slot(eid)
        if nxt and state.entities[eid]["kind"] == "artifact":
            acts += self._ask_next(state, eid)
        return {"acts": acts, "uncertainty": unc, "confidence": it.confidence}

    @staticmethod
    def _full_label(e: dict) -> str:
        if e.get("role") and e.get("owner") == "self":
            return f"your {e['role']} {e['label']}"
        return e.get("label") or "it"

    def _user_verb(self, it: Interp) -> str | None:
        return it.extra.get("verb")

    def _persist_entity_attr(self, scope, state: DialogueState, eid: str, pred: str, val: str, cid, stored: list) -> None:
        e = state.entities[eid]
        if e.get("owner") != "self" or e["kind"] != "artifact":
            return
        key = f"{SELF_USER}/{(e.get('head') or e['label'].split()[-1]).lower()}"
        owner = {"t": "entity", "key": key, "label": f"your {e['label'].split()[-1]}"}
        try:
            res = self.kb.assert_fact(scope, pred, {"owner": owner, "value": literal_term(val)}, confidence=0.9, source_type="user_statement", conversation_id=cid, correction=True)
            stored.append({"fact": res.fact.to_dict() if res.fact else None, "status": res.status})
        except Exception as ex:                                                  # storage failure must not break the conversation
            stored.append({"error": type(ex).__name__})

    def _acquire(self, scope, it: Interp, spec, state: DialogueState, cid, retrieved, stored) -> dict:
        roles = it.roles
        thing = roles.get("thing")
        if not thing or thing.get("t") not in ("new", "entity"):
            return {"acts": [], "uncertainty": [], "confidence": 0.3}
        if thing.get("t") == "new":
            thing = {**thing, "owner": "self"}
        ent = self._materialise(thing, state)
        eid = ent["id"]
        e = state.entities[eid]
        e["head"] = thing.get("head") if thing.get("head") else e["label"].split()[-1]
        if it.time:
            state.set_attr(eid, "acquired", it.time)
        key_label = e["head"]
        res = self.kb.assert_fact(scope, "rel.owns", {"owner": {"t": "self", "key": SELF_USER, "label": "you"}, "value": {"t": "entity", "key": f"{SELF_USER}/{key_label.lower()}", "label": f"your {key_label}"}},
                                  confidence=min(0.95, it.confidence), source_type="user_statement", conversation_id=cid)
        stored.append({"fact": res.fact.to_dict() if res.fact else None, "status": res.status})
        acts = [{"type": "ack", "frame": "acquisition", "agent": {"kind": "self"}, "value": e["label"], "novelty": "new", "tense": it.tense, "time": it.time, "verb_lemma": self._user_verb(it) or "buy"}]
        acts += self._ask_next(state, eid, echo=self._user_verb(it))
        return {"acts": acts, "uncertainty": [], "confidence": it.confidence}

    def _ask_next(self, state: DialogueState, eid: str, echo: str | None = None) -> list[dict]:
        nxt = state.next_open_slot(eid)
        if not nxt:
            return []
        slot, role = nxt
        state.ask(eid, slot, role)
        return [{"type": "ask_slot", "slot": slot, "thing": "it", "entity": eid, "echo_verb": echo}]

    # ---- queries ---------------------------------------------------------------------------------------------------------------------------
    def _lookup(self, scope, it: Interp, spec, state: DialogueState, cid, retrieved) -> tuple[Any, dict | None, dict]:
        """(value, evidence, agent_label) for the asked role."""
        roles = it.roles
        slot_role = it.ask
        if it.frame in ("purpose", "maker"):
            thing = roles.get("thing")
            eid = thing.get("id") if thing and thing.get("t") == "entity" else None
            if eid is None and thing and thing.get("t") == "new" and thing.get("head"):
                eid = state.find_by_kind(self.graph, thing["head"], "self")
            slot = "use" if it.frame == "purpose" else "maker"
            if eid is not None:
                a = state.entities[eid]["attrs"].get(slot)
                if a is None and slot == "maker":
                    m = state.entities[eid]["attrs"].get("model")
                    if m:
                        first = m["value"].split()[0]
                        retrieved.append({"source": "dialogue", "entity": eid, "slot": "model", "derived": "maker=first word of model", "confidence": 0.6})
                        return first, {"inferred": True}, {"kind": "self", "thing_np": f"your {state.entities[eid]['head']}"}
                if a is not None:
                    retrieved.append({"source": "dialogue", "entity": eid, "slot": slot, "turn": a["turn"], "provenance": a["source"], "confidence": a["confidence"]})
                    return a["value"], {"inferred": False}, {"kind": "self", "thing_np": f"your {state.entities[eid]['head']}"}
                return None, None, {"kind": "self", "thing_np": f"your {state.entities[eid].get('head', 'thing')}", "eid": eid}
            # fresh conversation: personal knowledge about the object persists
            head = (thing or {}).get("head") or (thing or {}).get("value")
            if head:
                owner_key = f"{SELF_USER}/{head.lower()}"
                facts = [f for f in self.kb.query(scope, "attr.use" if it.frame == "purpose" else "attr.maker", {"owner": owner_key}, include_self=False) if f.status == "active"]
                if facts:
                    retrieved.append({"source": "knowledge", "fact": facts[0].id, "provenance": facts[0].provenance, "verification": facts[0].verification})
                    return facts[0].args["value"].get("value"), {"inferred": False}, {"kind": "self", "thing_np": f"your {head}"}
            return None, None, {"kind": "self", "thing_np": "it"}
        agent = roles.get("agent")
        if agent is None:
            return None, None, {"kind": "self"}
        if agent.get("t") == "self":
            f, allf = self._kb_value(scope, spec["predicate"], {"key": SELF_USER}, cid)
            if f is not None:
                retrieved.append({"source": "knowledge", "fact": f.id, "provenance": f.provenance, "verification": f.verification, "claim_type": f.claim_type, "status": f.status})
                v = f.args.get("value", {})
                return (v.get("label") or v.get("value")), {"fact": f.id, "disputed": f.status == "disputed"}, {"kind": "self"}
            return None, None, {"kind": "self"}
        eid = agent.get("id")
        if eid is None and agent.get("t") == "new":
            eid = state.find_by_name(agent.get("label", "")) if agent.get("names") else None
            if eid is None and agent.get("role"):
                eid = state.find_by_role(agent["role"], "self")
        if eid is None:
            return None, None, {"kind": "entity", "label": agent.get("label") or "that person"}
        slot = {"residence": "residence", "occupation": "occupation", "naming": "name"}.get(it.frame, it.frame)
        a = state.entities[eid]["attrs"].get(slot)
        ref = self._ref_label({"t": "entity", "id": eid, "how": agent.get("how")}, state)
        ref["label"] = self._full_label(state.entities[eid]) if not ref["pron_ok"] else ref["label"]
        state.touch(eid)
        if a is not None:
            retrieved.append({"source": "dialogue", "entity": eid, "slot": slot, "turn": a["turn"], "provenance": a["source"], "confidence": a["confidence"]})
            return a["value"], {"inferred": False}, ref
        return None, None, ref

    def _query(self, scope, it: Interp, spec, state, cid, retrieved) -> dict:
        val, ev, ref = self._lookup(scope, it, spec, state, cid, retrieved)
        frame = it.frame
        if it.act == "ask":
            if val is None:
                ask_act = {"type": "unknown", "frame": frame, "agent": ref}
                if ref.get("eid") is not None and frame in ("purpose", "maker"):
                    return {"acts": [{"type": "unknown", "frame": frame, "agent": {"kind": "self"}, "thing_np": ref.get("thing_np")}], "uncertainty": ["no stored value"], "confidence": 0.5}
                return {"acts": [ask_act], "uncertainty": ["nothing stored for this attribute"], "confidence": 0.55}
            unc = []
            if ev and ev.get("disputed"):
                unc.append("the stored claim is disputed")
            act = {"type": "answer", "frame": frame, "agent": ref, "value": val, "source": "told", "polarity": "positive", "tense": "present", "thing_np": ref.get("thing_np"),
                   "inferred": bool(ev and ev.get("inferred")), "uncertain": bool(ev and ev.get("disputed"))}
            if ev and ev.get("inferred"):
                unc.append("derived from the first word of the model name, not stated")
            return {"acts": [act], "uncertainty": unc, "confidence": 0.9 if not unc else 0.7}
        # yes/no question
        want = it.roles.get(spec["value"])
        wterm = None
        if frame == "preference" and it.roles.get("agent", {}).get("t") == "self" and not it.roles.get("thing"):
            # "What do I like?": enumerate what the user has actually said (positive and negative are reported separately, nothing is inferred)
            likes, dislikes = [], []
            for f in self.kb.query(scope, spec["predicate"], {"owner": SELF_USER}, include_self=False, conversation_id=cid):
                if f.status not in ("active", "disputed"):
                    continue
                label = render_term(f.args.get("value", {}))
                (likes if f.polarity == "positive" else dislikes).append(label)
                retrieved.append({"source": "knowledge", "fact": f.id, "provenance": f.provenance, "verification": f.verification})
            if not likes and not dislikes:
                return {"acts": [{"type": "unknown", "frame": frame, "agent": {"kind": "self"}}], "uncertainty": ["nothing stored about this"], "confidence": 0.5}
            return {"acts": [{"type": "prefs", "likes": sorted(set(likes)), "dislikes": sorted(set(dislikes))}], "uncertainty": [], "confidence": 0.85}
        if frame in ("preference", "consumption") and it.roles.get("agent", {}).get("t") == "self":
            thing = it.roles.get("thing", {})
            noun = thing.get("head") or thing.get("value") or (thing.get("label") or "").split()[-1]
            facts = [f for f in self.kb.query(scope, spec["predicate"], {"owner": SELF_USER, "value": entity_term(noun)["key"]}, include_self=False, conversation_id=cid) if f.status in ("active", "disputed")]
            if frame == "preference":                                              # love/like are the same frame: a stated dislike answers "like" with no
                pass
            if not facts:
                return {"acts": [{"type": "unknown", "frame": frame, "agent": {"kind": "self"}}], "uncertainty": ["nothing stored about this"], "confidence": 0.5}
            f = facts[0]
            retrieved.append({"source": "knowledge", "fact": f.id, "provenance": f.provenance, "verification": f.verification})
            positive = (f.polarity == "positive") == (it.polarity == "positive")
            verb = self._user_verb(it) or ("like" if frame == "preference" else "drink")
            act = {"type": "answer", "frame": frame, "agent": {"kind": "self"}, "value": noun, "polarity": "positive" if positive else "negative", "yn": "yes" if positive else "no",
                   "verb_lemma": verb, "source": "told"}
            return {"acts": [act], "uncertainty": [], "confidence": 0.9}
        return {"acts": [], "uncertainty": [], "confidence": 0.3}

    # ---- funds ---------------------------------------------------------------------------------------------------------------------------
    def _funds(self, scope, it: Interp, state, cid, retrieved, stored) -> dict:
        value = it.roles["value"]["value"]
        if it.act == "assert":
            res = self.kb.assert_fact(scope, "attr.funds", {"owner": {"t": "self", "key": SELF_USER, "label": "you"}, "value": literal_term(value)}, confidence=min(0.9, it.confidence),
                                      source_type="user_statement", conversation_id=cid, qualifiers={"time": it.time} if it.time else None)
            stored.append({"fact": res.fact.to_dict() if res.fact else None, "status": res.status})
            return {"acts": [{"type": "ack", "frame": "funds", "agent": {"kind": "self"}, "value": value, "novelty": "repeat" if res.status == "duplicate" else "new", "time": it.time,
                              "valence": -1 if value == "insufficient" else 0, "tense": "present"}], "uncertainty": [], "confidence": it.confidence}
        f, _ = self._kb_value(scope, "attr.funds", {"key": SELF_USER}, cid)
        if f is None:
            return {"acts": [{"type": "unknown", "frame": "funds", "agent": {"kind": "self"}}], "uncertainty": ["no information about the user's finances"], "confidence": 0.5}
        retrieved.append({"source": "knowledge", "fact": f.id, "provenance": f.provenance, "verification": f.verification, "created_at": f.created_at})
        have = f.args["value"]["value"]
        agree = have == value
        act = {"type": "answer", "frame": "funds", "agent": {"kind": "self"}, "value": have, "yn": "yes" if agree else "no", "source": "told", "time": (f.qualifiers or {}).get("time")}
        return {"acts": [act], "uncertainty": ["based on what you said earlier; money situations change"], "confidence": 0.8}

    # ---- fragments ---------------------------------------------------------------------------------------------------------------------------
    def _fragment(self, scope, clauses: list[Clause], tokens, state: DialogueState, cid, stored) -> list[dict] | None:
        if len(clauses) != 1 or clauses[0].wh or (clauses[0].vg is not None and (clauses[0].subject is not None or clauses[0].items or clauses[0].vg.f.get("aux"))):
            return None
        q = state.answer_pending()
        if q is None:
            return None
        cl = clauses[0]
        words = [t for t in tokens[cl.tokens[0]:cl.tokens[1]] if t["pos"] not in ("DET", "PUNCT")]
        if q["slot"] == "model" and cl.vg is not None:
            return None
        if not words:
            return None
        value = " ".join(t["text"] for t in words)
        if q["slot"] == "model" and not any(t["pos"] in ("PROPN", "NOUN") for t in words):
            return None
        state.set_attr(q["entity"], q["slot"], value, evidence="fragment answer to a pending question")
        state.resolve_pending(q)
        state.touch(q["entity"])
        e = state.entities[q["entity"]]
        self._persist_entity_attr(scope, state, q["entity"], {"model": "attr.model", "use": "attr.use"}.get(q["slot"], "attr." + q["slot"]), value, cid, stored)
        if q["slot"] == "model":
            first = value.split()[0]
            state.set_attr(q["entity"], "maker", first, source="inferred", confidence=0.6, evidence="first word of the model name")
        acts = [{"type": "ack", "frame": ASK_SLOT_FRAME.get(q["slot"], "purpose"), "agent": {"kind": "self"}, "value": value if q["slot"] != "model" else value, "novelty": "new",
                 "thing_np": f"your {e.get('head', 'thing')}", "slot_fill": q["slot"], "tense": "present"}]
        acts += self._ask_next(state, q["entity"])
        return acts


def text_snip(it: Interp) -> str:
    return f"{it.frame}/{it.construction}"
