"""ACRDocument: a container of composable ACR nodes with validation and serialisation."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator, TypeVar

from ..core.errors import RepresentationError
from ..core.types import new_id
from ..version import ACR_SCHEMA_VERSION
from . import concepts
from .nodes import (
    MODALITIES, POLARITIES, Condition, Contradiction, Event, Goal, Node, Proposition,
    Provenance, Quantity, Reference, SOURCE_TYPES, Variable, node_from_dict,
)

N = TypeVar("N", bound=Node)
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_STRUCTURAL = (Event, Proposition, Condition)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings)}


class ACRDocument:
    """A bag of typed nodes with named roots. Nodes reference each other by id."""

    def __init__(self, doc_id: str | None = None, *, meta: dict | None = None,
                 schema_version: str = ACR_SCHEMA_VERSION):
        self.id = doc_id or new_id()
        self.schema_version = schema_version
        self.nodes: dict[str, Node] = {}
        self.roots: list[str] = []
        self.meta: dict = dict(meta or {})

    # ---- access ----------------------------------------------------------------------
    def add(self, node: Node, *, root: bool = False) -> str:
        if not node.id:
            raise RepresentationError("node id must be non-empty")
        if node.id in self.nodes:
            raise RepresentationError(f"duplicate node id {node.id!r}")
        self.nodes[node.id] = node
        if root:
            self.roots.append(node.id)
        return node.id

    def get(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise RepresentationError(f"unknown node id {node_id!r}") from None

    def maybe(self, node_id: str | None) -> Node | None:
        return self.nodes.get(node_id) if node_id else None

    def has(self, node_id: str) -> bool:
        return node_id in self.nodes

    def of_kind(self, cls: type[N]) -> Iterator[N]:
        for node in self.nodes.values():
            if isinstance(node, cls):
                yield node

    def __len__(self) -> int:
        return len(self.nodes)

    def resolve(self, node_id: str | None) -> Node | None:
        """Follow resolved References to the node they stand for."""
        seen = set()
        node = self.maybe(node_id)
        while isinstance(node, Reference) and node.resolved and node.id not in seen:
            seen.add(node.id)
            node = self.maybe(node.resolved)
        return node

    def resolve_id(self, node_id: str | None) -> str | None:
        node = self.resolve(node_id)
        return node.id if node else node_id

    # ---- composition -----------------------------------------------------------------
    def merge(self, other: "ACRDocument", *, prefix: str | None = None) -> dict[str, str]:
        """Copy ``other`` into this document. Returns the old->new id map.

        Ids are prefixed (default: first 6 chars of the other doc id) to avoid clashes, and
        every internal reference is rewritten consistently.
        """
        prefix = prefix if prefix is not None else f"{other.id[:6]}:"
        mapping = {nid: f"{prefix}{nid}" for nid in other.nodes}
        for nid, node in other.nodes.items():
            clone = copy.deepcopy(node)
            clone.id = mapping[nid]
            clone.map_refs(lambda r: mapping.get(r, r))
            self.add(clone)
        for root in other.roots:
            if mapping[root] not in self.roots:
                self.roots.append(mapping[root])
        return mapping

    def subgraph(self, ids: Iterable[str]) -> "ACRDocument":
        """New document containing ``ids`` and everything they transitively reference."""
        out = ACRDocument(meta=dict(self.meta))
        todo = list(ids)
        seen: set[str] = set()
        while todo:
            nid = todo.pop()
            if nid in seen or nid not in self.nodes:
                continue
            seen.add(nid)
            todo.extend(self.nodes[nid].iter_refs())
        for nid in self.nodes:  # keep insertion order
            if nid in seen:
                out.add(copy.deepcopy(self.nodes[nid]))
        out.roots = [r for r in self.roots if r in seen]
        return out

    def clone(self) -> "ACRDocument":
        return ACRDocument.from_dict(self.to_dict())

    # ---- serialisation ---------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "meta": copy.deepcopy(self.meta),
            "roots": list(self.roots),
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }

    @classmethod
    def from_dict(cls, data: dict, *, strict: bool = True) -> "ACRDocument":
        if not isinstance(data, dict) or "nodes" not in data:
            raise RepresentationError("not an ACR document (missing 'nodes')")
        doc = cls(data.get("id"), meta=data.get("meta"), schema_version=data.get("schema_version", ACR_SCHEMA_VERSION))
        for raw in data["nodes"]:
            doc.add(node_from_dict(raw, strict=strict))
        doc.roots = list(data.get("roots", []))
        return doc

    # ---- validation ------------------------------------------------------------------
    def validate(self, *, strict: bool = False) -> ValidationReport:
        rep = ValidationReport()
        for nid, node in self.nodes.items():
            where = f"{node.KIND}:{nid}"
            if not 0.0 <= float(node.confidence) <= 1.0:
                rep.errors.append(f"{where}: confidence {node.confidence} outside [0,1]")
            for prov in node.provenance:
                if prov.source_type not in SOURCE_TYPES:
                    rep.errors.append(f"{where}: unknown provenance source_type {prov.source_type!r}")
            for ref in node.iter_refs():
                if ref not in self.nodes:
                    rep.errors.append(f"{where}: dangling reference to {ref!r}")
            if isinstance(node, Event):
                if not node.action:
                    rep.errors.append(f"{where}: event without action")
                self._check_polarity(rep, where, node.polarity, node.modality)
                for role in node.roles:
                    if not _ROLE_RE.match(role):
                        rep.errors.append(f"{where}: malformed role name {role!r}")
                    elif role not in concepts.EVENT_ROLES:
                        rep.warnings.append(f"{where}: non-standard role {role!r}")
                info = concepts.get(node.action)
                if info and info.animate_roles:
                    for role in info.animate_roles:
                        filler = self.resolve(node.roles.get(role)) if role in node.roles else None
                        if filler is not None and hasattr(filler, "features"):
                            if filler.features.get("animacy") == "inanimate":
                                rep.warnings.append(f"{where}: role {role!r} of {node.action} filled by an inanimate referent")
            elif isinstance(node, Proposition):
                if not node.predicate:
                    rep.errors.append(f"{where}: proposition without predicate")
                self._check_polarity(rep, where, node.polarity, node.modality)
                for role in node.args:
                    if not _ROLE_RE.match(role):
                        rep.errors.append(f"{where}: malformed arg name {role!r}")
                if node.quantifier not in (None, "all", "some", "no", "most", "few"):
                    rep.errors.append(f"{where}: unknown quantifier {node.quantifier!r}")
            elif isinstance(node, Contradiction):
                if len(node.items) < 2:
                    rep.errors.append(f"{where}: a contradiction needs at least two items")
            elif isinstance(node, Goal):
                if not 1 <= node.priority <= 5:
                    rep.errors.append(f"{where}: priority must be 1..5")
                if not 0.0 <= node.progress <= 1.0:
                    rep.errors.append(f"{where}: progress outside [0,1]")
                if node.status not in ("open", "active", "blocked", "done", "dropped"):
                    rep.errors.append(f"{where}: bad goal status {node.status!r}")
            elif isinstance(node, Quantity):
                if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                    rep.errors.append(f"{where}: quantity value must be numeric")
            elif isinstance(node, Reference):
                if node.status not in ("resolved", "ambiguous", "unresolved"):
                    rep.errors.append(f"{where}: bad reference status {node.status!r}")
                if node.status == "resolved" and not node.resolved:
                    rep.errors.append(f"{where}: resolved reference without target")
            elif isinstance(node, Variable) and not node.name:
                rep.errors.append(f"{where}: variable needs a name")
        for root in self.roots:
            if root not in self.nodes:
                rep.errors.append(f"root {root!r} not in document")
        cycle = self._find_structural_cycle()
        if cycle:
            rep.errors.append("structural cycle: " + " -> ".join(cycle))
        if strict and rep.errors:
            raise RepresentationError("ACR validation failed", details={"errors": rep.errors})
        return rep

    @staticmethod
    def _check_polarity(rep: ValidationReport, where: str, polarity: str, modality: str) -> None:
        if polarity not in POLARITIES:
            rep.errors.append(f"{where}: bad polarity {polarity!r}")
        if modality not in MODALITIES:
            rep.errors.append(f"{where}: bad modality {modality!r}")

    def _find_structural_cycle(self) -> list[str] | None:
        """Events/Propositions/Conditions may nest, but never contain themselves."""
        WHITE, GREY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}
        stack: list[str] = []

        def visit(nid: str) -> list[str] | None:
            color[nid] = GREY
            stack.append(nid)
            node = self.nodes[nid]
            if isinstance(node, _STRUCTURAL) or node.KIND in ("logical", "expression"):
                for ref in node.iter_refs():
                    target = self.nodes.get(ref)
                    if target is None or not (isinstance(target, _STRUCTURAL) or target.KIND in ("logical", "expression")):
                        continue
                    if color[ref] == GREY:
                        return stack[stack.index(ref):] + [ref]
                    if color[ref] == WHITE:
                        found = visit(ref)
                        if found:
                            return found
            stack.pop()
            color[nid] = BLACK
            return None

        for nid in list(self.nodes):
            if color[nid] == WHITE:
                found = visit(nid)
                if found:
                    return found
        return None

    def __repr__(self) -> str:
        return f"<ACRDocument {self.id[:8]} nodes={len(self.nodes)} roots={len(self.roots)}>"
