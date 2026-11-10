"""A small finite-domain constraint solver (backtracking, MRV, forward checking).

It is deliberately generic: variables, domains, and n-ary predicate constraints. The
reasoning engine uses it to enumerate every ranking consistent with the stated
relations, which cross-checks the transitive-closure strategy by an independent method.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Any, Callable, Hashable, Iterator, Sequence

Var = Hashable


@dataclass
class Constraint:
    scope: tuple[Var, ...]
    check: Callable[..., bool]
    label: str = ""


class CSP:
    def __init__(self) -> None:
        self.domains: dict[Var, list[Any]] = {}
        self.constraints: list[Constraint] = []

    def add_variable(self, var: Var, domain: Sequence[Any]) -> None:
        self.domains[var] = list(domain)

    def add_constraint(self, scope: Sequence[Var], check: Callable[..., bool], label: str = "") -> None:
        for v in scope:
            if v not in self.domains:
                raise KeyError(f"unknown variable {v!r}")
        self.constraints.append(Constraint(tuple(scope), check, label))

    def _consistent(self, assignment: dict[Var, Any]) -> bool:
        for c in self.constraints:
            if all(v in assignment for v in c.scope):
                if not c.check(*(assignment[v] for v in c.scope)):
                    return False
        return True

    def solutions(self, limit: int | None = None) -> Iterator[dict[Var, Any]]:
        count = 0
        domains = {v: list(d) for v, d in self.domains.items()}

        def backtrack(assignment: dict[Var, Any], doms: dict[Var, list[Any]]):
            nonlocal count
            if limit is not None and count >= limit:
                return
            if len(assignment) == len(doms):
                count += 1
                yield dict(assignment)
                return
            # MRV: pick the unassigned variable with the smallest remaining domain
            var = min((v for v in doms if v not in assignment), key=lambda v: len(doms[v]))
            for value in doms[var]:
                assignment[var] = value
                if self._consistent(assignment):
                    pruned = self._forward_check(assignment, doms, var)
                    if pruned is not None:
                        yield from backtrack(assignment, pruned)
                del assignment[var]
                if limit is not None and count >= limit:
                    return

        yield from backtrack({}, domains)

    def _forward_check(self, assignment: dict[Var, Any], doms: dict[Var, list[Any]], just: Var):
        new = {v: list(d) for v, d in doms.items()}
        for c in self.constraints:
            if just not in c.scope:
                continue
            unassigned = [v for v in c.scope if v not in assignment]
            if len(unassigned) != 1:
                continue
            target = unassigned[0]
            keep = []
            for val in new[target]:
                trial = dict(assignment)
                trial[target] = val
                if c.check(*(trial[v] for v in c.scope)):
                    keep.append(val)
            if not keep:
                return None
            new[target] = keep
        return new

    def count_solutions(self, cap: int = 100_000) -> int:
        return sum(1 for _ in self.solutions(limit=cap))


def rankings(items: Sequence[Hashable], greater: Sequence[tuple[Hashable, Hashable]],
             not_greater: Sequence[tuple[Hashable, Hashable]] = (),
             equal: Sequence[tuple[Hashable, Hashable]] = (), *, max_items: int = 8,
             limit: int = 50_000) -> list[dict[Hashable, int]] | None:
    """Enumerate integer rank assignments (higher = greater) consistent with the constraints.

    Items declared equal share a rank. Ranks range over ``0..n-1`` so any weak ordering of
    ``n`` items is representable. Returns None when there are too many items to enumerate.
    """
    items = list(items)
    if len(items) > max_items:
        return None
    n = len(items)
    csp = CSP()
    for it in items:
        csp.add_variable(it, range(n))
    for a, b in greater:
        csp.add_constraint((a, b), lambda x, y: x > y, f"{a}>{b}")
    for a, b in not_greater:
        csp.add_constraint((a, b), lambda x, y: not (x > y), f"not {a}>{b}")
    for a, b in equal:
        csp.add_constraint((a, b), lambda x, y: x == y, f"{a}={b}")
    out = []
    seen = set()
    for sol in csp.solutions(limit=limit):
        # canonicalise: compress ranks so two solutions describing the same weak order merge
        distinct = sorted(set(sol.values()))
        remap = {v: i for i, v in enumerate(distinct)}
        canon = tuple(sorted((str(k), remap[v]) for k, v in sol.items()))
        if canon in seen:
            continue
        seen.add(canon)
        out.append({k: remap[v] for k, v in sol.items()})
    return out
