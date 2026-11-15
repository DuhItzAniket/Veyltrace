"""`prism_m`: PRISM's additive combination of internal and external deviation (07 §3.2).

M = I' + E − ln(1 + I' + E) with I' = max(I, prism_m.silence_z · Sil), so a silent service counts
as strongly internally anomalous; `prism_m.combine: conj` scores min(I', E) instead (ablation).
A re-implementation inside this pipeline, never quoted with PRISM's published numbers.
"""

from __future__ import annotations

import math

from veyltrace_causatrix.config import CausatrixConfig
from veyltrace_causatrix.ranking import Ranker
from veyltrace_causatrix.views import EvidenceView, GraphView
from veyltrace_contracts.models import Sources


def channel(ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> bool:
    """Votes when the case has any robust_z anomaly atom (07 §3.3)."""
    return ev.has_robust_z


def score(ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in ev.universe:
        f = ev.of(s)
        i = max(f.internal, cfg.silence_z * f.silent)
        x = i + f.external
        out[s] = min(i, f.external) if cfg.prism_combine == "conj" else x - math.log1p(x)
    return out


RANKER = Ranker("prism_m", channel, score)
