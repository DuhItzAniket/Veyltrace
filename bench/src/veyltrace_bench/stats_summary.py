"""summary.json `statistics` (bench_summary 1.1, 04 §8, CCR #357): intervals and paired comparisons.

Every case-mean metric the experiment lists gets a 95% percentile cluster-bootstrap interval per
(dataset, system, method). An experiment with a `statistics.noninferiority` block also gets its
paired comparisons on `primary_metric`, per system: non-inferiority with margin 0 (04 §2: "CI not
entirely below 0") and superiority in `holm_family`. The pooled superiority test runs over all
clusters of the benchmark and joins Holm. The sign flip needs no strata because each cluster flips
on its own (lead, 21 Nov). Pooled intervals wait for the system-stratified bootstrap and are listed
in `not_run`; unstratified pooling is never used. Clusters are (system, root service, fault), the
seeds are the experiment's, and the procedures are veyltrace_stats' (O-14).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.metrics import AC_KS, CaseScore, chance_at
from veyltrace_bench.summary import METRIC_KEYS
from veyltrace_core.errors import ConfigError
from veyltrace_stats.cluster import LEVEL, cluster_bootstrap, sign_flip_test
from veyltrace_stats.exact import holm, mcnemar_exact

__all__ = ["Case", "statistics"]

BEST_SIMPLE_BASELINE = "best_simple_baseline"  # 04 §2: the highest primary metric among `baselines`
MARGIN = 0.0  # 04 §2 H1a and H2a: the paired difference's CI must not lie entirely below 0
CLUSTER_BY = "system/root_service/fault"  # 04 §8
POOLED_REASON = "waits for the system-stratified cluster bootstrap (bench/stats follow-up)"

Groups = dict[tuple[str, str, str], list["Case"]]  # (dataset, system, method) -> its cases
Value = Callable[[CaseScore], float | None]  # a case's value; None outside the metric's cases


@dataclass(frozen=True)
class Case:
    """One scored row with what the statistics need besides its score."""

    case_id: str
    dataset: str
    system: str
    method: str
    cluster: tuple[str | None, ...]  # (system, root service, fault label), 04 §8
    score: CaseScore
    seed: int | None = None  # an LLM arm's seed (bench_result.seed); None for a deterministic method


#: Why McNemar is not run for a seeded method (04 §8 "LLM arms": paired on per-case seed means).
SEEDED_MCNEMAR = "seeded method: per-case seed means are not binary"


def _hit(hit: bool | None) -> float:
    return 1.0 if hit else 0.0


def _chance(k: int, s: CaseScore) -> float:
    return chance_at(k, s.n_candidates or 0) if s.in_universe else 0.0


def _ac(k: int) -> Value:
    return lambda s: _hit(s.hit_at(k)) if s.has_truth else None


def _fine(k: int) -> Value:
    return lambda s: _hit(s.fine_hit_at(k)) if s.has_truth and s.fine_applicable else None


def _chance_at(k: int) -> Value:
    return lambda s: _chance(k, s) if s.has_truth else None


def _chance_diff(k: int) -> Value:
    return lambda s: _hit(s.hit_at(k)) - _chance(k, s) if s.has_truth else None


#: The per-case value of every case-mean key (summary_case_metric), as summary.summarize averages it.
VALUES: dict[str, Value] = {
    "avg_at_5": lambda s: math.fsum(_hit(s.hit_at(k)) for k in AC_KS) / len(AC_KS) if s.has_truth else None,
    "mrr": lambda s: (1.0 / s.position if s.position else 0.0) if s.has_truth else None,
    "retrieval_at_k": lambda s: _hit(s.retrieval_hit) if s.has_truth else None,
    "pool_retrieval": lambda s: _hit(s.pool_hit) if s.has_truth else None,
    "decoy_ranked_first": lambda s: _hit(s.decoy_ranked_first) if s.decoy_present else None,
    **{f"ac_at_{k}": _ac(k) for k in AC_KS},
    **{f"fine_ac_at_{k}": _fine(k) for k in AC_KS},
    **{f"chance_at_{k}": _chance_at(k) for k in AC_KS},
    **{f"chance_diff_at_{k}": _chance_diff(k) for k in AC_KS},
}
CHANNEL = {"retrieval_at_k": "retrieval_hit", "pool_retrieval": "pool_hit"}  # null when no row has it


def _defined(metric: str, cases: Sequence[Case]) -> list[tuple[float, Case]]:
    """(value, case) for the cases in `metric`'s denominator; empty where summary.json has null."""
    faults = [c for c in cases if c.score.has_truth]
    if metric in CHANNEL and all(getattr(c.score, CHANNEL[metric]) is None for c in faults):
        return []
    if metric.startswith("chance") and any(c.score.n_candidates is None for c in faults):
        return []  # Chance@k is null unless every n_i is known (summary.summarize)
    return [(v, c) for c in cases if (v := VALUES[metric](c.score)) is not None]


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _case_means(metric: str, cases: Sequence[Case]) -> dict[str, tuple[float, tuple[str | None, ...]]]:
    """case id -> (mean value over its rows, cluster), in first-row order. A seeded method has one
    row per seed, so its value is the per-case mean over seeds (04 §8 "LLM arms"); a deterministic
    method has one row per case, its value unchanged."""
    rows: dict[str, list[float]] = {}
    clusters: dict[str, tuple[str | None, ...]] = {}
    for v, c in _defined(metric, cases):
        rows.setdefault(c.case_id, []).append(v)
        clusters[c.case_id] = c.cluster
    return {case: (_mean(values), clusters[case]) for case, values in rows.items()}


def _paired(
    exp: Experiment,
    metric: str,
    a: Sequence[Case],
    b: Sequence[Case],
    interval: bool,
    not_run: list[dict[str, str]] | None = None,
    scope: str = "",
) -> dict[str, object]:
    """The paired difference a − b over the cases both have a value for (04 §8), paired on case_id:
    a seeded method's value is its per-case seed mean, so `n_pairs` counts cases and the bootstrap
    resamples clusters, not seeds. McNemar needs binary pairs, so with a seeded side it is not run
    (listed in `not_run` under `scope`)."""
    st = exp.statistics
    means_a, means_b = _case_means(metric, a), _case_means(metric, b)
    pairs = [(va, means_b[c][0], cl) for c, (va, cl) in means_a.items() if c in means_b]
    seeded = any(c.seed is not None for c in (*a, *b))
    keys = ("difference", "low", "high", "sign_flip_p", "mcnemar_only_a", "mcnemar_only_b", "mcnemar_p")
    row: dict[str, object] = {key: None for key in keys}
    row |= {"n_pairs": len(pairs), "n_clusters": len({p[2] for p in pairs})}
    if not pairs:
        return row
    diffs, clusters = [va - vb for va, vb, _ in pairs], [p[2] for p in pairs]
    row["difference"] = _mean(diffs)
    if interval:
        ci = cluster_bootstrap(diffs, clusters, seed=st.bootstrap.seed, resamples=st.bootstrap.resamples)
        row |= {"low": ci.low, "high": ci.high}
    row["sign_flip_p"] = sign_flip_test(
        diffs, clusters, seed=st.permutation.seed, flips=st.permutation.n
    ).p_value
    if st.mcnemar and seeded:
        if not_run is not None:
            not_run.append({"scope": f"mcnemar {scope}", "reason": SEEDED_MCNEMAR})
    elif st.mcnemar and all(va in (0.0, 1.0) and vb in (0.0, 1.0) for va, vb, _ in pairs):
        m = mcnemar_exact([va == 1.0 for va, _, _ in pairs], [vb == 1.0 for _, vb, _ in pairs])
        row |= {"mcnemar_only_a": m.only_a, "mcnemar_only_b": m.only_b, "mcnemar_p": m.p_value}
    return row


def _best(metric: str, candidates: Sequence[str], cases: dict[str, list[Case]]) -> str:
    """The candidate with the highest metric over its cases (04 §2); a tie goes to the earlier listed."""

    def mean(m: str) -> float:
        got = [v for v, _ in _defined(metric, cases.get(m, []))]
        return _mean(got) if got else -math.inf

    return max(candidates, key=lambda m: (mean(m), -candidates.index(m)))


def _comparisons(
    exp: Experiment, groups: Groups, bench: str | None, not_run: list[dict[str, str]]
) -> list[dict[str, object]]:
    """The declared comparisons: method A is the first listed method that is not compared against."""
    st = exp.statistics
    if st.noninferiority is None:
        return []
    metric, vs = st.primary_metric, str(st.noninferiority.get("vs"))
    if metric not in VALUES:
        raise ConfigError(f"statistics.primary_metric {metric!r} is not a case-mean metric (03 §13.3)")
    named = st.noninferiority.get("baselines", []) if vs == BEST_SIMPLE_BASELINE else [vs]
    against = [str(m) for m in named] if isinstance(named, list) else []
    ids = [m.id for m in exp.methods]
    subject = next((m for m in ids if m not in against), None)
    if not against or subject is None or any(m not in ids for m in against):
        raise ConfigError(f"statistics.noninferiority {st.noninferiority} names no method pair of {ids}")
    systems = sorted({(d, s) for d, s, _ in groups})
    rows: list[dict[str, object]] = []
    for d, s in systems:
        here = {m: groups.get((d, s, m), []) for m in [subject, *against]}
        b = _best(metric, against, here)
        base = {
            "dataset": d,
            "system": s,
            "metric": metric,
            "method_a": subject,
            "method_b": b,
            "holm_p": None,
        }
        scope = f"{d}/{s} {subject} vs {b}"
        diff = _paired(exp, metric, here[subject], here[b], interval=True, not_run=not_run, scope=scope)
        rows.append(base | diff | {"kind": "noninferiority", "family": None, "margin": MARGIN})
        if st.holm_family is not None:
            rows.append(base | diff | {"kind": "superiority", "family": st.holm_family, "margin": None})
    if bench is not None and st.holm_family is not None:
        every = {m: [c for d, s in systems for c in groups.get((d, s, m), [])] for m in [subject, *against]}
        b = _best(metric, against, every)
        rows.append(
            {
                "dataset": bench,
                "system": None,
                "metric": metric,
                "method_a": subject,
                "method_b": b,
                "holm_p": None,
            }
            | _paired(
                exp, metric, every[subject], every[b], False, not_run, f"{bench} pooled {subject} vs {b}"
            )
            | {"kind": "superiority", "family": st.holm_family, "margin": None}
        )
    family = [r for r in rows if r["family"] is not None]
    p_values = [r["sign_flip_p"] for r in family]
    if family and all(isinstance(p, float) for p in p_values):
        for r, adjusted in zip(
            family, holm([float(p) for p in p_values if isinstance(p, float)]), strict=True
        ):
            r["holm_p"] = adjusted
    elif family:
        not_run.append({"scope": f"holm {st.holm_family}", "reason": "a family member has no paired cases"})
    return sorted(
        rows,
        key=lambda r: tuple(
            _sort_key(r, k) for k in ("dataset", "system", "metric", "method_a", "method_b", "kind")
        ),
    )


def _sort_key(row: dict[str, object], key: str) -> tuple[bool, str]:
    return (row[key] is not None, str(row[key] or ""))  # x-sort: a null system sorts first


def statistics(exp: Experiment, cases: Sequence[Case]) -> dict[str, object]:
    """The bench_summary 1.1 `statistics` object of one experiment run (03 §13.3)."""
    st = exp.statistics
    groups: Groups = {}
    for c in cases:
        groups.setdefault((c.dataset, c.system, c.method), []).append(c)
    wanted = {key for name in exp.metrics for key in METRIC_KEYS.get(name, ()) if key in VALUES}
    intervals: list[dict[str, object]] = []
    for (dataset, system, method), members in sorted(groups.items()):
        for metric in sorted(wanted):
            if got := _defined(metric, members):
                ci = cluster_bootstrap([v for v, _ in got], [c.cluster for _, c in got],
                                       seed=st.bootstrap.seed, resamples=st.bootstrap.resamples)  # fmt: skip
                intervals.append({"dataset": dataset, "system": system, "method": method, "metric": metric,
                                  "estimate": ci.estimate, "low": ci.low, "high": ci.high,
                                  "n_cases": ci.n_cases, "n_clusters": ci.n_clusters})  # fmt: skip
    benches = sorted({d.split("-")[0] for d in exp.dataset.parts})
    pooled = len(exp.dataset.parts) > 1 and len(benches) == 1  # 04 §8: pooled within one benchmark only
    bench = benches[0] if pooled else None
    not_run = [{"scope": f"{bench} pooled intervals", "reason": POOLED_REASON}] if bench else []
    comparisons = _comparisons(exp, groups, bench, not_run)
    boot, perm = st.bootstrap, st.permutation
    params = {"level": LEVEL, "resamples": boot.resamples, "bootstrap_seed": boot.seed,
              "flips": perm.n, "permutation_seed": perm.seed, "cluster_by": CLUSTER_BY}  # fmt: skip
    not_run.sort(key=lambda r: r["scope"])
    return {"params": params, "intervals": intervals, "comparisons": comparisons, "not_run": not_run}
