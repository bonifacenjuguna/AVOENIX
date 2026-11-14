"""Task decomposition: goal verb + object -> ordered subtasks scheduled over the available time (hierarchical task network, method library in data)."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .chunker import Clause, words_to_number

DATA = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def _methods() -> dict:
    return json.loads((DATA / "methods.json").read_text(encoding="utf-8"))["methods"]


@dataclass
class Plan:
    goal: str
    object: str
    days: int | None
    steps: list[tuple[str, str]]          # (when, what)
    method: str


def _units(np) -> tuple[int | None, str | None]:
    if np is None:
        return None, None
    n = np.f.get("num")
    unit = (np.f.get("nouns") or [None])[-1]
    return n, unit


def plan_from_clause(cl: Clause) -> Plan | None:
    """"How do I prepare for an exam in three days?" -> schedule. Returns None when no method exists for the goal."""
    if cl.wh != "how" or cl.vg is None:
        return None
    verb = (cl.vg.f.get("verb") or "").lower()
    if verb not in _methods():
        return None
    obj = None
    days = None
    for c in cl.items:
        nps = [c] if c.kind == "NP" else ([c.f["np"]] if c.kind == "PP" and c.f.get("np") is not None else [])
        for np in nps:
            n, unit = _units(np)
            if n is not None and unit in ("day", "week", "hour"):
                days = n if unit == "day" else (n * 7 if unit == "week" else max(1, math.ceil(n / 24)))
            elif np.f.get("nouns") and obj is None:
                obj = np.f["nouns"][-1]
    if obj is None:
        return None
    for mname, m in _methods()[verb].items():
        if obj in m["objects"]:
            return _schedule(verb, obj, days, m["subtasks"], mname)
    return None


def _schedule(verb: str, obj: str, days: int | None, subtasks: list[dict], method: str) -> Plan:
    steps: list[tuple[str, str]] = []
    if not days or days < 1:
        for i, t in enumerate(subtasks, 1):
            steps.append((f"Step {i}", t["text"].format(object=obj)))
        return Plan(verb, obj, None, steps, method)
    # assign each subtask to the day where its cumulative share crosses; subtasks that fall on the same day are grouped
    cum = 0.0
    by_day: dict[int, list[str]] = {}
    for t in subtasks:
        start = min(days, int(cum * days) + 1)
        cum += t["share"]
        by_day.setdefault(start, []).append(t["text"].format(object=obj))
    for d in range(1, days + 1):
        if d in by_day:
            first, *rest = by_day[d]
            steps.append((f"Day {d}", "; then ".join([first] + [r[:1].lower() + r[1:] for r in rest])))
    return Plan(verb, obj, days, steps, method)
