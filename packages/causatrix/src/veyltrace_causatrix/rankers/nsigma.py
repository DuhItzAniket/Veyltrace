"""`nsigma`: the maximum N-sigma deviation NS(s), two-sided (07 §3.2; RCAEval's N-Sigma idea)."""

from __future__ import annotations

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Ranker
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources


def channel(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> bool:
    """Votes when the case has any nsigma anomaly atom (07 §3.3)."""
    return ev.has_nsigma


def score(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, float]:
    return {s: ev.of(s).nsigma for s in ev.universe}


RANKER = Ranker("nsigma", channel, score)
