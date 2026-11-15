"""`cp_sbfl`: critical-path-weighted Ochiai spectrum SP(s) from FaultLoom (07 §3.2; 06 §3.4)."""

from __future__ import annotations

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Ranker
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources


def channel(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> bool:
    """Votes when the case has traces and any spectrum atom (07 §3.3)."""
    return sources.traces and ev.has_spectrum


def score(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, float]:
    return {s: ev.of(s).spectrum for s in ev.universe}


RANKER = Ranker("cp_sbfl", channel, score)
