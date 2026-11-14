"""Frame matching: clauses (chunker output) -> typed meaning structures.

A *frame* (``data/frames.json``) is a predicate with roles plus several *constructions*: structural templates over clause constituents whose
open-class positions are **concept clusters** from the lexicon rather than words. "I live in Kampala", "I dwell in Kampala", "I am based in
Kampala", "Kampala is my home" and "My house is in Kampala" all produce the same ``residence`` frame because the verb/adjective/noun slots are
satisfied by the ``c.reside`` / ``c.based`` / ``c.home`` clusters and the roles are read from syntactic position. The same constructions
interpret questions: the role the question word asks about is simply the one left unfilled.

Two non-frame analyses live here as well, because they are compositional rather than slot-based:

* **funds**: a signed-concept composition ("short"(-) "on" "cash"; "can"+"not"(flip) "afford"(+); "don't"(flip) "have" "enough"(+)) that maps many
  surface forms onto one proposition without enumerating them.
* **reported speech**: "<source> says/thinks <clause>" wraps the embedded proposition with attribution and a hedge, so it is never stored as fact.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .chunker import Chunk, Clause, words_to_number
from .dialogue import DialogueState, gender_of_concept, kind_of_lemma
from .lexicon import ConceptGraph, default_graph

DATA = Path(__file__).parent / "data"
HEDGE_VERBS = {"think", "believe", "suppose", "reckon", "guess", "assume", "imagine"}
SELF_PRON = {"i", "me", "my", "myself", "we", "us", "our"}
OTHER_SUBJ = {"everyone", "everybody", "people", "someone", "somebody", "they", "you", "anyone", "nobody"}
TIME_WORDS = {"now", "today", "yesterday", "tomorrow", "tonight", "currently", "recently", "lately"}


@lru_cache(maxsize=1)
def load_frames() -> dict:
    return json.loads((DATA / "frames.json").read_text(encoding="utf-8"))


@dataclass
class Interp:
    act: str                                  # assert | ask | confirm_q | report
    frame: str
    roles: dict[str, dict] = field(default_factory=dict)
    polarity: str = "positive"
    ask: str | None = None                    # role asked about (wh-question)
    time: str | None = None
    tense: str = "present"
    hedge: str | None = None
    source: dict | None = None                # {"ref": ..., "verb": ...}  attribution for reported content
    confidence: float = 0.9
    evidence: list[str] = field(default_factory=list)
    clause: int = 0
    construction: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"act": self.act, "frame": self.frame, "construction": self.construction, "polarity": self.polarity, "tense": self.tense,
             "roles": {k: _brief(v) for k, v in self.roles.items()}, "confidence": round(self.confidence, 3), "evidence": self.evidence}
        for k in ("ask", "time", "hedge"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        if self.source:
            d["source"] = _brief(self.source.get("ref") or self.source)
        if self.extra:
            d["extra"] = self.extra
        return d


def _brief(ref: dict) -> dict:
    return {k: v for k, v in ref.items() if k in ("t", "id", "value", "kind", "label", "how", "pron", "role", "cands", "conf")}


class FrameMatcher:
    def __init__(self, graph: ConceptGraph | None = None):
        self.graph = graph or default_graph()
        self.frames = load_frames()["frames"]

    # ---- helpers ---------------------------------------------------------------------------------------------------------------------------
    def _is(self, lemma: str, concept: str, pos: str | None = None) -> bool:
        if not lemma:
            return False
        return any(m.concept == concept or self.graph.is_a(m.concept, concept) for m in self.graph.concepts_of(lemma, pos, strict=bool(pos)))

    def _verb_is(self, clause: Clause, concept: str) -> bool:
        return bool(clause.vg) and self._is(clause.vg.f.get("verb") or "", concept, "verb")

    def bind_np(self, np: Chunk, state: DialogueState, *, need_slot: str | None = None, creating: bool = False, default_owner: str | None = None) -> dict:
        f = np.f
        pron = f.get("pron")
        if pron:
            if pron in SELF_PRON:
                return {"t": "self", "how": "deixis"}
            if pron in OTHER_SUBJ:
                return {"t": "other", "pron": pron}
            eid, cands, conf = state.resolve_pronoun(pron, need_slot)
            if eid is None:
                return {"t": "unresolved", "pron": pron, "cands": []}
            return {"t": "entity", "id": eid, "how": "pronoun", "pron": pron, "conf": conf, "cands": cands}
        names = f.get("names") or []
        nouns = f.get("nouns") or []
        poss = f.get("poss")
        role_noun = f.get("role_noun")
        # named entity
        if names and not nouns:
            name = " ".join(names)
            eid = state.find_by_name(name)
            if eid:
                return {"t": "entity", "id": eid, "how": "name", "conf": 1.0}
            return {"t": "new", "kind": "named", "label": name, "names": [name], "person": False, "unknown_type": True, "owner": None, "adjs": f.get("adjs", [])}
        if role_noun and names:                                            # "my uncle Peter"
            name = " ".join(names)
            eid = state.find_by_name(name) or state.find_by_role(role_noun, "self" if poss == "my" else None)
            if eid:
                return {"t": "entity", "id": eid, "how": "name", "conf": 1.0}
            kind, concept, person = kind_of_lemma(self.graph, role_noun)
            return {"t": "new", "kind": kind, "label": name, "role": role_noun, "owner": "self" if poss == "my" else None, "names": [name], "person": person,
                    "gender": gender_of_concept(concept), "concept": concept, "adjs": []}
        if nouns:
            head = nouns[-1]
            kind, concept, person = kind_of_lemma(self.graph, head)
            if poss == "my":
                eid = state.find_by_role(head, "self") if person else None
                eid = eid or (state.find_by_kind(self.graph, head, "self") if not person else None)
                if eid:
                    return {"t": "entity", "id": eid, "how": "possessive", "conf": 0.95}
                if f.get("possessor"):
                    pass
                return {"t": "new", "kind": kind, "label": " ".join(f.get("adjs", []) + [head]), "role": head if person else None, "owner": "self", "names": [], "person": person,
                        "gender": gender_of_concept(concept), "concept": concept, "adjs": f.get("adjs", []), "head": head, "referring": True}
            if f.get("possessor"):
                poss_name = f["possessor"]
                eid = state.find_by_name(poss_name)
                return {"t": "literal", "value": head, "pos": "NOUN", "possessor": poss_name, "possessor_entity": eid}
            if f.get("det") in ("the", "this", "that"):
                eid = state.find_by_kind(self.graph, head)
                if eid:
                    return {"t": "entity", "id": eid, "how": "definite", "conf": 0.8}
            return {"t": "new", "kind": kind, "label": " ".join(f.get("adjs", []) + [head]), "role": head if person else None, "owner": default_owner, "names": [], "person": person,
                    "gender": gender_of_concept(concept), "concept": concept, "adjs": f.get("adjs", []), "head": head, "indefinite": f.get("det") in ("a", "an", None)}
        if "num" in f:
            return {"t": "literal", "value": f["num"], "pos": "NUM"}
        return {"t": "unresolved", "pron": None, "cands": []}

    @staticmethod
    def _literal(np: Chunk | None, kind: str = "text") -> dict | None:
        if np is None:
            return None
        names = np.f.get("names") or []
        if names:
            return {"t": "literal", "value": " ".join(names), "pos": "PROPN"}
        nouns = np.f.get("nouns") or []
        if nouns:
            return {"t": "literal", "value": (np.f.get("compound") or nouns[-1]), "pos": "NOUN"}
        return None

    def _time(self, clause: Clause) -> str | None:
        for c in clause.items:
            if c.kind == "ADVP" and c.head in TIME_WORDS:
                return c.head
            if c.kind == "NP" and c.head in TIME_WORDS:
                return c.head
            if c.kind == "PP" and c.f.get("prep") in ("on", "at", "in", "last", "since") and c.f.get("np") is not None:
                n = c.f["np"]
                h = (n.head or "").lower()
                if h in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "morning", "evening", "night", "moment", "week", "month", "year"):
                    return f"{c.f['prep']} {n.text}"
        # "right now": ADJ right + ADV now
        txt = " ".join(c.text.lower() for c in clause.items)
        for phrase in ("right now", "at the moment", "these days", "last week", "last year", "last month"):
            if phrase in txt:
                return phrase
        return None

    # ---- main entry ------------------------------------------------------------------------------------------------------------------------
    def interpret(self, clauses: list[Clause], state: DialogueState) -> tuple[list[Interp], list[dict]]:
        out: list[Interp] = []
        unmatched: list[dict] = []
        for idx, cl in enumerate(clauses):
            found = self._clause(cl, state, idx)
            if found:
                out.extend(found)
            else:
                unmatched.append({"clause": idx, "text": cl.text})
        # attach reported-speech wrapper: [X says] + [that ...]
        merged: list[Interp] = []
        skip: set[int] = set()
        for i, it in enumerate(out):
            merged.append(it)
        return merged, unmatched

    def _clause(self, cl: Clause, state: DialogueState, idx: int) -> list[Interp]:
        is_q = bool(cl.wh) or cl.inverted or cl.punct_question
        # a bare verb group with a hedge/report verb and no complement is the head of a reported clause: handled by the caller through ``report``
        if cl.vg is not None and not is_q and self._reporting_verb(cl) and not cl.items:
            return [Interp("report_head", "report", {"source": self._subject_ref(cl, state)}, extra={"verb": cl.vg.f.get("verb")}, clause=idx)]
        funds = self._funds(cl, state, is_q, idx)
        if funds:
            return funds
        age = self._age(cl, state, is_q, idx)
        if age:
            return [age]
        res: list[Interp] = []
        for fid, spec in self.frames.items():
            for cons in spec["constructions"]:
                it = self._construction(cl, fid, spec, cons, state, is_q, idx)
                if it:
                    res.append(it)
        if not res:
            return []
        res.sort(key=lambda i: -i.confidence)
        return [res[0]]

    def _reporting_verb(self, cl: Clause) -> bool:
        v = (cl.vg.f.get("verb") if cl.vg else "") or ""
        return self._is(v, "c.say", "verb") or self._is(v, "c.think", "verb")

    def _subject_ref(self, cl: Clause, state: DialogueState, need_slot: str | None = None) -> dict:
        if cl.subject is None:
            return {"t": "unresolved"}
        return self.bind_np(cl.subject, state, need_slot=need_slot)

    # ---- constructions ---------------------------------------------------------------------------------------------------------------------
    def _construction(self, cl: Clause, fid: str, spec: dict, cons: dict, state: DialogueState, is_q: bool, idx: int) -> Interp | None:
        typ = cons["type"]
        roles: dict[str, dict] = {}
        ev: list[str] = []
        ask_role = None
        asked_wh = cl.wh
        polarity = "negative" if cl.negated else "positive"
        tense = cl.tense
        need_slot = {"maker": "maker", "purpose": "purpose", "name": "name"}.get(spec.get("value"))

        def bind_role(role: str | None, np: Chunk | None):
            if role is None or np is None:
                return
            if role in ("agent", "thing", "other", "maker"):
                roles[role] = self.bind_np(np, state, need_slot=need_slot if role in ("thing",) else None, default_owner="self" if role == "thing" else None)
            else:
                roles[role] = self._literal(np) or {"t": "literal", "value": np.text}

        subj = cl.subject
        nps = [c for c in cl.items if c.kind == "NP" and not c.f.get("pron") == "it" or c.kind == "NP"]
        obj_nps = [c for c in cl.items if c.kind == "NP" and not c.f.get("wh")]
        ppmap = cons.get("pp", {})

        if typ == "V":
            if not self._verb_is(cl, cons["verb"]):
                return None
            if cons["verb"] == "c.do_living":
                lv = [c for c in cl.items if c.kind == "PP" and c.f.get("prep") == "for"] if "living" in cl.text.lower() else []
                if not (cl.wh == "what" and (lv or not cl.items)):
                    return None
                bind_role(cons.get("subject"), subj)
                if "agent" not in roles:
                    return None
                ask_role = spec["ask"].get("what"); ev.append("do+for a living → occupation question")
            else:
                if cons.get("needs_tense") and not (tense in cons["needs_tense"] or cl.vg.f.get("aspect") in cons["needs_tense"] or cl.vg.f.get("aspect") == "progressive"):
                    return None
                subj_role = cons.get("subject")
                if subj is not None:
                    bind_role(subj_role, subj)
                elif cl.wh in spec.get("ask", {}) and spec["ask"][cl.wh] == subj_role:
                    ask_role = subj_role
                elif cl.elided_subject:
                    return None
                if cons.get("object"):
                    o = next((c for c in obj_nps), None)
                    if o is not None and o.f.get("neg_det") and cons["verb"] != "c.call":
                        polarity = "negative" if polarity == "positive" else "positive"
                    if o is not None and not (cons.get("complement") and cons["verb"] == "c.call"):
                        bind_role(cons["object"], o)
                        if cons.get("object_kind") and roles.get(cons["object"], {}).get("t") == "new" and roles[cons["object"]].get("kind") != cons["object_kind"]:
                            return None
                    elif cons["verb"] == "c.call":
                        pass
                    elif cl.wh in spec.get("ask", {}) and spec["ask"][cl.wh] == cons["object"]:
                        ask_role = cons["object"]
                if cons["verb"] == "c.call":
                    return self._call_construction(cl, fid, spec, cons, state, is_q, idx, roles)
                for pp in cl.items:
                    if pp.kind == "PP":
                        role = ppmap.get(pp.f.get("prep"))
                        if role:
                            npc = pp.f.get("np")
                            if npc is not None:
                                roles[role] = self._literal(npc) or {"t": "literal", "value": npc.text}
                            elif pp.f.get("prep") == "for" and cl.wh == "what":
                                ask_role = role
                if cl.wh and cl.wh in spec.get("ask", {}) and ask_role is None:
                    r = spec["ask"][cl.wh]
                    if r not in roles:
                        ask_role = r
                # a stranded "for" ("What do I use it for?"): the purpose is what's asked
                if cons["verb"] == "c.use" and any(c.kind == "PP" and c.f.get("prep") == "for" and c.f.get("np") is None for c in cl.items):
                    ask_role = "purpose"
                if cons["verb"] == "c.use" and "purpose" not in roles and ask_role is None:
                    return None
                if cons["verb"] == "c.use" and not any(c.kind == "PP" and c.f.get("prep") in ("for", "as") for c in cl.items):
                    return None
        elif typ == "V_PASSIVE":
            return self._passive_call(cl, fid, spec, cons, state, is_q, idx)
        elif typ == "COP_ADJ":
            if not cl.vg or not (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be" or "be" in cl.vg.f.get("aux", [])):
                return None
            adj = next((c for c in cl.items if c.kind in ("ADJP", "VG") and self._is(c.head or (c.f.get("lemmas") or [""])[-1], cons["adj"])), None)
            if adj is None and "be" in cl.vg.f.get("aux", []) and self._is(cl.vg.f.get("verb") or "", cons["adj"]):
                adj = cl.vg                                  # "I'm located in …": passive participle fused into the verb group
            if adj is None:
                return None
            bind_role(cons["subject"], subj)
            for pp in cl.items:
                if pp.kind == "PP" and ppmap.get(pp.f.get("prep")) and pp.f.get("np") is not None:
                    roles[ppmap[pp.f["prep"]]] = self._literal(pp.f["np"]) or {"t": "literal", "value": pp.f["np"].text}
            if cl.wh == "where":
                ask_role = spec["ask"]["where"]
        elif typ == "COP_WHERE":
            if not (cl.vg and (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be")) or subj is None or subj.f.get("pron"):
                return None
            rel_vg = next((c for c in cl.items if c.kind == "VG" and self._is(c.f.get("verb") or "", cons["verb"], "verb")), None)
            rel_np = next((c for c in cl.items if c.kind == "NP" and c.f.get("pron") in ("i", "we")), None)
            if rel_vg is None or rel_np is None or not any(c.kind == "WH" and c.head == "where" for c in cl.items):
                return None
            lit = self._literal(subj)
            if lit is None or lit.get("pos") != "PROPN":
                return None
            roles = {"agent": {"t": "self", "how": "deixis"}, "place": lit}
            return Interp("assert", fid, roles, "negative" if cl.negated else "positive", None, self._time(cl), cl.tense, None, None, 0.85, ["copular 'X is where I live'"], idx, "COP_WHERE",
                          {"verb": rel_vg.f.get("verb")})
        elif typ == "COP_NP" and cons.get("value_from") == "pp":
            if not (cl.vg and (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be")) or subj is None:
                return None
            comp = next((c for c in obj_nps if self._is(c.head, cons["complement"], "noun") or any(self._is(n, cons["complement"], "noun") for n in c.f.get("nouns", []))), None)
            if comp is None:
                return None
            bind_role(cons["subject"], subj)
            for pp in cl.items:
                if pp.kind == "PP" and ppmap.get(pp.f.get("prep")) and pp.f.get("np") is not None:
                    roles[ppmap[pp.f["prep"]]] = self._literal(pp.f["np"]) or {"t": "literal", "value": pp.f["np"].text}
            if cl.wh == "where":
                ask_role = "place"
        elif typ == "COP_NP":
            if not (cl.vg and (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be")):
                return None
            comp = next((c for c in obj_nps if self._is(c.head, cons["complement"], "noun") or any(self._is(n, cons["complement"], "noun") for n in c.f.get("nouns", []))), None)
            if comp is None:
                return None
            if cons.get("value_from") == "complement":
                bind_role(cons["subject"], subj)
                if "agent" not in roles:
                    if cl.wh:
                        return None
                    return None
                roles["occupation"] = {"t": "literal", "value": comp.head or (comp.f.get("nouns") or [""])[-1], "pos": "NOUN"}
                polarity = polarity
            else:
                if comp.f.get("poss") is None:
                    return None
                roles[cons["possessor"]] = {"t": "self", "how": "deixis"} if comp.f["poss"] in ("my", "our") else self._possessor_ref(comp.f["poss"], state)
                if subj is None:
                    return None
                roles[cons["subject"]] = self._literal(subj) or {"t": "literal", "value": subj.text}
                if roles[cons["subject"]]["t"] == "literal" and roles[cons["subject"]].get("pos") != "PROPN":
                    return None
        elif typ == "POSS_COP":
            if not (cl.vg and (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be")):
                return None
            cands = ([subj] if subj is not None else []) + obj_nps
            head = next((c for c in cands if c.f.get("poss") and any(self._is(n, cons["head"], "noun") for n in (c.f.get("nouns") or [c.head]))), None)
            if head is None:
                return None
            roles[cons["possessor"]] = {"t": "self", "how": "deixis"} if head.f["poss"] in ("my", "our") else self._possessor_ref(head.f["poss"], state)
            other = next((c for c in cands if c is not head and not c.f.get("wh") and not c.f.get("poss")), None)
            if other is not None:
                lit = self._literal(other)
                if lit is None:
                    return None
                roles[cons["complement"]] = lit
            elif cl.wh:
                ask_role = cons["complement"]
        elif typ == "NP_PP":
            if not (cl.vg and (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be")) or subj is None:
                return None
            if not (subj.f.get("poss") and any(self._is(n, cons["head"], "noun") for n in (subj.f.get("nouns") or [subj.head]))):
                return None
            roles[cons["possessor"]] = {"t": "self", "how": "deixis"} if subj.f["poss"] in ("my", "our") else self._possessor_ref(subj.f["poss"], state)
            for pp in cl.items:
                if pp.kind == "PP" and ppmap.get(pp.f.get("prep")) and pp.f.get("np") is not None:
                    roles[ppmap[pp.f["prep"]]] = self._literal(pp.f["np"]) or {"t": "literal", "value": pp.f["np"].text}
            if cl.wh == "where":
                ask_role = "place"
        elif typ == "COP_NAME":
            if not (cl.vg and (cl.vg.f.get("copula") or cl.vg.f.get("verb") == "be")) or subj is None or not subj.f.get("pron") in ("i", "me"):
                return None
            comp = next((c for c in obj_nps if c.f.get("names") and not c.f.get("nouns")), None)
            if comp is None:
                return None
            roles["agent"] = {"t": "self", "how": "deixis"}
            roles["name"] = {"t": "literal", "value": " ".join(comp.f["names"]), "pos": "PROPN"}
        else:
            return None
        return self._finish(cl, fid, spec, cons, roles, ask_role, polarity, tense, is_q, idx, ev)

    def _possessor_ref(self, poss: str, state: DialogueState) -> dict:
        if poss in ("his", "her"):
            eid, cands, conf = state.resolve_pronoun("he" if poss == "his" else "she")
            return {"t": "entity", "id": eid, "how": "pronoun", "conf": conf} if eid else {"t": "unresolved", "pron": poss}
        return {"t": "other", "pron": poss}

    def _call_construction(self, cl, fid, spec, cons, state, is_q, idx, roles) -> Interp | None:
        nps = [c for c in cl.items if c.kind == "NP"]
        as_pp = next((p.f["np"] for p in cl.items if p.kind == "PP" and p.f.get("prep") == "as" and p.f.get("np") is not None), None)
        if len(nps) < 2 and not cl.wh and as_pp is None:
            return None
        target = nps[0] if nps else None
        value = nps[1] if len(nps) > 1 else as_pp
        if target is None or not target.f.get("pron") in ("i", "me", "myself"):
            return None
        roles.pop("other", None)
        roles["agent"] = {"t": "self", "how": "deixis"}
        if value is not None:
            lit = self._literal(value)
            if lit is None or lit.get("pos") != "PROPN":
                return None
            roles["name"] = lit
        return self._finish(cl, fid, spec, cons, roles, spec["ask"].get(cl.wh) if cl.wh else None, "negative" if cl.negated else "positive", cl.tense, is_q, idx, [])

    def _passive_call(self, cl, fid, spec, cons, state, is_q, idx) -> Interp | None:
        if not cl.vg:
            return None
        verb_chunk_is_called = (cl.vg.f.get("verb") and self._is(cl.vg.f["verb"], "c.call", "verb")) or any(
            c.kind in ("ADJP", "VG") and self._is(c.head or "", "c.call", "verb") for c in cl.items) or "called" in cl.text.lower() or "named" in cl.text.lower()
        if not (cl.vg.f.get("copula") or "be" in cl.vg.f.get("aux", [])) or not verb_chunk_is_called:
            return None
        roles: dict[str, dict] = {}
        if cl.subject is None:
            return None
        roles["agent"] = self.bind_np(cl.subject, state, need_slot="name")
        if roles["agent"].get("t") == "self" and cl.subject.f.get("pron") not in ("i",):
            return None
        names = [c for c in cl.items if c.kind == "NP" and c.f.get("names") and not c.f.get("pron")]
        ask = None
        if names:
            roles["name"] = {"t": "literal", "value": " ".join(names[-1].f["names"]), "pos": "PROPN"}
        elif cl.wh == "what":
            ask = "name"
        else:
            return None
        return self._finish(cl, fid, spec, cons, roles, ask, "negative" if cl.negated else "positive", cl.tense, is_q, idx, ["passive 'is called/named'"])

    def _finish(self, cl, fid, spec, cons, roles, ask_role, polarity, tense, is_q, idx, ev) -> Interp | None:
        owner_role = spec["owner"]
        val_role = spec["value"]
        have_owner = owner_role in roles
        if not have_owner:
            return None
        if fid in ("occupation", "residence", "naming", "age"):
            # selectional restriction: abstract nouns cannot have a job, a home, a name or an age ("My goal is to learn chess" is not an occupation)
            ow = roles[owner_role]
            if ow.get("t") == "new" and (ow.get("label") or "").split(" ")[-1] in ("goal", "plan", "idea", "problem", "thing", "reason", "wish", "dream", "aim"):
                return None
            if fid == "occupation" and ow.get("t") == "new" and ow.get("kind") not in ("person", "named", None) and not ow.get("person"):
                return None                       # only people (or named things of unknown type) have occupations; a cat or a laptop does not
        if fid == "preference" and cl.vg is not None and (cl.vg.f.get("verb") or "") == "prefer":
            return None                           # "I prefer short answers" is a response-style preference handled by the preference engine, not a liked thing
        if cl.wh and ask_role is None and val_role in roles:
            ask_role = None
        asking = ask_role is not None
        if is_q and not asking:
            if val_role in roles or fid in ("preference", "consumption"):
                act = "confirm_q"
            else:
                return None
        elif asking:
            act = "ask"
        else:
            if val_role not in roles:
                return None
            act = "assert"
        if act == "assert" and cons.get("polarity"):
            polarity = cons["polarity"] if polarity == "positive" else ("negative" if cons["polarity"] == "positive" else "positive")
        if act == "confirm_q" and cons.get("polarity"):
            polarity = cons["polarity"] if polarity == "positive" else ("negative" if cons["polarity"] == "positive" else "positive")
        if act == "ask" and ask_role not in (val_role, owner_role):
            return None
        conf = 0.9
        for r in roles.values():
            if r.get("t") == "unresolved":
                conf = min(conf, 0.3)
            if r.get("t") == "entity" and r.get("conf") is not None:
                conf = min(conf, r["conf"])
        return Interp(act, fid, roles, polarity, ask_role, self._time(cl), tense, None, None, conf, ev, idx, cons["type"], {"verb": (cl.vg.f.get("verb") if cl.vg else None)})

    def _age(self, cl: Clause, state: DialogueState, is_q: bool, idx: int) -> Interp | None:
        """"I am thirty years old" / "I turned 30" / "How old am I?" -> age frame (value is a number)."""
        if cl.vg is None:
            return None
        subj_ref = None
        if cl.subject is not None and cl.subject.f.get("pron") in ("i", "we", "me"):
            subj_ref = {"t": "self", "how": "deixis"}
        elif cl.subject is not None:
            subj_ref = self.bind_np(cl.subject, state)
        if subj_ref is None:
            return None
        if cl.wh == "how_old":
            return Interp("ask", "age", {"agent": subj_ref}, "positive", "value", None, cl.tense, None, None, 0.9, ["how old → age question"], idx, "AGE_Q")
        num = None
        for c in cl.items:
            if c.kind == "NP" and "num" in c.f:
                num = c.f["num"]
                has_year = "year" in (c.f.get("nouns") or [])
                old = any(x.kind in ("ADJP", "VG") and (x.head or "") in ("old", "age") or "old" in (x.f.get("lemmas") or []) for x in cl.items) or "old" in cl.text.lower().split()
                turned = self._verb_is(cl, "c.turn")
                if (has_year and old) or turned or (old and not c.f.get("nouns")):
                    break
                num = None
        if num is None or is_q:
            return None
        return Interp("assert", "age", {"agent": subj_ref, "value": {"t": "literal", "value": str(num), "pos": "NUM"}}, "negative" if cl.negated else "positive", None, self._time(cl), cl.tense,
                      None, None, 0.9, ["age expression"], idx, "AGE")

    # ---- funds (compositional) -------------------------------------------------------------------------------------------------------------
    def _funds(self, cl: Clause, state: DialogueState, is_q: bool, idx: int) -> list[Interp]:
        lemmas: list[tuple[str, str]] = []
        for c in cl.items + ([cl.vg] if cl.vg else []):
            if c is None:
                continue
            if c.kind == "PP" and c.f.get("np") is not None:
                lemmas.append((c.f["np"].head, "n"))
                for n in c.f["np"].f.get("nouns", []):
                    lemmas.append((n, "n"))
            elif c.kind == "ADJP":
                lemmas += [(l, "a") for l in c.f.get("lemmas", [c.head])]
            elif c.kind == "NP":
                lemmas += [(l, "n") for l in (c.f.get("nouns") or [c.head])] + [(l, "a") for l in c.f.get("adjs", [])]
            elif c.kind == "VG":
                lemmas.append((c.f.get("verb") or "", "v"))
                lemmas += [(w.lower(), "a") for w in c.text.replace("'", " ").split()]
            elif c.kind in ("ADVP",):
                lemmas.append((c.head, "r"))
        subj_lem = cl.subject.head if cl.subject is not None else ""
        has_money = any(self._is(l, "c.money") for l, _ in lemmas)
        signs: list[tuple[int, str]] = []
        for l, p in lemmas:
            if not l:
                continue
            for cid, s in (("c.insufficient", -1), ("c.penniless", -1), ("c.lack", -1), ("c.enough", 1), ("c.afford", 1)):
                if self._is(l, cid):
                    if cid in ("c.insufficient", "c.lack") and not has_money:
                        continue
                    signs.append((s, l))
            if self._is(l, "c.depleted") and has_money:
                signs.append((-1, l))
        if any(c.kind == "NP" and c.f.get("neg_det") and any(self._is(n, "c.money") for n in (c.f.get("nouns") or [])) for c in cl.items) and not signs:
            signs.append((-1, "no money"))
        pay = [l for l, p in lemmas if p == "v" and self._is(l, "c.pay") and cl.vg and cl.vg.f.get("modal") == "ability"]
        if pay and not signs and (cl.negated or is_q):
            signs.append((1, pay[0]))
        if not signs:
            return []
        if not (has_money or any(self._is(l, "c.penniless") or self._is(l, "c.afford") for l, _ in lemmas) or pay):
            return []
        sign = 1
        for s, _ in signs:
            sign *= s
        if cl.negated:
            sign *= -1
        value = "sufficient" if sign > 0 else "insufficient"
        agent = {"t": "self", "how": "deixis"}
        if cl.subject is not None and cl.subject.f.get("pron") not in (None, "i", "me", "we", "us", "my"):
            agent = self.bind_np(cl.subject, state)
        ev = [f"signed concepts {[(s, l) for s, l in signs]}", f"negation={'yes' if cl.negated else 'no'}", f"→ funds {value}"]
        it = Interp("confirm_q" if is_q else "assert", "funds", {"agent": agent, "value": {"t": "literal", "value": value, "pos": "ADJ"}}, "positive", None, self._time(cl),
                    cl.tense, None, None, 0.85, ev, idx, "composition")
        return [it]
