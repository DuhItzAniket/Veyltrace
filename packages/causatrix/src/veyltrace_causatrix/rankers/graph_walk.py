"""`graph_walk`: personalised PageRank from symptoms toward the services they call (07 §3.4).

The walker starts at anomalous services and moves caller → callee, against the direction in which
anomalies propagate (02 §6.7), so mass gathers at services that are anomalous themselves and whose
callees are not. Each row of the transition matrix splits into callee moves weighted by the
callee's anomaly, a self-loop weighted by the node's own internal anomaly, and a restart by the
personalisation; every row sums to 1, so no node is absorbing. A fixed iteration count (no
convergence test) and `math.fsum` in sorted order keep the result independent of float stopping
decisions (07 §5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Ranker
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources


@dataclass(frozen=True)
class Row:
    """One row of the transition matrix: callee moves, self-loop and restart mass (sum 1)."""

    moves: tuple[tuple[str, float], ...]
    stay: float
    restart: float


def prior(ev: EvidenceView, cfg: CausatrixConfig) -> dict[str, float]:
    """A(s) = max(I(s), E(s), prism_m.silence_z · Sil(s)) over U."""
    return {
        s: max(ev.of(s).internal, ev.of(s).external, cfg.silence_z * ev.of(s).silent) for s in ev.universe
    }


def channel(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> bool:
    """Votes when G has an edge and max_s A(s) > 0 (07 §3.3)."""
    return graph.has_edges and max(prior(ev, cfg).values(), default=0.0) > 0


def transition_rows(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, Row]:
    """The rows of 07 §3.4 for every node of U (requires max A > 0)."""
    big_a = prior(ev, cfg)
    top = max(big_a.values())
    rows: dict[str, Row] = {}
    for u in ev.universe:
        edges = graph.callees(u)
        total = math.fsum(e.weight for e in edges)
        moves = tuple((e.dst, e.weight / total * big_a[e.dst] / top) for e in edges if total > 0)
        free = 1.0 - math.fsum(f for _, f in moves)
        a_internal = ev.of(u).internal / top if cfg.self_loop else 0.0
        rows[u] = Row(moves, free * a_internal, free * (1.0 - a_internal))
    return rows


def score(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, float]:
    """π after `graph_walk.iterations` steps of π ← (1 − d)·p + d·πP from π₀ = p; 0 when A ≡ 0."""
    big_a = prior(ev, cfg)
    if not big_a or max(big_a.values()) <= 0:
        return dict.fromkeys(ev.universe, 0.0)
    mass = math.fsum(big_a.values())
    p = {s: big_a[s] / mass for s in ev.universe}
    rows = transition_rows(ev, graph, cfg)
    into: dict[str, list[tuple[str, float]]] = {s: [] for s in ev.universe}
    for u in ev.universe:
        for v, f in rows[u].moves:
            into[v].append((u, f))
    d = cfg.damping
    pi = dict(p)
    for _ in range(cfg.iterations):
        restart = math.fsum(pi[u] * rows[u].restart for u in ev.universe)
        pi = {
            v: (1.0 - d) * p[v]
            + d * (math.fsum([pi[v] * rows[v].stay, *(pi[u] * f for u, f in into[v])]) + restart * p[v])
            for v in ev.universe
        }
    return pi


RANKER = Ranker("graph_walk", channel, score)
