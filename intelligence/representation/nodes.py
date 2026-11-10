"""ACR node types.

ACR (AVOENIX Cognitive Representation) is a typed, composable structure. It is *not* a
bare node/edge graph: each node kind has its own semantics, validation rules and role
vocabulary, and nodes compose by reference (an Event's purpose may be another Event, a
Condition's consequent may be a Logical formula over Propositions, and so on).

Language independence: nodes carry language-neutral concept identifiers (``act.give``,
``rel.exceeds``, ``dim.age``). Surface information (spans, wording) is confined to the
``annotations["surface"]`` slot so that language-specific processing never leaks into the
cognitive layer.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from typing import Any, Callable, ClassVar, Iterator

Ref = str

SOURCE_TYPES = (
    "user_statement",      # asserted by an end user (unverified)
    "external_verified",   # imported from a source that was independently verified
    "seed_curated",        # shipped with AVOENIX, authored by the project, not independently verified
    "derived",             # concluded by AVOENIX's own reasoning
    "learned",             # accepted through the Learning Engine's approval workflow
    "system",              # produced by AVOENIX itself (introspection, configuration)
)

POLARITIES = ("positive", "negative")
MODALITIES = ("actual", "possible", "obligatory", "desired", "hypothetical", "counterfactual", "queried")
TENSES = ("past", "present", "future", "timeless")


@dataclass
class Provenance:
    source_type: str
    source_id: str | None = None
    method: str | None = None
    timestamp: str | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "method": self.method,
            "timestamp": self.timestamp,
            "detail": copy.deepcopy(self.detail),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Provenance":
        return cls(
            source_type=data.get("source_type", "system"),
            source_id=data.get("source_id"),
            method=data.get("method"),
            timestamp=data.get("timestamp"),
            detail=dict(data.get("detail") or {}),
        )


# Reference field kinds used by the generic traversal helpers.
#   one   -> Optional[str]
#   list  -> list[str]
#   dict  -> dict[str, str]
#   cands -> list[dict] where each dict may hold a "ref" key
_REF_KINDS = ("one", "list", "dict", "cands")


@dataclass(kw_only=True)
class Node:
    id: str
    confidence: float = 1.0
    provenance: list[Provenance] = field(default_factory=list)
    annotations: dict[str, Any] = field(default_factory=dict)

    KIND: ClassVar[str] = "node"
    REFS: ClassVar[dict[str, str]] = {}

    # ---- reference traversal -------------------------------------------------
    def iter_refs(self) -> Iterator[Ref]:
        for name, kind in self.REFS.items():
            value = getattr(self, name)
            if value is None:
                continue
            if kind == "one":
                yield value
            elif kind == "list":
                yield from value
            elif kind == "dict":
                yield from value.values()
            elif kind == "cands":
                for item in value:
                    ref = item.get("ref") if isinstance(item, dict) else None
                    if ref:
                        yield ref

    def map_refs(self, fn: Callable[[Ref], Ref]) -> None:
        """Rewrite every reference in place (used by merge/remap)."""
        for name, kind in self.REFS.items():
            value = getattr(self, name)
            if value is None:
                continue
            if kind == "one":
                setattr(self, name, fn(value))
            elif kind == "list":
                setattr(self, name, [fn(v) for v in value])
            elif kind == "dict":
                setattr(self, name, {k: fn(v) for k, v in value.items()})
            elif kind == "cands":
                for item in value:
                    if isinstance(item, dict) and item.get("ref"):
                        item["ref"] = fn(item["ref"])

    # ---- serialisation -------------------------------------------------------
    def to_dict(self) -> dict:
        out: dict[str, Any] = {"kind": self.KIND}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "provenance":
                out["provenance"] = [p.to_dict() for p in value]
            else:
                out[f.name] = copy.deepcopy(value)
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Node":
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        extras: dict[str, Any] = {}
        for key, value in data.items():
            if key == "kind":
                continue
            if key == "provenance":
                kwargs["provenance"] = [Provenance.from_dict(p) for p in (value or [])]
            elif key in known:
                kwargs[key] = copy.deepcopy(value)
            else:
                extras[key] = copy.deepcopy(value)
        node = cls(**kwargs)
        if extras:  # forward compatibility: keep unknown fields instead of dropping data
            node.annotations.setdefault("_unknown_fields", {}).update(extras)
        return node


# ----------------------------------------------------------------------------------------
# Referents
# ----------------------------------------------------------------------------------------
@dataclass(kw_only=True)
class Entity(Node):
    """A particular individual (person, object, place, organisation...)."""

    label: str
    entity_type: str = "class.entity"
    features: dict[str, Any] = field(default_factory=dict)   # gender, number, animacy ...
    aliases: list[str] = field(default_factory=list)
    KIND: ClassVar[str] = "entity"


@dataclass(kw_only=True)
class Concept(Node):
    """A general kind/notion (as opposed to an individual): 'dogs', 'books', 'age'."""

    concept_id: str
    label: str | None = None
    KIND: ClassVar[str] = "concept"


@dataclass(kw_only=True)
class Literal(Node):
    value: Any
    datatype: str = "string"      # string | number | boolean
    KIND: ClassVar[str] = "literal"


@dataclass(kw_only=True)
class Quantity(Node):
    value: float
    unit: str | None = None
    dimension: str | None = None
    approximate: bool = False
    KIND: ClassVar[str] = "quantity"


@dataclass(kw_only=True)
class TimeRef(Node):
    """Time information. Absolute values are ISO-8601; relative ones carry an offset
    from an anchor (normally the utterance time) so the same structure stays valid when
    stored and re-interpreted later."""

    time_kind: str = "unspecified"   # instant | interval | relative | duration | recurrent | unspecified
    value: str | None = None         # ISO date/time for absolute references
    start: str | None = None
    end: str | None = None
    granularity: str | None = None   # second|minute|hour|day|week|month|year|part_of_day
    anchor: str | None = None        # e.g. "utterance_time"
    offset: dict[str, float] | None = None   # {"days": -1}
    anchor_relation: str | None = None       # before | at | after
    KIND: ClassVar[str] = "time"


# ----------------------------------------------------------------------------------------
# Happenings and states
# ----------------------------------------------------------------------------------------
@dataclass(kw_only=True)
class Event(Node):
    """Something that happens or is done, with participant roles and circumstances."""

    action: str                                   # language-neutral id, e.g. "act.give"
    roles: dict[str, Ref] = field(default_factory=dict)
    time: Ref | None = None
    location: Ref | None = None
    purpose: Ref | None = None
    conditions: list[Ref] = field(default_factory=list)
    tense: str | None = None
    aspect: str | None = None
    polarity: str = "positive"
    modality: str = "actual"
    KIND: ClassVar[str] = "event"
    REFS: ClassVar[dict[str, str]] = {
        "roles": "dict", "time": "one", "location": "one", "purpose": "one", "conditions": "list",
    }


@dataclass(kw_only=True)
class Proposition(Node):
    """A state, relation or property: ``rel.is_a(subject, object)``, ``rel.exceeds(greater, lesser)``..."""

    predicate: str
    args: dict[str, Ref] = field(default_factory=dict)
    polarity: str = "positive"
    quantifier: str | None = None     # None (particular) | all | some | no | most
    modality: str = "actual"
    time: Ref | None = None
    KIND: ClassVar[str] = "proposition"
    REFS: ClassVar[dict[str, str]] = {"args": "dict", "time": "one"}


@dataclass(kw_only=True)
class Link(Node):
    """Typed relation between two structures: cause, purpose, temporal order, explanation..."""

    link_type: str                    # cause | purpose | before | after | during | explains | contrast | elaboration | condition
    source: Ref
    target: Ref
    KIND: ClassVar[str] = "link"
    REFS: ClassVar[dict[str, str]] = {"source": "one", "target": "one"}


@dataclass(kw_only=True)
class Condition(Node):
    antecedent: Ref
    consequent: Ref
    strength: str = "strict"          # strict | default
    KIND: ClassVar[str] = "condition"
    REFS: ClassVar[dict[str, str]] = {"antecedent": "one", "consequent": "one"}


@dataclass(kw_only=True)
class Logical(Node):
    op: str                           # and | or | not | implies | iff
    operands: list[Ref] = field(default_factory=list)
    KIND: ClassVar[str] = "logical"
    REFS: ClassVar[dict[str, str]] = {"operands": "list"}


@dataclass(kw_only=True)
class Expression(Node):
    """Arithmetic expression over quantities/expressions."""

    op: str                           # add | sub | mul | div | pow | neg | percent_of | sqrt
    operands: list[Ref] = field(default_factory=list)
    KIND: ClassVar[str] = "expression"
    REFS: ClassVar[dict[str, str]] = {"operands": "list"}


# ----------------------------------------------------------------------------------------
# Mental / pragmatic structure
# ----------------------------------------------------------------------------------------
@dataclass(kw_only=True)
class Goal(Node):
    title: str = ""
    content: Ref | None = None        # the target state/event, when representable
    owner: Ref | None = None
    priority: int = 3                 # 1 (highest) .. 5
    status: str = "open"              # open | active | blocked | done | dropped
    depends_on: list[Ref] = field(default_factory=list)
    parent: Ref | None = None
    progress: float = 0.0
    KIND: ClassVar[str] = "goal"
    REFS: ClassVar[dict[str, str]] = {"content": "one", "owner": "one", "depends_on": "list", "parent": "one"}


@dataclass(kw_only=True)
class Intention(Node):
    """What an agent is trying to achieve; also the representation of a speaker's act."""

    act: str                          # assert | request_information | request_action | greet | thank | ...
    agent: Ref | None = None
    content: list[Ref] = field(default_factory=list)
    addressee: Ref | None = None
    features: dict[str, Any] = field(default_factory=dict)
    KIND: ClassVar[str] = "intention"
    REFS: ClassVar[dict[str, str]] = {"agent": "one", "content": "list", "addressee": "one"}


@dataclass(kw_only=True)
class Reference(Node):
    """Contextual reference ('he', 'it', 'that one', 'the previous option')."""

    ref_type: str                     # pronoun | demonstrative | definite | ordinal | ellipsis
    features: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)   # [{"ref": id, "score": float}]
    resolved: Ref | None = None
    status: str = "unresolved"        # resolved | ambiguous | unresolved
    KIND: ClassVar[str] = "reference"
    REFS: ClassVar[dict[str, str]] = {"candidates": "cands", "resolved": "one"}


@dataclass(kw_only=True)
class Variable(Node):
    """Unknown to be solved for (a question's focus)."""

    name: str
    constraints: dict[str, Any] = field(default_factory=dict)
    KIND: ClassVar[str] = "variable"


# ----------------------------------------------------------------------------------------
# Epistemic structure
# ----------------------------------------------------------------------------------------
@dataclass(kw_only=True)
class Uncertainty(Node):
    subject: Ref | None = None
    uncertainty_type: str = "ambiguity"   # ambiguity | epistemic | vagueness | underdetermined
    alternatives: list[dict[str, Any]] = field(default_factory=list)   # [{"ref": id?, "description": str, "weight": float}]
    note: str | None = None
    KIND: ClassVar[str] = "uncertainty"
    REFS: ClassVar[dict[str, str]] = {"subject": "one", "alternatives": "cands"}


@dataclass(kw_only=True)
class Contradiction(Node):
    items: list[Ref] = field(default_factory=list)
    reason: str = ""
    detected_by: str | None = None
    KIND: ClassVar[str] = "contradiction"
    REFS: ClassVar[dict[str, str]] = {"items": "list"}


@dataclass(kw_only=True)
class Unknown(Node):
    about_ref: Ref | None = None
    about_text: str | None = None
    reason: str = "not_stated"        # not_stated | not_in_knowledge | unresolved_reference | unsupported
    needed: str | None = None
    KIND: ClassVar[str] = "unknown"
    REFS: ClassVar[dict[str, str]] = {"about_ref": "one"}


@dataclass(kw_only=True)
class RawNode(Node):
    """Preserves a node of a kind this version does not know (safe schema evolution)."""

    raw_kind: str = "unknown"
    data: dict[str, Any] = field(default_factory=dict)
    KIND: ClassVar[str] = "raw"


NODE_KINDS: dict[str, type[Node]] = {
    cls.KIND: cls
    for cls in (
        Entity, Concept, Literal, Quantity, TimeRef, Event, Proposition, Link, Condition,
        Logical, Expression, Goal, Intention, Reference, Variable, Uncertainty,
        Contradiction, Unknown, RawNode,
    )
}


def node_from_dict(data: dict, *, strict: bool = True) -> Node:
    from .errors import RepresentationError  # local import avoids cycles

    kind = data.get("kind")
    cls = NODE_KINDS.get(kind) if isinstance(kind, str) else None
    if cls is None:
        if strict:
            raise RepresentationError(f"unknown node kind: {kind!r}", details={"kind": kind})
        return RawNode(
            id=str(data.get("id", "")),
            raw_kind=str(kind),
            data={k: v for k, v in data.items() if k not in ("id", "kind")},
        )
    return cls.from_dict(data)
