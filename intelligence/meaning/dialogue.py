"""Dialogue state: which entities are active, how salient they are, what was asked and is awaiting an answer, what was corrected.

This is *understanding* state, not history. A message log is stored elsewhere; this structure holds what the conversation is currently about:

* ``entities``  – things and people introduced in the conversation with kind, owner, attributes (each with value, turn, source, confidence).
* salience      – recency-weighted activation used to resolve pronouns; introducing or mentioning an entity raises it, every turn decays all others.
* ``pending``   – questions the system asked and has not had answered (slot filling): a short fragment such as "A Lenovo ThinkPad." answers one.
* ``corrections`` / ``moves`` – bounded logs for inspection and for revising an earlier statement.

The state is JSON-serialisable and stored inside the conversation's context state, so it survives between requests and follows the same
scoping (a conversation's state is only readable inside its own project/user scope).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from .lexicon import ConceptGraph, default_graph

DATA = Path(__file__).parent / "data"
DECAY = 0.72
MAX_ENTITIES = 40
MAX_MOVES = 60


def _slots() -> dict:
    return json.loads((DATA / "slots.json").read_text(encoding="utf-8"))


class DialogueState:
    def __init__(self, data: dict | None = None):
        d = data or {}
        self.turn: int = d.get("turn", 0)
        self.entities: dict[str, dict] = d.get("entities", {})
        self.pending: list[dict] = d.get("pending", [])
        self.topic: str | None = d.get("topic")
        self.topics: list[str] = d.get("topics", [])
        self.moves: list[dict] = d.get("moves", [])
        self.corrections: list[dict] = d.get("corrections", [])
        self.counter: int = d.get("counter", 0)
        self.last_question: dict | None = d.get("last_question")      # the user's last question, for "and Rwanda?"-style follow-ups
        self.recent_out: list[str] = d.get("recent_out", [])           # last few system sentences, used to avoid repeating wording

    def to_dict(self) -> dict:
        return {"turn": self.turn, "entities": self.entities, "pending": self.pending, "topic": self.topic, "topics": self.topics[-12:],
                "moves": self.moves[-MAX_MOVES:], "corrections": self.corrections[-20:], "counter": self.counter, "last_question": self.last_question,
                "recent_out": self.recent_out[-8:]}

    def snapshot(self) -> dict:
        """Compact, privacy-conscious view for diagnostics: entity kinds/labels/salience and pending slots, no raw message text."""
        return {"turn": self.turn, "topic": self.topic,
                "entities": {i: {"kind": e["kind"], "label": e.get("label"), "salience": round(e.get("salience", 0), 3), "attrs": sorted(e.get("attrs", {}))} for i, e in self.entities.items()},
                "pending": [{"entity": p["entity"], "slot": p["slot"]} for p in self.pending]}

    def copy(self) -> "DialogueState":
        return DialogueState(copy.deepcopy(self.to_dict()))

    # ---- turn lifecycle --------------------------------------------------------------------------------------------------------------------
    def begin_turn(self) -> None:
        self.turn += 1
        for e in self.entities.values():
            e["salience"] = round(e.get("salience", 0.0) * DECAY, 4)

    # ---- entities --------------------------------------------------------------------------------------------------------------------------
    def add_entity(self, kind: str, label: str, *, concept: str | None = None, role: str | None = None, owner: str | None = None, gender: str | None = None,
                   names: list[str] | None = None, adjs: list[str] | None = None, person: bool = False, source: str = "user_statement") -> str:
        self.counter += 1
        eid = f"e{self.counter}"
        self.entities[eid] = {"id": eid, "kind": kind, "concept": concept, "label": label, "role": role, "owner": owner, "gender": gender, "names": names or [],
                              "adjs": adjs or [], "person": person, "attrs": {}, "salience": 1.0, "introduced": self.turn, "last": self.turn, "source": source}
        self.topic = eid
        if eid not in self.topics:
            self.topics.append(eid)
        if len(self.entities) > MAX_ENTITIES:
            drop = min((e for e in self.entities.values() if e["id"] != eid), key=lambda e: e["salience"])
            self.entities.pop(drop["id"], None)
        return eid

    def touch(self, eid: str, bump: float = 1.0) -> None:
        e = self.entities.get(eid)
        if e:
            e["salience"] = max(e.get("salience", 0.0), bump)
            e["last"] = self.turn
            self.topic = eid

    def set_attr(self, eid: str, slot: str, value, *, source: str = "user_statement", confidence: float = 0.9, evidence: str | None = None) -> dict:
        e = self.entities[eid]
        prior = e["attrs"].get(slot)
        rec = {"value": value, "turn": self.turn, "source": source, "confidence": confidence}
        if evidence:
            rec["evidence"] = evidence
        if prior and prior["value"] != value:
            rec["revises"] = {"value": prior["value"], "turn": prior["turn"]}
            self.corrections.append({"entity": eid, "slot": slot, "old": prior["value"], "new": value, "turn": self.turn})
        e["attrs"][slot] = rec
        return rec

    def find_by_name(self, name: str) -> str | None:
        low = name.lower()
        for eid, e in self.entities.items():
            if low in [n.lower() for n in e.get("names", [])] or (e["attrs"].get("name", {}).get("value", "") or "").lower() == low:
                return eid
        return None

    def find_by_role(self, role: str, owner: str | None = None) -> str | None:
        best = None
        for eid, e in self.entities.items():
            if e.get("role") == role and (owner is None or e.get("owner") == owner):
                if best is None or e["salience"] > self.entities[best]["salience"]:
                    best = eid
        return best

    def find_by_kind(self, graph: ConceptGraph, lemma: str, owner: str | None = None) -> str | None:
        best = None
        for eid, e in self.entities.items():
            if (e.get("label") or "").lower().endswith(lemma.lower()) or graph.relation(lemma, e.get("label", "").split()[-1])[0] in ("same", "synonym"):
                if owner is None or e.get("owner") == owner:
                    if best is None or e["salience"] > self.entities[best]["salience"]:
                        best = eid
        return best

    # ---- reference resolution --------------------------------------------------------------------------------------------------------------
    def compatible(self, eid: str, *, person: bool | None, gender: str | None, need_slot: str | None) -> bool:
        e = self.entities[eid]
        if person is not None and bool(e.get("person")) != person:
            return False
        if gender and e.get("gender") and e["gender"] != gender:
            return False
        if need_slot:
            allowed = _slots()["selectional"].get(need_slot)
            if allowed and e["kind"] not in allowed:
                return False
        return True

    def resolve_pronoun(self, pron: str, need_slot: str | None = None) -> tuple[str | None, list[str], float]:
        """Return (entity id, candidates, confidence). ``it`` -> non-person entities, he/she -> people (gender-compatible), chosen by salience
        after selectional restrictions of the governing predicate. Several equally salient candidates lower the confidence."""
        pron = pron.lower()
        person = None if pron in ("they", "them") else pron in ("he", "him", "she", "her")
        gender = "male" if pron in ("he", "him", "his") else "female" if pron in ("she", "her", "hers") else None
        cands = [e for e in self.entities if self.compatible(e, person=person, gender=gender, need_slot=need_slot)]
        if not cands:
            return None, [], 0.0
        cands.sort(key=lambda i: (-self.entities[i]["salience"], -self.entities[i]["last"]))
        top = self.entities[cands[0]]["salience"]
        close = [c for c in cands if top - self.entities[c]["salience"] < 0.08]
        conf = 0.95 if len(close) == 1 else 0.5
        return cands[0], cands[:4], conf

    # ---- pending questions ---------------------------------------------------------------------------------------------------------------
    def ask(self, eid: str, slot: str, role: str) -> dict:
        q = {"entity": eid, "slot": slot, "role": role, "turn": self.turn}
        self.pending = [p for p in self.pending if not (p["entity"] == eid and p["slot"] == slot)] + [q]
        return q

    def next_open_slot(self, eid: str) -> tuple[str, str] | None:
        e = self.entities.get(eid)
        if not e:
            return None
        for slot, role in _slots()["kinds"].get(e["kind"], {}).get("slots", []):
            if slot not in e["attrs"] and not any(p["entity"] == eid and p["slot"] == slot for p in self.pending):
                return slot, role
        return None

    def answer_pending(self) -> dict | None:
        """The oldest still-valid pending question (questions older than 3 turns lapse: the topic has moved on)."""
        self.pending = [p for p in self.pending if self.turn - p["turn"] <= 3 and p["entity"] in self.entities]
        return self.pending[0] if self.pending else None

    def resolve_pending(self, q: dict) -> None:
        self.pending = [p for p in self.pending if p is not q and not (p["entity"] == q["entity"] and p["slot"] == q["slot"])]

    def log(self, **move) -> None:
        self.moves.append({"turn": self.turn, **move})
        self.moves = self.moves[-MAX_MOVES:]


def kind_of_lemma(graph: ConceptGraph, lemma: str) -> tuple[str, str | None, bool]:
    """(kind, concept id, is_person) for a common-noun lemma, using the slot inventory's concept clusters via hypernym closure."""
    slots = _slots()["kinds"]
    for m in graph.concepts_of(lemma, "noun", strict=True):
        for kind, spec in slots.items():
            if any(graph.is_a(m.concept, c) for c in spec["concepts"]):
                return kind, m.concept, spec["person"]
    return "thing", None, False


def gender_of_concept(concept: str | None) -> str | None:
    return _slots()["gender"].get(concept or "")
