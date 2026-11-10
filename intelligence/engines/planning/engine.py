"""Planning / Goal Engine: goals, task decomposition, dependency graphs, scheduling and plan evaluation.

Algorithms (all deterministic, stdlib only):
  * decomposition  - clause splitting with ordering cues ("then", "after", numbered lists, "first ...") into tasks + dependencies
  * dependency DAG - Kahn topological order with cycle detection; unknown-dependency detection
  * scheduling     - forward pass (earliest start/finish), critical path by estimated minutes, slack, parallel makespan vs total effort
  * priority       - priority x urgency score (urgency from the due date and the clock)
  * evaluation     - findings: missing estimates, cycles, infeasible deadlines, empty plans, blocked ready-set
Persistence uses the Memory Engine (category ``semantic``, key ``goal:<id>``): schema 0001 has no dedicated goals table.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from ...core.engine import Engine, EngineInfo, EngineStatus, traced
from ...core.errors import InputError, NotFoundError
from ...core.types import Scope
from ..memory.engine import MemoryEngine

DEFAULT_ESTIMATE = 30
STATUSES = ("todo", "doing", "done", "blocked")
GOAL_PATTERNS = [
    r"^(?:i\s+(?:want|need|would like|plan|am planning|'d like)\s+to|my goal is to|i'm trying to|i am trying to|help me|i have to|i must)\s+(?P<g>.+?)[.!?]*$",
    r"^(?:let's|let us)\s+(?P<g>.+?)[.!?]*$",
    r"^(?:plan|organi[sz]e|prepare|schedule)\s+(?P<g>.+?)[.!?]*$",
]
_SPLIT = re.compile(r"\s*(?:,\s*(?:and\s+)?(?:then\s+)?|;\s*|\s+and then\s+|\s+then\s+|\s+after that\s+|\s+afterwards?\s+|\s+and\s+(?=[a-z]+\s))\s*", re.I)
_ENUM = re.compile(r"(?:^|\s)(?:\d+[.)]|[-*•])\s+")
_SEQUENTIAL = re.compile(r"\bthen\b|\bafter that\b|\bafterwards?\b|\bnext\b|\bfinally\b|\bfirst\b|\d+[.)]\s", re.I)


@dataclass
class Task:
    id: str
    title: str
    status: str = "todo"
    depends_on: list[str] = field(default_factory=list)
    estimate_min: int | None = None
    priority: int = 3
    note: str | None = None


@dataclass
class Goal:
    id: str
    title: str
    description: str = ""
    priority: int = 3
    due: str | None = None
    status: str = "active"
    tasks: list[Task] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Goal":
        g = Goal(**{k: v for k, v in d.items() if k != "tasks"})
        g.tasks = [Task(**t) for t in d.get("tasks", [])]
        return g


# ---- pure algorithms -----------------------------------------------------------------------------------------------------
def decompose(text: str) -> list[dict]:
    """'book flights, then reserve a hotel and pack' -> [{'title','depends_on_prev'}...]. Sequential cues chain tasks; otherwise tasks are parallel."""
    text = text.strip().rstrip(".!")
    sequential = bool(_SEQUENTIAL.search(text))
    text = re.sub(r"^(first|firstly)[,:]?\s+", "", text, flags=re.I)
    parts = [p.strip(" ,.;") for p in (_ENUM.split(text) if _ENUM.search(" " + text) else _SPLIT.split(text)) if p and p.strip(" ,.;")]
    parts = [re.sub(r"^(?:next|finally|lastly|also)[,:]?\s+", "", p, flags=re.I) for p in parts]
    return [{"title": p[0].upper() + p[1:], "depends_on_prev": sequential and i > 0} for i, p in enumerate(parts)]


def topological_order(tasks: list[Task]) -> tuple[list[str], list[str] | None]:
    """Kahn's algorithm. Returns (order, cycle_members). Dependencies on unknown ids are ignored here (reported by evaluate)."""
    ids = {t.id for t in tasks}
    indeg = {t.id: sum(1 for d in t.depends_on if d in ids) for t in tasks}
    out: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for d in t.depends_on:
            if d in ids:
                out[d].append(t.id)
    queue = [i for i, n in indeg.items() if n == 0]
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in out[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if len(order) < len(tasks):
        return order, [i for i in ids if i not in order]
    return order, None


def schedule(tasks: list[Task]) -> dict:
    order, cyc = topological_order(tasks)
    if cyc:
        return {"ok": False, "cycle": cyc}
    by = {t.id: t for t in tasks}
    est = {t.id: (t.estimate_min or DEFAULT_ESTIMATE) for t in tasks}
    start: dict[str, int] = {}
    finish: dict[str, int] = {}
    for i in order:
        deps = [d for d in by[i].depends_on if d in by]
        start[i] = max((finish[d] for d in deps), default=0)
        finish[i] = start[i] + est[i]
    makespan = max(finish.values(), default=0)
    # backward pass for slack
    late_finish = {i: makespan for i in order}
    succ: dict[str, list[str]] = {i: [] for i in order}
    for t in tasks:
        for d in t.depends_on:
            if d in succ:
                succ[d].append(t.id)
    for i in reversed(order):
        for s in succ[i]:
            late_finish[i] = min(late_finish[i], late_finish[s] - est[s])
    slack = {i: late_finish[i] - finish[i] for i in order}
    critical = [i for i in order if slack[i] == 0]
    return {"ok": True, "order": order, "start": start, "finish": finish, "slack": slack, "critical_path": critical,
            "makespan_min": makespan, "total_effort_min": sum(est.values()), "estimated_all": all(t.estimate_min for t in tasks)}


def progress(tasks: list[Task]) -> float:
    if not tasks:
        return 0.0
    w = lambda t: (t.estimate_min or DEFAULT_ESTIMATE)
    return sum(w(t) for t in tasks if t.status == "done") / sum(w(t) for t in tasks)


def ready_tasks(tasks: list[Task]) -> list[Task]:
    done = {t.id for t in tasks if t.status == "done"}
    return [t for t in tasks if t.status in ("todo", "blocked") and all(d in done for d in t.depends_on)]


class PlanningEngine(Engine):
    info = EngineInfo(
        key="planning", name="Planning / Goal Engine", status=EngineStatus.PARTIAL,
        summary="Goal tracking, rule-based decomposition, dependency DAG, critical-path scheduling, progress, plan evaluation.",
        depends_on=("memory",),
        capabilities=("goal detection from first-person statements", "decomposition by sequencing cues", "cycle / unknown-dependency detection",
                      "critical path, slack, makespan vs total effort", "priority x urgency ranking", "next-action selection", "plan evaluation findings"),
        limitations=("Decomposition is clause-splitting, not domain planning: AVOENIX does not know how to plan a trip, it structures what the user says.",
                     "Single-resource assumptions; no calendars, working hours or resource levelling.",
                     "Goals live in memory rows (no dedicated table in schema 0001)."),
    )

    def self_check(self) -> tuple[bool, str]:
        steps = decompose("Plan a trip: book flights, then reserve a hotel, then pack")
        ok = len(steps) >= 3
        return ok, f"decompose probe produced {len(steps)} steps" if ok else f"decompose probe produced {len(steps)} steps (expected >= 3)"

    def __init__(self, memory: MemoryEngine):
        super().__init__()
        self.memory = memory

    # ---- detection ------------------------------------------------------------------------------------------------------
    @staticmethod
    def detect_goal(text: str) -> str | None:
        t = text.strip()
        for pat in GOAL_PATTERNS:
            m = re.match(pat, t, re.I)
            if m and len(m.group("g").split()) >= 2:
                return m.group("g").strip()
        return None

    # ---- persistence ----------------------------------------------------------------------------------------------------
    def _row(self, scope: Scope, goal_id: str) -> dict:
        rows = self.memory.repo(scope).select("memories", {"category": "semantic", "key": f"goal:{goal_id}", "status": "active"})
        if not rows:
            raise NotFoundError("goal not found")
        return rows[0]

    def get_goal(self, scope: Scope, goal_id: str) -> Goal:
        return Goal.from_dict(self._row(scope, goal_id)["data"])

    def _save(self, scope: Scope, g: Goal) -> None:
        row = self._row(scope, g.id)
        self.memory.repo(scope).update("memories", {"id": row["id"]}, {"data": g.to_dict(), "content": f"Goal: {g.title} [{g.status}]",
                                                                    "updated_at": self.memory.clock.now().isoformat()})

    def list_goals(self, scope: Scope, *, status: str | None = None) -> list[Goal]:
        rows = self.memory.repo(scope).select("memories", {"category": "semantic", "status": "active"})
        goals = [Goal.from_dict(r["data"]) for r in rows if (r.get("key") or "").startswith("goal:")]
        return [g for g in goals if status is None or g.status == status]

    @traced("create_goal")
    def create_goal(self, scope: Scope, title: str, *, description: str = "", priority: int = 3, due: str | None = None, decompose_text: str | None = None) -> Goal:
        if not title.strip():
            raise InputError("goal title is empty")
        if not 1 <= priority <= 5:
            raise InputError("priority must be 1..5")
        if due:
            try:
                datetime.fromisoformat(due)
            except ValueError as e:
                raise InputError("due must be an ISO date/time") from e
        g = Goal(id="g_" + uuid.uuid4().hex[:10], title=title.strip(), description=description, priority=priority, due=due, created_at=self.memory.clock.now().isoformat())
        if decompose_text:
            self._apply_decomposition(g, decompose_text)
        self.memory.remember(scope, "semantic", f"Goal: {g.title} [{g.status}]", key=f"goal:{g.id}", data=g.to_dict(), importance=0.7, source="user_statement")
        return g

    def _apply_decomposition(self, g: Goal, text: str) -> None:
        prev = None
        for step in decompose(text):
            t = Task(id=f"t{len(g.tasks) + 1}", title=step["title"], depends_on=[prev.id] if (step["depends_on_prev"] and prev) else [])
            g.tasks.append(t)
            prev = t

    @traced("add_task")
    def add_task(self, scope: Scope, goal_id: str, title: str, *, depends_on: list[str] | None = None, estimate_min: int | None = None, priority: int = 3) -> Goal:
        g = self.get_goal(scope, goal_id)
        if not title.strip():
            raise InputError("task title is empty")
        ids = {t.id for t in g.tasks}
        bad = [d for d in (depends_on or []) if d not in ids]
        if bad:
            raise InputError(f"unknown dependencies: {bad}")
        g.tasks.append(Task(id=f"t{len(g.tasks) + 1}", title=title.strip(), depends_on=list(depends_on or []), estimate_min=estimate_min, priority=priority))
        self._save(scope, g)
        return g

    @traced("update_task")
    def update_task(self, scope: Scope, goal_id: str, task_id: str, *, status: str | None = None, estimate_min: int | None = None) -> Goal:
        g = self.get_goal(scope, goal_id)
        t = next((x for x in g.tasks if x.id == task_id), None)
        if t is None:
            raise NotFoundError("task not found")
        if status:
            if status not in STATUSES:
                raise InputError(f"status must be one of {STATUSES}")
            t.status = status
        if estimate_min is not None:
            t.estimate_min = estimate_min
        if g.tasks and all(x.status == "done" for x in g.tasks):
            g.status = "completed"
        elif g.status == "completed":
            g.status = "active"
        self._save(scope, g)
        return g

    # ---- analysis ----------------------------------------------------------------------------------------------------------
    def urgency(self, g: Goal) -> float:
        if not g.due:
            return 0.2
        due = datetime.fromisoformat(g.due)
        due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
        days = (due - self.memory.clock.now()).total_seconds() / 86400
        return 1.0 if days <= 0 else max(0.1, min(1.0, 1.0 / (1 + days / 3)))

    def rank(self, scope: Scope) -> list[dict]:
        out = []
        for g in self.list_goals(scope, status="active"):
            out.append({"goal": g.id, "title": g.title, "score": round(g.priority / 5 * 0.6 + self.urgency(g) * 0.4, 3), "urgency": round(self.urgency(g), 3)})
        return sorted(out, key=lambda x: -x["score"])

    def next_actions(self, scope: Scope, goal_id: str) -> list[Task]:
        g = self.get_goal(scope, goal_id)
        sch = schedule(g.tasks)
        ready = ready_tasks(g.tasks)
        if sch.get("ok"):
            ready.sort(key=lambda t: (sch["slack"][t.id], -t.priority))
        return ready

    @traced("evaluate_plan")
    def evaluate(self, scope: Scope, goal_id: str) -> dict:
        g = self.get_goal(scope, goal_id)
        findings: list[dict] = []
        if not g.tasks:
            findings.append({"severity": "warning", "code": "no_tasks", "message": "The goal has no tasks yet."})
        ids = {t.id for t in g.tasks}
        for t in g.tasks:
            for d in t.depends_on:
                if d not in ids:
                    findings.append({"severity": "error", "code": "unknown_dependency", "message": f"{t.id} depends on unknown task {d}."})
        sch = schedule(g.tasks) if g.tasks else {"ok": True, "makespan_min": 0, "total_effort_min": 0, "estimated_all": True, "critical_path": []}
        if not sch["ok"]:
            findings.append({"severity": "error", "code": "dependency_cycle", "message": f"Circular dependencies among {sch['cycle']}."})
        else:
            missing = [t.id for t in g.tasks if not t.estimate_min]
            if missing:
                findings.append({"severity": "info", "code": "missing_estimates", "message": f"No estimate for {missing}; {DEFAULT_ESTIMATE} min assumed each."})
            if g.due and g.tasks:
                due = datetime.fromisoformat(g.due)
                due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
                avail = (due - self.memory.clock.now()).total_seconds() / 60
                if avail <= 0:
                    findings.append({"severity": "error", "code": "overdue", "message": "The due date has passed."})
                elif sch["makespan_min"] > avail:
                    findings.append({"severity": "error", "code": "infeasible", "message": "Even fully parallel, the critical path is longer than the time left."})
                elif sch["total_effort_min"] > avail:
                    findings.append({"severity": "warning", "code": "effort_exceeds_time", "message": "Total effort exceeds the time left for a single worker; it only fits if tasks run in parallel."})
        blocked = [t.id for t in g.tasks if t.status == "blocked"]
        if blocked:
            findings.append({"severity": "warning", "code": "blocked_tasks", "message": f"Blocked: {blocked}"})
        ok = not any(f["severity"] == "error" for f in findings)
        return {"goal": g.id, "ok": ok, "findings": findings, "progress": round(progress(g.tasks), 3),
                "schedule": {k: v for k, v in sch.items() if k in ("makespan_min", "total_effort_min", "critical_path", "order")}}
