"""Hand imported statements to the Knowledge Engine as *claims*. They enter with source_type "imported" (reliability prior 0.5, provenance "imported")
and are validated against existing knowledge like any other claim: agreement raises support, disagreement creates a conflict. They are never written
as established knowledge."""
from __future__ import annotations

from ..engines.knowledge.terms import entity_term
from .store import ProcessedStore

PREDICATE_MAP = {"capital": "attr.capital", "country": "rel.located_in"}


def offer_candidates(store: ProcessedStore, kb, scope, *, limit: int = 100) -> list[dict]:
    out = []
    rows = store.con.execute("""SELECT s.subject, s.predicate, s.object, s.confidence FROM statements s JOIN imports i ON i.id=s.import_id
                                WHERE i.status='active' AND s.status='candidate' LIMIT ?""", (limit,)).fetchall()
    for subj, pred, obj, conf in rows:
        mapped = PREDICATE_MAP.get(pred)
        if not mapped:
            continue
        res = kb.assert_fact(scope, mapped, {"owner": entity_term(subj), "value": entity_term(obj)}, confidence=conf, source_type="imported")
        out.append({"statement": (subj, pred, obj), "status": res.status, "verification": res.verification})
    return out
