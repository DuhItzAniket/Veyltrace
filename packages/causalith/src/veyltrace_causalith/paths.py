"""k-best propagation paths from every node to the entry services (05-causalith §3.6).

Why every node: Causalith runs before the slate exists, so later engines look up their candidates'
paths here (02 §6.5). Paths run against the call direction (03 §6.3): if the entry calls … calls the
candidate, the path is candidate → … → entry. Anomalous edges and anomalous callers are cheaper, so
the best path is the most anomalous route the symptom could have taken to the user.

Yen's k-shortest simple paths on the reversed graph plus a virtual sink behind every entry. Written
in-package (a lead decision in O-05): deterministic by construction, because every Dijkstra queue
entry is ordered by (cost, node list), so equal-cost ties resolve lexicographically; no RNG.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Iterable, Iterator, Mapping, Sequence

__all__ = ["SINK", "Adjacency", "ranked_paths", "reversed_graph", "yen"]

#: The virtual sink: an empty name can never be a node (names match ^[a-z0-9][a-z0-9.-]*$, 03 §1).
SINK = ""
Adjacency = Mapping[str, Sequence[tuple[str, float]]]


def _dijkstra(
    adj: Adjacency,
    source: str,
    target: str,
    banned_nodes: frozenset[str],
    banned_arcs: frozenset[tuple[str, str]],
) -> tuple[float, tuple[str, ...]] | None:
    """Cheapest path source → target avoiding the banned nodes and arcs; ties → smallest node list."""
    queue: list[tuple[float, tuple[str, ...]]] = [(0.0, (source,))]
    done: set[str] = set()
    while queue:
        cost, path = heapq.heappop(queue)
        node = path[-1]
        if node == target:
            return cost, path
        if node in done:
            continue
        done.add(node)
        for nxt, weight in adj.get(node, ()):
            if nxt in done or nxt in banned_nodes or (node, nxt) in banned_arcs or nxt in path:
                continue
            heapq.heappush(queue, (cost + weight, (*path, nxt)))
    return None


def _arc_cost(adj: Adjacency, path: Sequence[str]) -> float:
    weights = {(a, b): w for a in path for b, w in adj.get(a, ())}
    return sum(weights[a, b] for a, b in itertools.pairwise(path))


def yen(adj: Adjacency, source: str, target: str) -> Iterator[tuple[float, tuple[str, ...]]]:
    """Every simple path source → target in non-decreasing cost (ties: node list ascending), lazily.

    Standard Yen: each accepted path spawns spur candidates that avoid its root's nodes and the arcs
    leaving the shared root in already accepted paths.
    """
    first = _dijkstra(adj, source, target, frozenset(), frozenset())
    if first is None:
        return
    accepted: list[tuple[str, ...]] = []
    candidates: list[tuple[float, tuple[str, ...]]] = [first]
    seen: set[tuple[str, ...]] = {first[1]}
    while candidates:
        cost, path = heapq.heappop(candidates)
        accepted.append(path)
        yield cost, path
        for i in range(len(path) - 1):
            root = path[: i + 1]
            arcs = frozenset((p[i], p[i + 1]) for p in accepted if len(p) > i + 1 and p[: i + 1] == root)
            spur = _dijkstra(adj, path[i], target, frozenset(root[:-1]), arcs)
            if spur is None:
                continue
            total = (*root[:-1], *spur[1])
            if total not in seen:
                seen.add(total)
                heapq.heappush(candidates, (_arc_cost(adj, total), total))


def reversed_graph(
    edges: Iterable[tuple[str, str, bool | None]], anomalous_nodes: frozenset[str], entries: Sequence[str],
    penalty: float,
) -> dict[str, list[tuple[str, float]]]:  # fmt: skip
    """R: dst → src at cost 1 if the edge or its caller is anomalous, else 1 + penalty; plus a
    zero-cost arc from every entry to the sink. Arcs sorted by target name (05 §3.6 steps 2–3)."""
    adj: dict[str, dict[str, float]] = {}
    for src, dst, anomalous in edges:
        if src == dst:
            continue
        cost = 1.0 if anomalous is True or src in anomalous_nodes else 1.0 + penalty
        current = adj.setdefault(dst, {})
        current[src] = min(cost, current.get(src, cost))
    for entry in entries:
        adj.setdefault(entry, {})[SINK] = 0.0
    return {node: sorted(arcs.items()) for node, arcs in sorted(adj.items())}


def ranked_paths(
    adj: Mapping[str, Sequence[tuple[str, float]]], candidate: str, entries: frozenset[str],
    anomalous_nodes: frozenset[str], k: int, max_len: int,
) -> list[tuple[tuple[str, ...], float]]:  # fmt: skip
    """Up to k (nodes, anomalous_fraction), best first (05 §3.6 steps 4–6)."""
    if candidate in entries:
        return [((candidate,), 1.0 if candidate in anomalous_nodes else 0.0)]
    # Arcs cost at most 1 + penalty, so no path of at most max_len nodes costs more than this.
    longest = (max_len - 1) * max((w for arcs in adj.values() for _, w in arcs), default=1.0)
    kept: list[tuple[float, float, int, tuple[str, ...]]] = []
    for cost, path in yen(adj, candidate, SINK):
        nodes = path[:-1]
        if (len(kept) >= k and cost > kept[k - 1][0]) or cost > longest:
            break
        if len(nodes) > max_len:
            continue
        fraction = sum(1 for n in nodes if n in anomalous_nodes) / len(nodes)
        kept.append((cost, -fraction, len(nodes), nodes))
        kept.sort()
    return [(nodes, -neg) for _, neg, _, nodes in sorted(kept)[:k]]
