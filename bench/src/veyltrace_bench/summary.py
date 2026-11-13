"""Aggregation of case scores into the summary.json metrics of one group (04 §7, §9).

A group is one (dataset, system, method); its rows are `metrics.CaseScore`s. Rates are over the
group's fault cases F, so failed and unranked runs stay in every denominator (04 §7 "Failed runs";
"Unranked runs", added by #14) and no-fault rows stay out of all of them (and of n_unranked). Means
use math.fsum, so a summary never depends on row order. Onset error is not a rate: its median and
max are over the rows that have one (detected-protocol ``ok`` runs of injected cases, #215).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from types import MappingProxyType

from veyltrace_bench.metrics import AC_KS, CaseScore, chance_at


def _at_ks(*names: str) -> tuple[str, ...]:
    return tuple(f"{name}_at_{k}" for name in names for k in AC_KS)


#: summary.json keys of each 04 §9 metric name v0 computes (04 §7); counts are always written.
METRIC_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ac_at_k": _at_ks("ac"),
        "avg_at_5": ("avg_at_5",),
        "mrr": ("mrr",),
        "fine_ac_at_k": _at_ks("fine_ac"),
        "retrieval_at_k": ("retrieval_at_k", "retrieval_k", "pool_retrieval"),
        "rerank_at_1": ("rerank_at_1",),
        "chance": _at_ks("chance"),
        "lift": _at_ks("lift", "chance_diff"),  # Lift@k = AC@k / Chance@k, also AC@k − Chance@k
        "onset_error": ("onset_error_median_ms", "onset_error_max_ms", "n_onset"),  # 04 §7, #215
    }
)
ALL_METRICS = tuple(METRIC_KEYS)


def _mean(values: Sequence[float]) -> float | None:
    """Mean via math.fsum (exactly rounded), so the result never depends on row order."""
    return math.fsum(values) / len(values) if values else None


def _rate(hits: Sequence[bool | None], channel: bool = False) -> float | None:
    """Share of true hits, a null hit counting as a miss; None for no rows, and for a ``channel``
    (slate, pool) that no row has."""
    if channel and all(hit is None for hit in hits):
        return None
    return _mean([1.0 if hit else 0.0 for hit in hits])


def summarize(scores: Iterable[CaseScore], metrics: Collection[str] = ALL_METRICS) -> dict[str, object]:
    """The requested ``metrics`` (METRIC_KEYS names) of one (dataset, system, method) group, with
    its denominators and run_outcome counts, JSON-ready for summary.json; row order never matters.

    Rates are over the fault cases F. Chance@k = mean over F of min(k, n_i)/n_i, 0 when the root is
    outside the case's universe, and None unless every n_i is known (RCAEval's chance_accuracy), so
    Chance, Lift and AC share one denominator. Rerank@1 = AC@1 / Retrieval@K (04 §7).
    """
    rows = list(scores)
    fault = [s for s in rows if s.has_truth]
    fine = [s for s in fault if s.fine_applicable]
    n_chance = sum(s.n_candidates is not None for s in fault)
    counts: dict[str, object] = {
        "n_rows": len(rows),
        "n_fault": len(fault),
        "n_no_truth": len(rows) - len(fault),
        "n_unranked": sum(s.unranked for s in fault),
        "n_fine": len(fine),
        "n_chance": n_chance,
        "n_outside_universe": sum(s.in_universe is False for s in fault),
        "outcomes": dict(sorted(Counter(s.outcome for s in rows).items())),
    }
    ac = {k: _rate([s.hit_at(k) for s in fault]) for k in AC_KS}
    values: dict[str, object] = {}
    for k, acc in ac.items():
        per_case = [chance_at(k, s.n_candidates or 0) if s.in_universe else 0.0 for s in fault]
        chance = _mean(per_case) if n_chance == len(fault) else None
        values[f"ac_at_{k}"] = acc
        values[f"fine_ac_at_{k}"] = _rate([s.fine_hit_at(k) for s in fine])
        values[f"chance_at_{k}"] = chance
        values[f"lift_at_{k}"] = acc / chance if acc is not None and chance else None
        values[f"chance_diff_at_{k}"] = acc - chance if acc is not None and chance is not None else None
    values["avg_at_5"] = _mean([v for v in ac.values() if v is not None])
    values["mrr"] = _mean([1.0 / s.position if s.position else 0.0 for s in fault])
    retrieval = values["retrieval_at_k"] = _rate([s.retrieval_hit for s in fault], channel=True)
    values["retrieval_k"] = sorted({s.slate_k for s in fault if s.slate_k is not None}) or None
    values["pool_retrieval"] = _rate([s.pool_hit for s in fault], channel=True)
    values["rerank_at_1"] = ac[1] / retrieval if ac[1] is not None and retrieval else None
    onset = [s.onset_error_ms for s in rows if s.onset_error_ms is not None]
    values["onset_error_median_ms"] = statistics.median(onset) if onset else None  # sorts: order-free
    values["onset_error_max_ms"] = max(onset) if onset else None
    values["n_onset"] = len(onset)
    keep = {key for name in metrics for key in METRIC_KEYS[name]}
    return counts | {key: value for key, value in values.items() if key in keep}
