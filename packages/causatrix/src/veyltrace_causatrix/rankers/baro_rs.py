"""`baro_rs`: BARO's robust-scaled maximum deviation, two-sided: max(I, E) (07 §3.2).

Unlike RCAEval's reference BARO it scores absolute deviations, so a root whose traffic drops is not
ranked last; the faithful RCAEval baseline is run separately by bench (04 §4).
"""

from __future__ import annotations

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Ranker
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources


def channel(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> bool:
    """Votes when the case has any robust_z anomaly atom (07 §3.3)."""
    return ev.has_robust_z


def score(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, float]:
    return {s: max(ev.of(s).internal, ev.of(s).external) for s in ev.universe}


RANKER = Ranker("baro_rs", channel, score)
