"""Claims: the typed, versioned *epistemic* layer over ACR propositions (schema ``claim/1.0``).

An ACR proposition says *what* is asserted. A ``Claim`` says *who asserted it, what we know about whether it is true, and why*:

* ``ProvenanceKind``  where the information came from (user, inference, internal curated knowledge, independent verification, import, unresolved)
* ``ClaimType``       what sort of statement it is: about the world (needs verification), about the speaker (self-report), or a scenario premise
* ``Verification``    the outcome of validation — deliberately separate from the fact's lifecycle status (active / superseded / ...)
* ``Assessment``      structured, explainable evidence assessment (never a bare number)

A user *saying* something and the system *believing* it are separate operations: a user claim starts ``unverified`` and only moves when
validation finds evidence. Terms (``args``) reuse the ACR term encoding from ``engines/knowledge/terms.py``; nothing here is a second ontology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

CLAIM_SCHEMA_VERSION = "claim/1.0"


class ProvenanceKind(str, Enum):
    USER_PROVIDED = "user_provided"
    SYSTEM_INFERENCE = "system_inference"
    INTERNAL_KNOWLEDGE = "internal_knowledge"          # curated / shipped with AVOENIX (authored, not independently verified)
    INDEPENDENTLY_VERIFIED = "independently_verified"
    IMPORTED = "imported"
    UNRESOLVED = "unresolved"                          # origin could not be determined (e.g. legacy rows)


class ClaimType(str, Enum):
    WORLD = "world"          # about the world: capitals, taxonomy, locations ... needs evidence before it is knowledge
    PERSONAL = "personal"    # about the speaker (name, preferences): the speaker is the best available authority
    PREMISE = "premise"      # scenario statement about arbitrary individuals ("Tom is taller than Sam"): usable for reasoning, never verified


class Verification(str, Enum):
    VERIFIED = "verified"            # independently verified source
    CURATED = "curated"              # internal curated knowledge: established for answering, NOT independently verified
    SUPPORTED = "supported"          # agrees with / is entailed by established knowledge
    UNVERIFIED = "unverified"        # no evidence either way
    CONTRADICTED = "contradicted"    # conflicts with established knowledge
    CONFLICTING = "conflicting"      # conflicts with another claim of comparable standing
    NOT_APPLICABLE = "not_applicable"  # self-reports: nothing to verify against


class EpistemicLevel(str, Enum):
    ESTABLISHED = "established"
    SUPPORTED = "supported"          # supported but uncertain
    UNVERIFIED = "unverified"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"    # evidence too thin to assess
    SELF_REPORTED = "self_reported"
    UNKNOWN = "unknown"              # nothing is known (used for answers about absent claims)


class ConflictKind(str, Enum):
    NEGATION = "negation"                    # same statement with opposite polarity
    FUNCTIONAL = "functional"                # single-valued attribute with different values
    TAXONOMIC = "taxonomic"                  # is-a claim contradicted through the taxonomy (including inherited negations)
    ORDERING = "ordering"                    # comparison that would make an order circular
    LOCATION = "location"                    # located-in claim incompatible with established containment


ESTABLISHED_VERIFICATIONS = (Verification.VERIFIED.value, Verification.CURATED.value)

# source_type (existing column) -> provenance kind
PROVENANCE_OF_SOURCE = {
    "user_statement": ProvenanceKind.USER_PROVIDED.value,
    "derived": ProvenanceKind.SYSTEM_INFERENCE.value,
    "seed_curated": ProvenanceKind.INTERNAL_KNOWLEDGE.value,
    "system": ProvenanceKind.INTERNAL_KNOWLEDGE.value,
    "learned": ProvenanceKind.INTERNAL_KNOWLEDGE.value,
    "external_verified": ProvenanceKind.INDEPENDENTLY_VERIFIED.value,
    "imported": ProvenanceKind.IMPORTED.value,
}

# role names that carry (subject, object) for each predicate family
_SUBJECT_OBJECT = {
    "rel.is_a": ("subject", "object"), "rel.located_in": ("figure", "ground"), "rel.exceeds": ("greater", "lesser"),
    "rel.equal_on": ("first", "second"), "rel.has_property": ("subject", "property"), "rel.extreme": ("subject", "dimension"),
}


def triple_of(predicate: str, args: dict[str, dict]) -> tuple[dict | None, str, dict | None]:
    """(subject term, predicate, object term) view of a fact's arguments, for display and API consumers."""
    if predicate.startswith("attr."):
        return args.get("owner"), predicate, args.get("value")
    s, o = _SUBJECT_OBJECT.get(predicate, (None, None))
    if s:
        return args.get(s), predicate, args.get(o)
    items = list(args.values())
    return (items[0] if items else None), predicate, (items[1] if len(items) > 1 else None)


@dataclass
class EvidenceItem:
    """One piece of evidence for or against a claim."""
    direction: str                 # supports | contradicts | context
    kind: str                      # established_fact | entailment | contradiction | source_prior | corroboration | missing | temporal
    note: str
    ref: str | None = None         # id of the fact this evidence rests on
    weight: float | None = None    # reliability of that evidence (0..1) when it has one

    def to_dict(self) -> dict:
        return {"direction": self.direction, "kind": self.kind, "note": self.note, "ref": self.ref, "weight": self.weight}

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceItem":
        return cls(d["direction"], d["kind"], d["note"], d.get("ref"), d.get("weight"))


@dataclass
class Assessment:
    """Explainable epistemic assessment. ``interpretation_confidence`` (did we understand the statement?) is kept apart from
    ``support`` (is the statement true?). ``support`` is None when the claim cannot be assessed and 0.0 when evidence is absent."""
    level: str
    verification: str
    interpretation_confidence: float
    support: float | None
    refutation: float | None = None
    basis: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    schema: str = CLAIM_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {"schema": self.schema, "level": self.level, "verification": self.verification,
                "interpretation_confidence": self.interpretation_confidence, "support": self.support, "refutation": self.refutation,
                "basis": list(self.basis), "evidence": [e.to_dict() for e in self.evidence]}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Assessment":
        d = d or {}
        return cls(d.get("level", EpistemicLevel.INSUFFICIENT.value), d.get("verification", Verification.UNVERIFIED.value),
                   float(d.get("interpretation_confidence", 0.0)), d.get("support"), d.get("refutation"), list(d.get("basis", [])),
                   [EvidenceItem.from_dict(e) for e in d.get("evidence", [])], d.get("schema", CLAIM_SCHEMA_VERSION))


@dataclass
class Claim:
    """Serialisable view of a stored fact as an epistemic claim."""
    id: str
    subject: dict | None
    predicate: str
    object: dict | None
    polarity: str
    claim_type: str
    provenance: str
    source: str
    source_ref: str | None
    verification: str
    status: str
    assessment: Assessment
    statement: str
    conversation_id: str | None
    created_at: str | None
    updated_at: str | None
    conflicts: list[str] = field(default_factory=list)
    memory_id: str | None = None
    schema: str = CLAIM_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {"schema": self.schema, "id": self.id, "subject": self.subject, "predicate": self.predicate, "object": self.object,
                "polarity": self.polarity, "claim_type": self.claim_type, "provenance": self.provenance, "source": self.source,
                "source_ref": self.source_ref, "verification": self.verification, "status": self.status, "assessment": self.assessment.to_dict(),
                "statement": self.statement, "conversation_id": self.conversation_id, "created_at": self.created_at,
                "updated_at": self.updated_at, "conflicts": list(self.conflicts), "memory_id": self.memory_id}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Claim":
        return cls(d["id"], d.get("subject"), d["predicate"], d.get("object"), d.get("polarity", "positive"), d["claim_type"], d["provenance"],
                   d["source"], d.get("source_ref"), d["verification"], d["status"], Assessment.from_dict(d.get("assessment")), d.get("statement", ""),
                   d.get("conversation_id"), d.get("created_at"), d.get("updated_at"), list(d.get("conflicts", [])), d.get("memory_id"),
                   d.get("schema", CLAIM_SCHEMA_VERSION))
