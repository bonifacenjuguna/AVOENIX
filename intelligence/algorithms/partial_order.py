"""Strict partial orders with equality classes, cycle detection and extremum analysis.

Used by the relational (ordering) reasoning strategy. ``add_greater(a, b)`` records
"a is greater than b" on one dimension; equality is handled by union-find so
``a = b`` and ``b > c`` imply ``a > c``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Hashable, Iterable

Item = Hashable


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Item, Item] = {}

    def find(self, x: Item) -> Item:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: Item, b: Item) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


class PartialOrder:
    def __init__(self) -> None:
        self._greater: list[tuple[Item, Item, object]] = []   # (a > b, evidence)
        self._equal: list[tuple[Item, Item, object]] = []
        self._not_greater: list[tuple[Item, Item, object]] = []  # NOT (a > b)
        self._items: list[Item] = []

    # ---- construction ----------------------------------------------------------------
    def _touch(self, *items: Item) -> None:
        for it in items:
            if it not in self._items:
                self._items.append(it)

    def add_greater(self, a: Item, b: Item, evidence: object = None) -> None:
        self._touch(a, b)
        self._greater.append((a, b, evidence))

    def add_equal(self, a: Item, b: Item, evidence: object = None) -> None:
        self._touch(a, b)
        self._equal.append((a, b, evidence))

    def add_not_greater(self, a: Item, b: Item, evidence: object = None) -> None:
        self._touch(a, b)
        self._not_greater.append((a, b, evidence))

    @property
    def items(self) -> list[Item]:
        return list(self._items)

    # ---- analysis ------------------------------------------------------------------
    def _classes(self) -> tuple[_UnionFind, dict[Item, list[Item]]]:
        uf = _UnionFind()
        for it in self._items:
            uf.find(it)
        for a, b, _ in self._equal:
            uf.union(a, b)
        groups: dict[Item, list[Item]] = defaultdict(list)
        for it in self._items:
            groups[uf.find(it)].append(it)
        return uf, groups

    def _graph(self) -> tuple[dict[Item, set[Item]], _UnionFind]:
        uf, _ = self._classes()
        graph: dict[Item, set[Item]] = defaultdict(set)   # class -> classes it is greater than
        for it in self._items:
            graph[uf.find(it)]
        for a, b, _ in self._greater:
            graph[uf.find(a)].add(uf.find(b))
        return graph, uf

    def find_cycle(self) -> list[Item] | None:
        """Return one cycle of items (e.g. A>B, B>C, C>A, or A>A) if the order is inconsistent."""
        graph, uf = self._graph()
        for node, outs in graph.items():
            if node in outs:
                return [node, node]
        color: dict[Item, int] = {}
        stack: list[Item] = []

        def dfs(n: Item) -> list[Item] | None:
            color[n] = 1
            stack.append(n)
            for m in graph[n]:
                if color.get(m, 0) == 1:
                    return stack[stack.index(m):] + [m]
                if color.get(m, 0) == 0:
                    found = dfs(m)
                    if found:
                        return found
            stack.pop()
            color[n] = 2
            return None

        for n in list(graph):
            if color.get(n, 0) == 0:
                found = dfs(n)
                if found:
                    return found
        return None

    def is_consistent(self) -> bool:
        if self.find_cycle():
            return False
        return not self.violations()

    def violations(self) -> list[tuple[Item, Item, object]]:
        """NOT(a>b) constraints contradicted by the derived order."""
        bad = []
        for a, b, ev in self._not_greater:
            if self.compare(a, b) == ">":
                bad.append((a, b, ev))
        return bad

    def _reach(self, graph: dict[Item, set[Item]], start: Item) -> set[Item]:
        seen: set[Item] = set()
        queue = deque([start])
        while queue:
            n = queue.popleft()
            for m in graph[n]:
                if m not in seen:
                    seen.add(m)
                    queue.append(m)
        return seen

    def compare(self, a: Item, b: Item) -> str:
        """'>' | '<' | '=' | '?' (undetermined). Requires a consistent order."""
        graph, uf = self._graph()
        ca, cb = uf.find(a), uf.find(b)
        if ca == cb:
            return "="
        if cb in self._reach(graph, ca):
            return ">"
        if ca in self._reach(graph, cb):
            return "<"
        return "?"

    def chain(self, a: Item, b: Item) -> list[Item] | None:
        """Shortest justification path a > ... > b (using class representatives' members)."""
        graph, uf = self._graph()
        ca, cb = uf.find(a), uf.find(b)
        prev: dict[Item, Item | None] = {ca: None}
        queue = deque([ca])
        while queue:
            n = queue.popleft()
            if n == cb:
                break
            for m in graph[n]:
                if m not in prev:
                    prev[m] = n
                    queue.append(m)
        if cb not in prev:
            return None
        path = []
        cur: Item | None = cb
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        # translate class representatives back to a member that was actually mentioned
        def member(cls: Item) -> Item:
            for it in self._items:
                if uf.find(it) == cls:
                    return it
            return cls
        return [a] + [member(c) for c in path[1:-1]] + [b] if len(path) > 1 else [a]

    def maximal(self, domain: Iterable[Item] | None = None) -> list[Item]:
        """Items of ``domain`` not known to be below any other item of the domain."""
        dom = list(domain) if domain is not None else self.items
        return [x for x in dom if not any(y != x and self.compare(y, x) == ">" for y in dom)]

    def minimal(self, domain: Iterable[Item] | None = None) -> list[Item]:
        dom = list(domain) if domain is not None else self.items
        return [x for x in dom if not any(y != x and self.compare(y, x) == "<" for y in dom)]

    def unique_maximum(self, domain: Iterable[Item] | None = None) -> Item | None:
        dom = list(domain) if domain is not None else self.items
        for x in dom:
            if all(y == x or self.compare(x, y) in (">", "=") for y in dom):
                others_equal = [y for y in dom if y != x and self.compare(x, y) == "="]
                if not others_equal:
                    return x
        return None

    def unique_minimum(self, domain: Iterable[Item] | None = None) -> Item | None:
        dom = list(domain) if domain is not None else self.items
        for x in dom:
            if all(y == x or self.compare(x, y) in ("<", "=") for y in dom):
                others_equal = [y for y in dom if y != x and self.compare(x, y) == "="]
                if not others_equal:
                    return x
        return None

    def topological_ranking(self, domain: Iterable[Item] | None = None) -> list[list[Item]] | None:
        """Levels from greatest to least if the order is total on the domain, else None."""
        dom = list(domain) if domain is not None else self.items
        remaining = list(dom)
        levels: list[list[Item]] = []
        while remaining:
            top = [x for x in remaining if not any(y != x and self.compare(y, x) == ">" for y in remaining)]
            if len(top) == 0:
                return None
            # items in `top` must be mutually equal for a total preorder
            for i in range(len(top)):
                for j in range(i + 1, len(top)):
                    if self.compare(top[i], top[j]) != "=":
                        return None
            levels.append(top)
            remaining = [x for x in remaining if x not in top]
        return levels
