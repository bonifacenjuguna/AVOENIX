"""Fluent construction of ACR documents with deterministic local ids."""

from __future__ import annotations

from typing import Any

from ..core.types import new_id
from .document import ACRDocument
from .nodes import (
    Concept, Condition, Contradiction, Entity, Event, Expression, Goal, Intention, Link,
    Literal, Logical, Node, Proposition, Provenance, Quantity, Reference, TimeRef,
    Uncertainty, Unknown, Variable,
)


class ACRBuilder:
    """Creates nodes with sequential local ids (``n1``, ``n2``...) inside one document."""

    def __init__(self, doc: ACRDocument | None = None, *, default_provenance: Provenance | None = None,
                 doc_id: str | None = None):
        self.doc = doc or ACRDocument(doc_id or new_id())
        self.default_provenance = default_provenance
        self._counter = len(self.doc.nodes)

    def _next(self) -> str:
        while True:
            self._counter += 1
            nid = f"n{self._counter}"
            if nid not in self.doc.nodes:
                return nid

    def _add(self, node: Node, root: bool) -> str:
        if not node.provenance and self.default_provenance is not None:
            node.provenance = [Provenance(**self.default_provenance.to_dict())]
        return self.doc.add(node, root=root)

    # Each helper returns the new node id so structures compose by reference.
    def entity(self, label: str, entity_type: str = "class.entity", *, features: dict | None = None,
               aliases: list[str] | None = None, confidence: float = 1.0, root: bool = False,
               annotations: dict | None = None) -> str:
        return self._add(Entity(id=self._next(), label=label, entity_type=entity_type,
                                features=dict(features or {}), aliases=list(aliases or []),
                                confidence=confidence, annotations=dict(annotations or {})), root)

    def concept(self, concept_id: str, label: str | None = None, *, annotations: dict | None = None) -> str:
        return self._add(Concept(id=self._next(), concept_id=concept_id, label=label,
                                 annotations=dict(annotations or {})), False)

    def literal(self, value: Any, datatype: str | None = None) -> str:
        if datatype is None:
            datatype = "boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "string"
        return self._add(Literal(id=self._next(), value=value, datatype=datatype), False)

    def quantity(self, value: float, unit: str | None = None, dimension: str | None = None, *,
                 approximate: bool = False, confidence: float = 1.0, annotations: dict | None = None) -> str:
        return self._add(Quantity(id=self._next(), value=value, unit=unit, dimension=dimension,
                                  approximate=approximate, confidence=confidence,
                                  annotations=dict(annotations or {})), False)

    def time(self, time_kind: str = "unspecified", **kwargs: Any) -> str:
        annotations = kwargs.pop("annotations", None) or {}
        return self._add(TimeRef(id=self._next(), time_kind=time_kind, annotations=dict(annotations), **kwargs), False)

    def event(self, action: str, roles: dict[str, str] | None = None, *, root: bool = False,
              confidence: float = 1.0, annotations: dict | None = None, **kwargs: Any) -> str:
        return self._add(Event(id=self._next(), action=action, roles=dict(roles or {}),
                               confidence=confidence, annotations=dict(annotations or {}), **kwargs), root)

    def proposition(self, predicate: str, args: dict[str, str] | None = None, *, root: bool = False,
                    confidence: float = 1.0, annotations: dict | None = None, **kwargs: Any) -> str:
        return self._add(Proposition(id=self._next(), predicate=predicate, args=dict(args or {}),
                                     confidence=confidence, annotations=dict(annotations or {}), **kwargs), root)

    def link(self, link_type: str, source: str, target: str, *, root: bool = False, confidence: float = 1.0,
             annotations: dict | None = None) -> str:
        return self._add(Link(id=self._next(), link_type=link_type, source=source, target=target,
                              confidence=confidence, annotations=dict(annotations or {})), root)

    def condition(self, antecedent: str, consequent: str, *, root: bool = False, strength: str = "strict",
                  confidence: float = 1.0) -> str:
        return self._add(Condition(id=self._next(), antecedent=antecedent, consequent=consequent,
                                   strength=strength, confidence=confidence), root)

    def logical(self, op: str, operands: list[str], *, root: bool = False) -> str:
        return self._add(Logical(id=self._next(), op=op, operands=list(operands)), root)

    def expression(self, op: str, operands: list[str], *, root: bool = False) -> str:
        return self._add(Expression(id=self._next(), op=op, operands=list(operands)), root)

    def goal(self, title: str, *, root: bool = False, **kwargs: Any) -> str:
        return self._add(Goal(id=self._next(), title=title, **kwargs), root)

    def intention(self, act: str, *, agent: str | None = None, content: list[str] | None = None,
                  addressee: str | None = None, features: dict | None = None, root: bool = False,
                  confidence: float = 1.0, annotations: dict | None = None) -> str:
        return self._add(Intention(id=self._next(), act=act, agent=agent, content=list(content or []),
                                   addressee=addressee, features=dict(features or {}),
                                   confidence=confidence, annotations=dict(annotations or {})), root)

    def reference(self, ref_type: str, *, features: dict | None = None, candidates: list[dict] | None = None,
                  resolved: str | None = None, status: str | None = None, confidence: float = 1.0,
                  annotations: dict | None = None) -> str:
        if status is None:
            status = "resolved" if resolved else ("ambiguous" if candidates and len(candidates) > 1 else "unresolved")
        return self._add(Reference(id=self._next(), ref_type=ref_type, features=dict(features or {}),
                                   candidates=[dict(c) for c in (candidates or [])], resolved=resolved,
                                   status=status, confidence=confidence,
                                   annotations=dict(annotations or {})), False)

    def variable(self, name: str, **constraints: Any) -> str:
        return self._add(Variable(id=self._next(), name=name, constraints=dict(constraints)), False)

    def uncertainty(self, subject: str | None, uncertainty_type: str = "ambiguity",
                    alternatives: list[dict] | None = None, note: str | None = None, *, root: bool = False) -> str:
        return self._add(Uncertainty(id=self._next(), subject=subject, uncertainty_type=uncertainty_type,
                                     alternatives=[dict(a) for a in (alternatives or [])], note=note), root)

    def contradiction(self, items: list[str], reason: str, detected_by: str | None = None, *, root: bool = False) -> str:
        return self._add(Contradiction(id=self._next(), items=list(items), reason=reason, detected_by=detected_by), root)

    def unknown(self, *, about_ref: str | None = None, about_text: str | None = None,
                reason: str = "not_stated", needed: str | None = None, root: bool = False) -> str:
        return self._add(Unknown(id=self._next(), about_ref=about_ref, about_text=about_text,
                                 reason=reason, needed=needed), root)

    def build(self) -> ACRDocument:
        return self.doc
