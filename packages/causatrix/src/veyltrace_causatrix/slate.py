"""The v1 slate: top-K candidates with their votes, and a fused score for every service (03 §8).

07 §3.1 steps 6–7: take the first `slate.k` services of the step-5 order, classify each, and list
every service of U in `all_scores`. If no ranker voted, `candidates = []` (07 §3.1, §6): an order
built from the tie-break alone is not a ranking, and Causentra then returns INCONCLUSIVE with a
telemetry ask. Every enabled ranker appears in `ranker_ranks`/`ranker_scores`, null when it
abstained, and in `fusion.weights`.
"""

from __future__ import annotations

from typing import Any

from veyltrace_causatrix.classify import classify
from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.rank import FUSED_DECIMALS, RankResult
from veyltrace_causatrix.views import EvidenceView, GraphView

__all__ = ["build_slate"]


def _candidate(
    position: int, service: str, result: RankResult, ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig
) -> dict[str, Any]:
    c = classify(service, ev, graph, cfg)
    return {
        "rank": position,
        "service": service,
        "component": c.component,
        "indicator": c.indicator,
        "mode": c.mode,
        "fault_class": c.fault_class,
        "fused_score": result.fused[service],
        "ranker_ranks": {v.ranker: v.ranks[service] if v.active else None for v in result.votes},
        "ranker_scores": {v.ranker: v.scores[service] if v.active else None for v in result.votes},
    }


def build_slate(
    case_id: str, result: RankResult, ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig
) -> dict[str, Any]:
    """The slate.json object (without schema_version, which the writer stamps)."""
    picked = result.order[: cfg.k] if result.active else ()
    by_score = sorted(result.universe, key=lambda s: (-round(result.fused[s], FUSED_DECIMALS), s))
    return {
        "case_id": case_id,
        "k": cfg.k,
        "rankers_active": list(result.active),
        "fusion": {"method": cfg.method, "k": cfg.fusion_k, "weights": dict(cfg.weights)},
        "candidates": [_candidate(i, s, result, ev, graph, cfg) for i, s in enumerate(picked, start=1)],
        "all_scores": [{"service": s, "fused_score": result.fused[s]} for s in by_score],
    }
