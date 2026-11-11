"""Content planner: turns structured outcomes (conclusions, storage results, learning results, social acts) into a ContentPlan.

The plan is language-neutral data. Nothing here chooses words. Statuses that mean "I could not establish this" are never
turned into assertions: unknown stays unknown, underdetermined stays underdetermined, contradictions are surfaced.
"""

from __future__ import annotations

from typing import Any

from ...core.contracts import Conclusion, ContentPlan

SUPPORT_LIMIT = 5


def _labels(items: list[dict] | None) -> list[str]:
    return [i["label"] if isinstance(i, dict) else str(i) for i in (items or [])]


def _support(c: Conclusion) -> list[dict]:
    out, seen = [], set()
    for e in c.evidence:
        if e.data and e.kind in ("user_statement", "knowledge"):
            key = repr(sorted((k, repr(v)) for k, v in e.data.items()))
            if key not in seen:
                seen.add(key)
                out.append(e.data)
    return out[:SUPPORT_LIMIT]


def _what(q: dict) -> str | None:
    p, t = q.get("predicate"), q.get("terms", {})
    if p and p.startswith("attr.") and "owner" in t:
        owner = t["owner"]
        return f"{'your' if owner == 'you' else 'the'} {p[5:].replace('_', ' ')}{'' if owner == 'you' else ' of ' + str(owner)}"
    if q.get("kind") == "question" and q.get("predicate") == "rel.located_in" and {"figure", "ground"} <= set(t):
        return f"whether {t['figure']} is in {t['ground']}"
    if p in ("rel.extreme", "rel.exceeds") or (p == "rel.has_property" and "subject" in q.get("variables", {})):
        return "the answer to that"
    return None


def conclusion_to_message(c: Conclusion, *, capabilities: list[str] | None = None) -> dict | None:
    q, a = c.query or {}, c.answer or {}
    st = c.status
    if st in ("consistent",):
        return None
    if st == "answered":
        t = a.get("type")
        if t == "entity":
            return {"type": "entity_answer", "entity": a["value"]["label"], "relation": a.get("relation", {}), "domain": a.get("domain", []),
                    "confidence": c.confidence, "support": _support(c), "query": q}
        if t == "entities":
            return {"type": "entities_answer", "entities": _labels(a["value"]), "relation": a.get("relation", {}), "unrelated": _labels(c.alternatives),
                    "confidence": c.confidence, "support": _support(c), "query": q}
        if t == "value":
            src = c.evidence[0].kind if c.evidence else None
            src = c.evidence[0].source if c.evidence and c.evidence[0].kind == "knowledge" else src
            disputed = next((n for n in c.notes if n.startswith("Conflicting claims")), None)
            return {"type": "value_answer", "attribute": a["attribute"], "owner": "you" if a["owner"].get("key") == "@user" else a["owner"].get("label"),
                    "value": a["value"].get("label") or str(a["value"].get("value")), "confidence": c.confidence, "source": src,
                    "alternatives": c.alternatives, "user_claims": a.get("user_claims") or [], "disputed_note": "(Other claims about this are on hold as disputed.)" if disputed else None, "query": q}
        if t == "number":
            return {"type": "number_answer", "value": a["value"], "expression": a.get("expression"), "exact": a.get("exact"), "query": q}
        return {"type": "unsupported", "capabilities": capabilities or [], "query": q}
    if st in ("yes", "no"):
        msg = {"type": "boolean_answer", "value": st == "yes", "query": q, "confidence": c.confidence, "support": _support(c)}
        if st == "no":
            if q.get("predicate") == "rel.exceeds" and a.get("relation") in ("<", "="):
                t = q["terms"]
                if a["relation"] == "<":
                    msg["actual_fact"] = {"predicate": "rel.exceeds", "args": {"greater": t["lesser"], "lesser": t["greater"], "dimension": q["term_keys"]["dimension"]}}
                else:
                    msg["actual_fact"] = {"predicate": "rel.equal_on", "args": {"first": t["greater"], "second": t["lesser"], "dimension": q["term_keys"]["dimension"]}}
            elif q.get("predicate", "").startswith("attr.") and a.get("actual"):
                msg["actual_fact"] = {"predicate": q["predicate"], "args": {"owner": q["terms"]["owner"], "value": a["actual"].get("label")}}
        return msg
    if st == "unknown":
        if a.get("type") == "boolean":
            return {"type": "boolean_answer", "value": None, "query": q, "missing": c.missing}
        sugg = (a.get("suggestions") if isinstance(a, dict) else None) or []
        return {"type": "unknown", "what": _what(q), "missing": c.missing, "suggestions": sugg, "query": q}
    if st == "underdetermined":
        return {"type": "underdetermined", "alternatives": _labels(c.alternatives), "relation": {"dimension": q.get("terms") and q["term_keys"].get("dimension"), "pole": q.get("pole")},
                "missing": c.missing, "query": q}
    if st == "contradiction":
        return {"type": "contradiction", "contradictions": c.contradictions}
    if st == "undefined":
        return {"type": "undefined_math", "error": (a or {}).get("error"), "expression": (a or {}).get("expression")}
    if st == "unverified_claim":
        return {"type": "claim_answer", "attribute": a.get("attribute"), "owner": "you" if a["owner"].get("key") == "@user" else a["owner"].get("label"),
                "claims": a.get("claims", []), "asked": a.get("asked"), "query": q}
    if st == "likely":
        return {"type": "likely_answer", "generalisation": a, "confidence": c.confidence, "query": q}
    if st == "unsupported":
        return {"type": "unsupported", "capabilities": capabilities or [], "query": q}
    return {"type": "unsupported", "capabilities": capabilities or [], "query": q}


def build_plan(*, conclusions: list[Conclusion] | None = None, stored: list[dict] | None = None, learning: list[dict] | None = None, social: list[dict] | None = None,
               clarify: dict | None = None, error: dict | None = None, goal: dict | None = None, self_description: dict | None = None,
               recall: list[str] | None = None, capabilities: list[str] | None = None, explain: bool = False, name: str | None = None,
               occasion: dict | None = None) -> ContentPlan:
    messages: list[dict] = []
    objective = "acknowledge"
    explanation: list[str] = []
    certainty = "certain"
    for s in social or []:
        t = s["type"]
        if t == "greet":
            messages.append({"type": "greet", "name": name, "occasion": {**(occasion or {}), **s.get("occasion", {})}, "with_content": bool(conclusions or stored or learning)})
            objective = "greet"
        elif t == "farewell":
            messages.append({"type": "farewell", "name": name}); objective = "farewell"
        elif t == "thank":
            messages.append({"type": "thank_reply"}); objective = "thank"
        elif t == "social_inquiry":
            messages.append({"type": "social_reply"}); objective = "social"
    if error:
        messages.append({"type": "error", **error})
        objective = "error"
    if clarify:
        messages.append({"type": "clarify", **clarify})
        objective = "clarify"
    for c in conclusions or []:
        m = conclusion_to_message(c, capabilities=capabilities)
        if m:
            messages.append(m)
            objective = "answer" if c.status in ("answered", "yes", "no", "likely") else {"unknown": "inform_unknown", "underdetermined": "inform_unknown", "unverified_claim": "inform_unknown", "contradiction": "clarify"}.get(c.status, "refuse")
            if c.status in ("answered", "yes", "no") and (c.confidence or 1) < 0.75:
                certainty = "likely"
            elif c.status in ("unknown", "underdetermined", "unverified_claim"):
                certainty = "unknown"
            elif c.status == "likely":
                certainty = "likely"
            if explain or c.status in ("contradiction",):
                explanation += c.steps
    answered = any(m["type"].endswith("_answer") or m["type"] in ("unknown", "underdetermined") for m in messages)
    for s in stored or []:
        if s.get("claim"):
            messages.append({"type": "claim_recorded", **s["claim"]})
            if objective in ("acknowledge",):
                objective = "acknowledge_claim"
            continue
        if answered and s.get("ok", True):
            continue          # statements made alongside a question are stored silently; the answer is what the user asked for
        messages.append({"type": "stored", "facts": s["facts"], "status": s.get("status", "stored")} if s.get("ok", True) else {"type": "not_stored", "reason": s.get("reason", "unspecified")})
        if objective in ("acknowledge",):
            objective = "store_ack"
    for l in learning or []:
        messages.append({"type": "learned", "kind": l["kind"], "change": (l.get("proposal") or {}).get("change"), "verified": l.get("verified", False), "status": l["status"], "reason": l.get("reason")})
        objective = "store_ack" if objective == "acknowledge" else objective
    if goal:
        messages.append({"type": "goal", **goal})
    if self_description:
        messages.append({"type": "self", **self_description}); objective = "answer"
    if recall is not None:
        messages.append({"type": "recall", "items": recall}); objective = "answer"
    if not messages:
        messages.append({"type": "acknowledge"})
    return ContentPlan(objective=objective, messages=messages, certainty=certainty, explanation=explanation)
