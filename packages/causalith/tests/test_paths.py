"""Unit and property tests of the k-best propagation paths (05-causalith §3.6, §7)."""

from __future__ import annotations

import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_causalith.paths import SINK, ranked_paths, reversed_graph, yen

MICRO = [("frontend", "checkout", False), ("checkout", "payment", True), ("frontend", "cart", False)]


def test_micro_example() -> None:
    # 05 §3.6: payment -> checkout costs 1 (anomalous edge); the best path is [payment, checkout, frontend]
    # with 2 of 3 nodes anomalous.
    adj = reversed_graph(MICRO, frozenset({"payment", "checkout"}), ["frontend"], 1.0)
    assert adj["payment"] == [("checkout", 1.0)]
    (best,) = ranked_paths(adj, "payment", frozenset({"frontend"}), frozenset({"payment", "checkout"}), 3, 10)
    assert best == (("payment", "checkout", "frontend"), 2 / 3)


def test_entries_get_themselves_and_unreachable_nodes_nothing() -> None:
    adj = reversed_graph(MICRO, frozenset(), ["frontend"], 1.0)
    assert ranked_paths(adj, "frontend", frozenset({"frontend"}), frozenset(), 3, 10) == [
        (("frontend",), 0.0)
    ]
    assert ranked_paths(adj, "nowhere", frozenset({"frontend"}), frozenset(), 3, 10) == []


def test_ties_at_the_kth_cost_are_all_seen_then_sorted() -> None:
    # Diamond: c reaches the entry e through a or b at equal cost; b's path is more anomalous.
    edges = [("e", "a", False), ("e", "b", False), ("a", "c", False), ("b", "c", False)]
    adj = reversed_graph(edges, frozenset({"b"}), ["e"], 1.0)
    paths = ranked_paths(adj, "c", frozenset({"e"}), frozenset({"b"}), 1, 10)
    assert paths == [(("c", "b", "e"), 1 / 3)]  # cheaper via b (b is the anomalous caller)
    flat = reversed_graph(edges, frozenset(), ["e"], 1.0)
    assert [p for p, _ in ranked_paths(flat, "c", frozenset({"e"}), frozenset(), 1, 10)] == [("c", "a", "e")]


def test_max_len_drops_long_paths() -> None:
    chain = [("e", "a", False), ("a", "b", False), ("b", "c", False)]
    adj = reversed_graph(chain, frozenset(), ["e"], 1.0)
    assert ranked_paths(adj, "c", frozenset({"e"}), frozenset(), 3, 3) == []
    assert ranked_paths(adj, "c", frozenset({"e"}), frozenset(), 3, 4) == [(("c", "b", "a", "e"), 0.0)]


def _brute(adj: dict[str, list[tuple[str, float]]], s: str, t: str) -> list[tuple[float, tuple[str, ...]]]:
    out: list[tuple[float, tuple[str, ...]]] = []

    def walk(path: list[str], cost: float) -> None:
        if path[-1] == t:
            out.append((cost, tuple(path)))
            return
        for nxt, w in adj.get(path[-1], []):
            if nxt not in path:
                walk([*path, nxt], cost + w)

    walk([s], 0.0)
    return sorted(out)


_nodes = "abcdef"
_graphs = st.lists(st.tuples(st.sampled_from(_nodes), st.sampled_from(_nodes), st.booleans()), max_size=14)


@settings(max_examples=80, deadline=None)
@given(_graphs, st.frozensets(st.sampled_from(_nodes)))
def test_yen_enumerates_every_simple_path_in_cost_order(
    edges: list[tuple[str, str, bool]], anomalous: frozenset[str]
) -> None:
    adj = reversed_graph(edges, anomalous, ["a"], 1.0)
    got = list(yen(adj, "f", SINK))
    assert sorted(got) == _brute(adj, "f", SINK)
    assert [c for c, _ in got] == sorted(c for c, _ in got)


@settings(max_examples=80, deadline=None)
@given(_graphs, st.frozensets(st.sampled_from(_nodes)), st.integers(1, 3))
def test_ranked_paths_are_valid_propagation_paths(
    edges: list[tuple[str, str, bool]], anomalous: frozenset[str], k: int
) -> None:
    arcs = {(dst, src) for src, dst, _ in edges if src != dst}
    adj = reversed_graph(edges, anomalous, ["a", "b"], 1.0)
    for candidate in _nodes:
        paths = ranked_paths(adj, candidate, frozenset({"a", "b"}), anomalous, k, 10)
        assert len(paths) <= k
        for nodes, fraction in paths:
            assert nodes[0] == candidate and nodes[-1] in {"a", "b"}
            assert len(set(nodes)) == len(nodes)
            assert all((u, v) in arcs for u, v in itertools.pairwise(nodes))
            assert fraction == sum(n in anomalous for n in nodes) / len(nodes)
