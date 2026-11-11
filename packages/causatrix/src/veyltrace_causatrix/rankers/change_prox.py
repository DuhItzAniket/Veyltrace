"""`change_prox`: change proximity times anomaly presence (07 §3.2).

CH(s) · 1[max(I, E) ≥ k_anom or Sil = 1]: a recent change counts only on a service that is itself
anomalous or silent, so a quiet deploy elsewhere never votes.
"""

from __future__ import annotations

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Ranker
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources


def channel(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> bool:
    """Votes when the case has change events and any change_proximity atom (07 §3.3)."""
    return sources.events and ev.has_change


def score(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in ev.universe:
        f = ev.of(s)
        present = max(f.internal, f.external) >= cfg.k_anom or f.silent == 1.0
        out[s] = f.change if present else 0.0
    return out


RANKER = Ranker("change_prox", channel, score)
