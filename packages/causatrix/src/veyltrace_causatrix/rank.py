"""rank(): gated reciprocal rank fusion of the enabled rankers and the step-5 order of U (07 §3.1).

F(s) = Σ_{r active} w_r / (k_rrf + rank_r(s)) with k_rrf = 60 and w_r = 1.0, both fixed a priori
(Cormack et al.'s k; 02 §6.7). An abstaining ranker adds nothing, so it can never change F. U is
then ordered by (−round(F, 9), internal anomaly first, earliest onset, name), the key Causentra
uses with V in place of F (02 §6.9 step 6). Pure: Causentra calls it again for trial T9 on atoms
and edges without one telemetry source.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Vote, load_ranker, vote
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources
from veyltrace_core.errors import ConfigError

__all__ = ["FUSED_DECIMALS", "RankResult", "fuse", "order_universe", "rank"]

#: Fused scores are compared after rounding to 9 decimals, as canonical JSON writes them (03 §8).
FUSED_DECIMALS: Final = 9
#: The fusion rule rank() implements; combsum_minmax and borda are R-16 ablations (07 §9).
RRF: Final = "rrf"


@dataclass(frozen=True)
class RankResult:
    """Every enabled ranker's vote (by name), F over U, and U in the step-5 order."""

    universe: tuple[str, ...]
    votes: tuple[Vote, ...]
    fused: Mapping[str, float]
    order: tuple[str, ...]

    @property
    def active(self) -> tuple[str, ...]:
        """Sorted names of the rankers that voted (slate.rankers_active)."""
        return tuple(v.ranker for v in self.votes if v.active)

    def __hash__(self) -> int:
        """Hash by content: `fused` and each vote's scores and ranks are mappings, so hash them sorted."""
        votes = tuple(
            (v.ranker, v.abstained, tuple(sorted(v.scores.items())), tuple(sorted(v.ranks.items())))
            for v in self.votes
        )
        return hash((self.universe, votes, tuple(sorted(self.fused.items())), self.order))


def fuse(votes: tuple[Vote, ...], universe: tuple[str, ...], cfg: CausatrixConfig) -> dict[str, float]:
    """F(s) = fsum over the active rankers of w_r / (rrf.k + rank_r(s)); 0.0 with no voter."""
    active = [v for v in votes if v.active]
    return {s: math.fsum(cfg.weight(v.ranker) / (cfg.rrf_k + v.ranks[s]) for v in active) for s in universe}


def order_universe(fused: Mapping[str, float], ev: EvidenceView, k_anom: float) -> tuple[str, ...]:
    """U sorted by (−round(F, 9), 0 if I(s) ≥ k_anom else 1, onset_ms(s), s) (07 §3.1 step 5)."""

    def key(s: str) -> tuple[float, int, float, str]:
        f = ev.of(s)
        return (-round(fused[s], FUSED_DECIMALS), 0 if f.internal >= k_anom else 1, f.onset_ms, s)

    return tuple(sorted(fused, key=key))


def rank(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> RankResult:
    """Run every enabled ranker (sorted by name), fuse the votes and order U (07 §3.1 steps 1–5)."""
    if cfg.method != RRF:
        msg = f"causatrix.fusion.method={cfg.method} is an R-16 ablation and not implemented yet; use rrf"
        raise ConfigError(msg)
    if ev.universe != graph.universe:
        msg = "rank() needs the evidence and graph views over the same universe U"
        raise ValueError(msg)
    votes = tuple(vote(load_ranker(name), ev, graph, sources, cfg) for name in cfg.rankers)
    fused = fuse(votes, ev.universe, cfg)
    return RankResult(ev.universe, votes, MappingProxyType(fused), order_universe(fused, ev, cfg.k_anom))
