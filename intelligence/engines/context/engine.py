"""Context Engine: conversational continuity and reference resolution.

State kept per conversation (JSON-serialisable so it persists through ``ConversationStore``):

* an **entity salience table** (who/what has been talked about, how recently, in what grammatical role),
* the **options list** (ordered alternatives that "the first one", "that one", "the previous option" refer to),
* the **current topic**, **unresolved questions**, the last ``question frame`` (for elliptical follow-ups),
* a short **turn history**.

Reference resolution is a constraint-and-salience algorithm (a simplified centering/salience scheme in the
tradition of Lappin & Leass): candidates must agree in number/gender/animacy and satisfy the selectional
constraints of the predicate they appear in and a binding constraint (a non-reflexive pronoun cannot corefer
with another argument of the same predicate); survivors are ranked by recency, grammatical-role salience and
mention frequency. A near-tie is reported as *ambiguous* instead of being guessed.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.types import new_id
from ...representation import (
    ACRDocument, Concept, Entity, Event, Intention, Logical, Provenance, Proposition, Reference, Uncertainty, Variable, concepts,
)

ROLE_WEIGHT = {"subject": 3.0, "object": 2.0, "complement": 1.8, "value": 1.8, "owner": 1.5, "pp": 1.0, "fragment": 2.0}
DECAY = 0.6
MAX_TURNS_KEPT = 20
MAX_ENTITIES = 60


@dataclass
class ContextEntity:
    key: str
    label: str
    entity_type: str
    features: dict[str, Any]
    salience: float = 0.0
    last_turn: int = 0
    mentions: int = 0
    first_turn: int = 0
    kind: str = "entity"                 # entity | concept

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "entity_type": self.entity_type, "features": self.features,
                "salience": round(self.salience, 4), "last_turn": self.last_turn, "mentions": self.mentions,
                "first_turn": self.first_turn, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "ContextEntity":
        return cls(**{k: d[k] for k in ("key", "label", "entity_type", "features", "salience", "last_turn", "mentions", "first_turn")},
                   kind=d.get("kind", "entity"))


@dataclass
class ConversationState:
    conversation_id: str
    turn: int = 0
    entities: dict[str, ContextEntity] = field(default_factory=dict)
    options: list[dict] = field(default_factory=list)         # ordered [{"key","label"}]
    option_focus: int | None = None
    topic: dict[str, Any] = field(default_factory=dict)
    unresolved_questions: list[dict] = field(default_factory=list)
    pending_clarification: dict | None = None
    last_question: dict | None = None                          # {"doc": acr dict, "turn": n}
    history: list[dict] = field(default_factory=list)          # [{"turn", "role", "text"}]
    user: dict[str, Any] = field(default_factory=dict)
    dialogue: dict[str, Any] = field(default_factory=dict)        # meaning-layer dialogue state (entities, salience, pending slots); see intelligence/meaning/dialogue.py
    premises: dict[str, Any] = field(default_factory=dict)        # meaning-layer deduction premises for this conversation

    def to_dict(self) -> dict:
        return {"conversation_id": self.conversation_id, "turn": self.turn,
                "entities": {k: v.to_dict() for k, v in self.entities.items()}, "options": self.options,
                "option_focus": self.option_focus, "topic": self.topic, "unresolved_questions": self.unresolved_questions,
                "pending_clarification": self.pending_clarification, "last_question": self.last_question,
                "history": self.history[-MAX_TURNS_KEPT:], "user": self.user, "dialogue": self.dialogue, "premises": self.premises}

    @classmethod
    def from_dict(cls, d: dict) -> "ConversationState":
        st = cls(conversation_id=d["conversation_id"], turn=d.get("turn", 0))
        st.entities = {k: ContextEntity.from_dict(v) for k, v in d.get("entities", {}).items()}
        st.options = d.get("options", [])
        st.option_focus = d.get("option_focus")
        st.topic = d.get("topic", {})
        st.unresolved_questions = d.get("unresolved_questions", [])
        st.pending_clarification = d.get("pending_clarification")
        st.last_question = d.get("last_question")
        st.history = d.get("history", [])
        st.user = d.get("user", {})
        st.dialogue = d.get("dialogue", {})
        st.premises = d.get("premises", {})
        return st


@dataclass
class ResolutionReport:
    resolved: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    ellipsis: dict | None = None
    linked_definites: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"resolved": self.resolved, "ambiguous": self.ambiguous, "unresolved": self.unresolved, "ellipsis": self.ellipsis,
                "linked_definites": self.linked_definites}

    @property
    def confidence(self) -> float | None:
        refs = self.resolved + self.ambiguous + self.unresolved
        if not refs:
            return None
        score = sum(r.get("confidence", 0.0) for r in self.resolved)
        return score / len(refs)


def _entity_key(node: Entity | Concept) -> str:
    if isinstance(node, Concept):
        return node.concept_id
    lemma = node.features.get("lemma")
    if lemma and not node.features.get("definite") is None and node.entity_type != "class.person" and node.features.get("animacy") != "unknown" \
            and node.label.lower() == (lemma or "").lower():
        return f"{lemma}"
    return node.label.lower()


class ContextEngine(Engine):
    info = EngineInfo(
        key="context", name="Context Engine", status=EngineStatus.IMPLEMENTED,
        summary="Tracks conversational state and resolves pronouns, demonstratives, ordinals and elliptical follow-ups.",
        depends_on=("language",),
        capabilities=("entity salience with recency decay", "pronoun resolution (agreement, selectional, binding, salience)",
                      "ambiguity detection instead of forced guesses", "options list with ordinal/previous/next/'that one' references",
                      "topic tracking", "unresolved-question tracking", "elliptical follow-up completion", "serialisable state"),
        limitations=("Resolution is intra- and inter-utterance only for singular/plural pronouns and simple demonstratives; "
                     "split antecedents, bridging ('the engine' of a car) and event anaphora are not resolved.",
                     "Ellipsis completion substitutes one entity in the previous question; it states its interpretation so users can correct it."),
    )

    def __init__(self) -> None:
        super().__init__()

    def self_check(self) -> tuple[bool, str]:
        from ..language.en.pipeline import EnglishPipeline
        st = self.new_state("probe")
        pipe = EnglishPipeline()
        doc = pipe.analyze("Sarah gave Michael a book because he needed it.").doc
        self.resolve(doc, st)
        he = [r for r in doc.of_kind(Reference) if r.annotations.get("word") == "he"][0]
        michael = [e for e in doc.of_kind(Entity) if e.label == "Michael"][0]
        ok = he.resolved == michael.id
        return ok, "he -> Michael probe " + ("passed" if ok else "FAILED")

    # ---- state lifecycle ------------------------------------------------------------------------------
    def new_state(self, conversation_id: str | None = None) -> ConversationState:
        return ConversationState(conversation_id or new_id())

    # ---- resolution ------------------------------------------------------------------------------------
    @traced("resolve")
    def resolve(self, doc: ACRDocument, state: ConversationState) -> ResolutionReport:
        report = ResolutionReport()
        mentions = self._mentions_in_order(doc)
        # co-argument map: reference id -> ids filling other roles of the same predicate
        coargs = self._coarguments(doc)
        for ref in [n for n in doc.nodes.values() if isinstance(n, Reference)]:
            if ref.status == "resolved":
                continue
            self._resolve_one(doc, state, ref, mentions, coargs, report)
        self._link_definites(doc, state, report)
        self._complete_ellipsis(doc, state, report)
        return report

    def _mentions_in_order(self, doc: ACRDocument) -> list[Entity | Concept]:
        ents = [n for n in doc.nodes.values() if isinstance(n, (Entity, Concept)) and not n.annotations.get("deixis")]
        ents.sort(key=lambda n: (n.annotations.get("surface", {}).get("s", 0), n.annotations.get("surface", {}).get("i", 0)))
        return ents

    def _coarguments(self, doc: ACRDocument) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for node in doc.nodes.values():
            slots: dict[str, str] = {}
            if isinstance(node, Event):
                slots = dict(node.roles)
            elif isinstance(node, Proposition):
                slots = dict(node.args)
            if not slots:
                continue
            ids = {v for v in slots.values() if v in doc.nodes}
            for rid in ids:
                out.setdefault(rid, set()).update(ids - {rid})
        return out

    def _slot_of(self, doc: ACRDocument, ref_id: str) -> tuple[Event | Proposition | None, str | None]:
        for node in doc.nodes.values():
            if isinstance(node, Event):
                for r, v in node.roles.items():
                    if v == ref_id:
                        return node, r
            elif isinstance(node, Proposition):
                for r, v in node.args.items():
                    if v == ref_id:
                        return node, r
        return None, None

    def _agrees(self, feats: dict, cand_feats: dict, cand_type: str) -> tuple[bool, float]:
        """Hard agreement filter + a graded score (unknown features are tolerated with a penalty)."""
        score = 1.0
        g = feats.get("gender")
        if g in ("m", "f"):
            cg = cand_feats.get("gender")
            if cg in ("m", "f") and cg != g:
                return False, 0.0
            if cg not in ("m", "f"):
                if cand_feats.get("animacy") == "inanimate":
                    return False, 0.0
                score *= 0.75 if cand_feats.get("animacy") == "animate" else 0.55
        if g == "n":
            if cand_feats.get("animacy") == "animate" and cand_type != "class.animal":
                return False, 0.0
        an = feats.get("animacy")
        can = cand_feats.get("animacy")
        if an == "animate" and can == "inanimate":
            return False, 0.0
        if an == "inanimate" and can == "animate" and cand_type != "class.animal":
            return False, 0.0
        n = feats.get("number")
        cn = cand_feats.get("number")
        if n and cn and n != cn:
            # singular "they" is possible; plural pronoun vs singular candidate is rejected otherwise
            if not (feats.get("word") == "they" and n == "pl"):
                return False, 0.0
        return True, score

    def _resolve_one(self, doc: ACRDocument, state: ConversationState, ref: Reference, mentions: list, coargs: dict, report: ResolutionReport) -> None:
        word = ref.annotations.get("word", "")
        feats = {**ref.features, "word": word}
        surface = ref.annotations.get("surface", {"s": 0, "i": 0})
        if ref.ref_type in ("ordinal", "demonstrative", "definite") and (ref.features.get("head") is not None or ref.features.get("deictic")) \
                and (ref.features.get("ordinal") is not None or state.options or ref.features.get("deictic")):
            if self._resolve_option(doc, state, ref, report):
                return
        if ref.ref_type == "ellipsis":
            self._resolve_ellipsis_noun(doc, state, ref, report)
            return
        event, role = self._slot_of(doc, ref.id)
        banned = set(coargs.get(ref.id, set())) if ref.ref_type != "reflexive" else set()
        required: set[str] = set()
        if ref.ref_type == "reflexive" and event is not None:
            required = {v for r, v in getattr(event, "roles", {}).items() if r in ("agent", "experiencer")} or set(coargs.get(ref.id, set()))
        animate_needed = False
        if isinstance(event, Event) and role and event.action and (info := concepts.get(event.action)) and role in info.animate_roles:
            animate_needed = True
        candidates: list[tuple[float, Any, dict]] = []
        # intra-utterance candidates: earlier in the surface order
        pos = (surface.get("s", 0), surface.get("i", 0))
        for node in mentions:
            sp = (node.annotations.get("surface", {}).get("s", 0), node.annotations.get("surface", {}).get("i", 0))
            if sp >= pos and not ref.annotations.get("cataphora_ok"):
                continue
            if node.id in banned or (required and node.id not in required):
                continue
            if isinstance(node, Concept):
                continue
            cfeats = {**node.features}
            ok, graded = self._agrees(feats, cfeats, node.entity_type)
            if not ok:
                continue
            if animate_needed and cfeats.get("animacy") == "inanimate":
                continue
            gram = node.annotations.get("surface", {}).get("gram")
            sentence_distance = pos[0] - sp[0]
            recency = 1.0 / (1 + sentence_distance) * (0.85 ** max(0, self._order_distance(mentions, node, ref, doc)))
            sal = ROLE_WEIGHT.get(gram or "pp", 1.0) * recency * graded
            candidates.append((sal * 2.0, node, {"source": "utterance", "gram": gram}))
        # conversation candidates
        for key, ce in state.entities.items():
            if ce.kind != "entity":
                continue
            ok, graded = self._agrees(feats, ce.features, ce.entity_type)
            if not ok or (animate_needed and ce.features.get("animacy") == "inanimate"):
                continue
            if any(isinstance(c[1], Entity) and c[1].label.lower() == ce.label.lower() for c in candidates):
                continue
            sal = ce.salience * graded
            if sal <= 0.02:
                continue
            candidates.append((sal, ce, {"source": "conversation", "key": key}))
        if not candidates:
            ref.status = "unresolved"
            report.unresolved.append({"ref": ref.id, "word": word, "reason": "no_antecedent_matching_agreement"})
            return
        candidates.sort(key=lambda c: -c[0])
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        ref.candidates = [{"ref": self._materialise(doc, c[1]), "score": round(c[0], 3), **c[2]} for c in candidates[:4]]
        margin = (top[0] - second[0]) / top[0] if second and top[0] > 0 else 1.0
        if second is not None and margin < 0.18:
            ref.status = "ambiguous"
            ref.confidence = round(max(0.2, 0.5 * (1 - (1 - margin))), 3)
            labels = [self._label(c[1]) for c in candidates[:3]]
            unc = Uncertainty(id=f"u_{ref.id}", subject=ref.id, uncertainty_type="ambiguity",
                              alternatives=[{"ref": c["ref"], "description": l, "weight": c["score"]} for c, l in zip(ref.candidates, labels)],
                              note=f"'{word}' could refer to {' or '.join(labels)}")
            doc.add(unc, root=False)
            report.ambiguous.append({"ref": ref.id, "word": word, "candidates": labels})
            return
        target_id = self._materialise(doc, top[1])
        ref.resolved, ref.status = target_id, "resolved"
        conf = min(0.99, 0.55 + 0.4 * margin) * (0.9 if top[2]["source"] == "conversation" else 1.0)
        ref.confidence = round(conf, 3)
        report.resolved.append({"ref": ref.id, "word": word, "target": self._label(top[1]), "target_id": target_id,
                                "source": top[2]["source"], "confidence": round(conf, 3)})

    @staticmethod
    def _order_distance(mentions: list, node: Any, ref: Reference, doc: ACRDocument) -> int:
        """Number of intervening mentions (nearer antecedents are preferred)."""
        sp = (ref.annotations.get("surface", {}).get("s", 0), ref.annotations.get("surface", {}).get("i", 0))
        later = [m for m in mentions if m is not node and (m.annotations.get("surface", {}).get("s", 0), m.annotations.get("surface", {}).get("i", 0)) <
                 sp and (m.annotations.get("surface", {}).get("s", 0), m.annotations.get("surface", {}).get("i", 0)) >
                 (node.annotations.get("surface", {}).get("s", 0), node.annotations.get("surface", {}).get("i", 0))]
        return len(later)

    @staticmethod
    def _label(c: Any) -> str:
        return c.label if hasattr(c, "label") and c.label else getattr(c, "key", "?")

    def _materialise(self, doc: ACRDocument, cand: Any) -> str:
        """Return the id of a doc node for the candidate, copying conversation entities into the document."""
        if isinstance(cand, (Entity, Concept)):
            return cand.id
        ce: ContextEntity = cand
        existing = next((e for e in doc.of_kind(Entity) if e.label.lower() == ce.label.lower() and e.annotations.get("context_key") == ce.key), None)
        if existing:
            return existing.id
        nid = f"ctx:{ce.key}"
        if nid in doc.nodes:
            return nid
        doc.add(Entity(id=nid, label=ce.label, entity_type=ce.entity_type, features=dict(ce.features),
                       annotations={"context_key": ce.key, "from_context": True},
                       provenance=[Provenance("system", method="context")]))
        return nid

    # ---- options ("that one", "the first option", "the previous one") ----------------------------------
    def _resolve_option(self, doc: ACRDocument, state: ConversationState, ref: Reference, report: ResolutionReport) -> bool:
        opts = state.options
        ordinal = ref.features.get("ordinal")
        if not opts:
            return False
        idx: int | None = None
        if ordinal is not None:
            if ordinal == -1:
                idx = len(opts) - 1
            elif ordinal == -2:  # "previous"
                idx = (state.option_focus - 1) if state.option_focus not in (None, 0) else (len(opts) - 2 if state.option_focus is None else None)
            elif ordinal == 2 and ref.annotations.get("word", "").startswith("the next"):
                idx = (state.option_focus + 1) if state.option_focus is not None and state.option_focus + 1 < len(opts) else None
            elif ordinal == 0:  # "the other one"
                if state.option_focus is not None and len(opts) == 2:
                    idx = 1 - state.option_focus
                elif len(opts) == 2:
                    idx = 1
            elif 1 <= ordinal <= len(opts):
                idx = ordinal - 1
        elif ref.features.get("deictic") and len(opts) >= 1:
            idx = state.option_focus if state.option_focus is not None else (len(opts) - 1 if ref.features.get("deictic") == "near" else None)
            if idx is None and len(opts) == 1:
                idx = 0
        if idx is None or not (0 <= idx < len(opts)):
            ref.status = "unresolved"
            report.unresolved.append({"ref": ref.id, "word": ref.annotations.get("word", ""), "reason": "option_not_available",
                                      "options": [o["label"] for o in opts]})
            return True
        opt = opts[idx]
        nid = f"opt:{idx}"
        if nid not in doc.nodes:
            ce = state.entities.get(opt["key"])
            doc.add(Entity(id=nid, label=opt["label"], entity_type=ce.entity_type if ce else "class.entity",
                           features=dict(ce.features) if ce else {}, annotations={"context_key": opt["key"], "from_context": True, "option_index": idx}))
        ref.resolved, ref.status, ref.confidence = nid, "resolved", 0.9
        state.option_focus = idx
        report.resolved.append({"ref": ref.id, "word": ref.annotations.get("word", ""), "target": opt["label"], "target_id": nid,
                                "source": "options", "confidence": 0.9})
        return True

    def _resolve_ellipsis_noun(self, doc: ACRDocument, state: ConversationState, ref: Reference, report: ResolutionReport) -> None:
        """'gives 2 to Anna': the elided head noun is the theme of the previous event (in-document)."""
        target = ref.annotations.get("elided_head_of")
        if target and target in doc.nodes:
            ref.resolved, ref.status, ref.confidence = target, "resolved", 0.8
            report.resolved.append({"ref": ref.id, "word": f"[{ref.annotations.get('quantity')}]", "target": self._label(doc.nodes[target]),
                                    "target_id": target, "source": "utterance", "confidence": 0.8})
        else:
            ref.status = "unresolved"
            report.unresolved.append({"ref": ref.id, "word": "[elided noun]", "reason": "no_head"})

    # ---- definite NPs ("the book") link to earlier entities ----------------------------------------------
    def _link_definites(self, doc: ACRDocument, state: ConversationState, report: ResolutionReport) -> None:
        for e in list(doc.of_kind(Entity)):
            if e.annotations.get("deixis") or e.annotations.get("from_context"):
                continue
            if e.features.get("definite") and e.features.get("lemma"):
                ce = state.entities.get(e.features["lemma"])
                if ce and ce.last_turn < state.turn + 1:
                    e.annotations["context_key"] = ce.key
                    report.linked_definites.append({"node": e.id, "label": e.label, "context_key": ce.key})

    # ---- ellipsis completion -------------------------------------------------------------------------------
    def _complete_ellipsis(self, doc: ACRDocument, state: ConversationState, report: ResolutionReport) -> None:
        frag_intentions = [i for i in doc.of_kind(Intention) if i.features.get("question_kind") == "ellipsis"]
        if not frag_intentions or not state.last_question:
            return
        prev = ACRDocument.from_dict(state.last_question["doc"])
        for it in frag_intentions:
            if not it.content:
                continue
            frag_id = it.content[0]
            frag = doc.resolve(frag_id) or doc.nodes.get(frag_id)
            if frag is None:
                continue
            prev_it = next((i for i in prev.of_kind(Intention) if i.act in ("request_information", "request_confirmation")), None)
            if prev_it is None or not prev_it.content:
                continue
            slot_nodes = self._substitutable(prev, prev_it)
            ftype = getattr(frag, "entity_type", "class.entity")
            compatible = [(n, owner, role) for (n, owner, role) in slot_nodes if self._compatible(n, frag)]
            if not compatible:
                report.ellipsis = {"status": "unresolved", "reason": "no_compatible_slot"}
                continue
            # replace the last-mentioned compatible entity (surface order), keeping the question's structure
            compatible.sort(key=lambda t: (t[0].annotations.get("surface", {}).get("s", 0), t[0].annotations.get("surface", {}).get("i", 0)))
            target, owner, role = compatible[-1]
            mapping = doc.merge(prev, prefix="q:")
            owner_new = doc.nodes[mapping[owner.id]]
            if isinstance(owner_new, Event):
                owner_new.roles[role] = frag.id
            else:
                owner_new.args[role] = frag.id  # type: ignore[attr-defined]
            new_intent = doc.nodes[mapping[prev_it.id]]
            new_intent.features = {**new_intent.features, "completed_from_ellipsis": True, "replaced": getattr(target, "label", "?"), "with": getattr(frag, "label", "?")}
            doc.roots = [r for r in doc.roots if r != it.id] + [new_intent.id]
            report.ellipsis = {"status": "completed", "replaced": getattr(target, "label", "?"), "with": getattr(frag, "label", "?"),
                               "role": role, "confidence": 0.6}

    @staticmethod
    def _substitutable(prev: ACRDocument, intent: Intention) -> list[tuple[Any, Any, str]]:
        out = []
        for cid in intent.content:
            node = prev.nodes.get(cid)
            nodes = [node] if node is not None else []
            if isinstance(node, Logical):
                nodes = [prev.nodes[o] for o in node.operands if o in prev.nodes]
            for n in nodes:
                slots = n.roles if isinstance(n, Event) else n.args if isinstance(n, Proposition) else {}
                for role, vid in slots.items():
                    target = prev.resolve(vid)
                    if isinstance(target, Entity) and not target.annotations.get("deixis") and role not in ("dimension",):
                        out.append((target, n, role))
        return out

    @staticmethod
    def _compatible(old: Entity, new: Any) -> bool:
        if not isinstance(new, Entity):
            return False
        if new.entity_type == old.entity_type:
            return True
        return "class.entity" in (new.entity_type, old.entity_type) or old.features.get("animacy") == new.features.get("animacy")

    # ---- state update ------------------------------------------------------------------------------------------
    @traced("update")
    def update(self, state: ConversationState, doc: ACRDocument, *, user_text: str, system_text: str | None = None,
               options: list[dict] | None = None, unresolved: dict | None = None, answered: bool = False,
               clarification: dict | None = None) -> None:
        state.turn += 1
        for ce in state.entities.values():
            ce.salience *= DECAY
        seen: set[str] = set()
        for node in doc.nodes.values():
            target = doc.resolve(node.id) if isinstance(node, Reference) else node
            if not isinstance(target, (Entity, Concept)) or target.annotations.get("deixis"):
                continue
            if isinstance(node, Reference) and node.status != "resolved":
                continue
            if isinstance(target, Entity) and target.annotations.get("from_context"):
                key = target.annotations.get("context_key") or target.label.lower()
            else:
                key = _entity_key(target) if isinstance(target, Entity) else target.concept_id
            gram = (node.annotations.get("surface", {}) or target.annotations.get("surface", {})).get("gram")
            weight = ROLE_WEIGHT.get(gram or "pp", 1.0)
            ce = state.entities.get(key)
            if ce is None:
                label = target.label if isinstance(target, Entity) else (target.label or target.concept_id)
                ce = ContextEntity(key=key, label=label or key, entity_type=getattr(target, "entity_type", "class.abstract"),
                                   features={k: v for k, v in (target.features if isinstance(target, Entity) else {}).items()
                                             if k in ("gender", "number", "animacy", "lemma", "definite")},
                                   first_turn=state.turn, kind="entity" if isinstance(target, Entity) else "concept")
                state.entities[key] = ce
            elif isinstance(target, Entity):
                for k in ("gender", "animacy"):   # learn features the first mention did not have
                    if target.features.get(k) and not ce.features.get(k):
                        ce.features[k] = target.features[k]
            if key not in seen:
                ce.salience += weight
                ce.mentions += 1
                ce.last_turn = state.turn
                seen.add(key)
        if len(state.entities) > MAX_ENTITIES:
            keep = sorted(state.entities.values(), key=lambda e: -e.salience)[:MAX_ENTITIES]
            state.entities = {e.key: e for e in keep}
        # options from coordinated NPs in the user's text, or supplied by the response engine
        user_opts = self._options_from_doc(doc)
        new_opts = options or user_opts
        if new_opts:
            state.options = new_opts
            state.option_focus = None
        # topic
        top = sorted(state.entities.values(), key=lambda e: -e.salience)[:3]
        dims = [n.concept_id for n in doc.of_kind(Concept) if n.concept_id.startswith("dim.")]
        state.topic = {"entities": [e.label for e in top if e.salience > 0.2], "dimension": dims[0] if dims else state.topic.get("dimension"),
                       "turn": state.turn}
        # questions
        asked = [i for i in doc.of_kind(Intention) if i.act in ("request_information", "request_confirmation") and not i.features.get("completed_from_ellipsis") is None or False]
        for it in doc.of_kind(Intention):
            if it.act in ("request_information", "request_confirmation") and it.features.get("question_kind") != "ellipsis":
                state.last_question = {"doc": doc.subgraph([it.id] + list(it.content)).to_dict(), "turn": state.turn}
            elif it.features.get("completed_from_ellipsis"):
                state.last_question = {"doc": doc.subgraph([it.id] + list(it.content)).to_dict(), "turn": state.turn}
        if unresolved:
            state.unresolved_questions.append({**unresolved, "turn": state.turn})
        if answered:
            state.unresolved_questions = [q for q in state.unresolved_questions if q.get("turn", 0) < state.turn - 1][-5:]
        state.pending_clarification = clarification
        state.history.append({"turn": state.turn, "role": "user", "text": user_text})
        if system_text is not None:
            state.history.append({"turn": state.turn, "role": "system", "text": system_text})
        state.history = state.history[-MAX_TURNS_KEPT:]

    @staticmethod
    def _options_from_doc(doc: ACRDocument) -> list[dict]:
        out: list[dict] = []
        for lg in doc.of_kind(Logical):
            if lg.op in ("or", "and") and len(lg.operands) >= 2:
                items = []
                for o in lg.operands:
                    n = doc.nodes.get(o)
                    if isinstance(n, Entity) and not n.annotations.get("deixis"):
                        items.append({"key": _entity_key(n), "label": n.label})
                if len(items) >= 2:
                    return items
        return out

    def describe(self, state: ConversationState) -> dict:
        ents = sorted(state.entities.values(), key=lambda e: -e.salience)
        return {"conversation_id": state.conversation_id, "turn": state.turn, "topic": state.topic,
                "active_entities": [{"label": e.label, "salience": round(e.salience, 3), "last_turn": e.last_turn, "type": e.entity_type,
                                     "features": e.features} for e in ents[:12]],
                "options": state.options, "option_focus": state.option_focus, "unresolved_questions": state.unresolved_questions,
                "pending_clarification": state.pending_clarification, "history_length": len(state.history)}
