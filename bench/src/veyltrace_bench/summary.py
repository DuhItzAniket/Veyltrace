"""Aggregation of case scores into the summary.json metrics of one group (04 §7, §9).

A group is one (dataset, system, method); its rows are `metrics.CaseScore`s. Rates are over the
group's fault cases F, so failed and unranked runs stay in every denominator (04 §7 "Failed runs";
"Unranked runs", added by #14) and no-fault rows stay out of all of them (and of n_unranked). Means
use math.fsum, so a summary never depends on row order. Onset error is not a rate: its median and
max are over the rows that have one (detected-protocol ``ok`` runs of injected cases, #215). Cost is
the nearest-rank p50 and p95 of each cost column over the rows that have it (03 §13.3, #316).

The calibration and proposal entries (bench_summary 1.2, CCR #404, #405) also read each row's key,
fold and verdict columns (`with_rows`): coverage and set size over the fault rows, NO_FAULT rates
over the normal (no-truth) rows too, risk–coverage and selective accuracy from the status and the
verdict's confidence, and the top-1 and verdict-hash comparisons across a case's proposal variants.
A method with no set or no verdict has null values for that channel, as Retrieval@K does.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType

from veyltrace_bench.metrics import AC_KS, CaseScore, chance_at, coarse_service

#: per_case.csv cost columns summarised by the cost metric, and its percentiles (03 §13.3, #316).
COST_COLUMNS = ("wall_ms", "peak_rss_mb", "tokens_in", "tokens_out")
COST_PERCENTILES = (50, 95)  # 04 §2 H5 and 02 §9 budgets are p95s; p50 is the typical case
MEDIAN = 50  # set_size_median is the nearest-rank p50, as for cost (03 §13.3)
NO_FAULT, CONFIRMED, LIKELY = "NO_FAULT", "CONFIRMED", "LIKELY"  # verdict.status values (03 §10)
#: The verified score V's order for risk–coverage, most confident first; a row with no status (a
#: failed run) comes after all of them (04 §7 Risk–coverage; 03 §13.3).
STATUS_ORDER = (CONFIRMED, LIKELY, "INCONCLUSIVE", NO_FAULT)
DECIMALS = 9  # margins and fused scores compare at 9 decimals, as Causentra rounds them (09 §5)
PLANT_PREFIX = "plant-"  # bench_result.variant of a planted-proposal run (03 §13.3, H2b)
PERM_PREFIX = "perm-"  # bench_result.variant of a proposal permutation (03 §13.2, H2c)


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
        "cost": ("n_cost", *(f"{c}_p{p}" for c in COST_COLUMNS for p in COST_PERCENTILES)),  # #316
        "decoy_ranked_first": ("decoy_ranked_first", "n_decoy"),  # 04 §7 Decoy metrics, H4c (#357)
        # bench_summary 1.2 (#404): nested entries, computed by `entries` from the rows (ROW_ENTRIES)
        "coverage": ("coverage", "coverage_gap", "pool_coverage", "n_fault", "by_fold"),
        "set_size": ("set_size_mean", "set_size_median", "singleton_share", "n_set"),
        "no_fault_rates": (
            "false_alarm_rate",
            "n_normal",
            "wrong_no_fault_rate",
            "n_fault",
            "no_fault_precision",
            "no_fault_recall",
            "by_fold",
        ),
        "risk_coverage": ("aurc_verdict", "aurc_fused", "n_fault"),
        "selective_accuracy": (
            "ac_at_1_confirmed",
            "answer_rate_confirmed",
            "ac_at_1_likely_or_better",
            "answer_rate_likely_or_better",
            "n_fault",
        ),
        "decoy_top1_change": ("decoy_top1_change", "n_pairs"),
        "permutation_invariance": ("permutation_invariance", "n_cases"),
    }
)
ALL_METRICS = tuple(METRIC_KEYS)


def _mean(values: Sequence[float]) -> float | None:
    """Mean via math.fsum (exactly rounded), so the result never depends on row order."""
    return math.fsum(values) / len(values) if values else None


def nearest_rank(values: Sequence[float], p: int) -> float | None:
    """The p-th percentile by nearest rank: the ceil(p*n/100)-th smallest of n values (03 §13.3), so
    it is one of the values and order-free; None for no values."""
    if not values:
        return None
    rank = max(1, -(-p * len(values) // 100))  # ceil(p*n/100) in integers, at least the smallest
    return sorted(values)[rank - 1]


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
    outside the case's services (n_i, not U), and None unless every n_i is known (RCAEval's
    chance_accuracy), so Chance, Lift and AC share one denominator. Rerank@1 = AC@1 / Retrieval@K (04 §7).
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
        "n_outside_services": sum(s.in_universe is False for s in fault),  # root not among n_i (04 §7)
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
    for column in COST_COLUMNS:
        have = [float(v) for s in rows if (v := getattr(s, column)) is not None]
        for p in COST_PERCENTILES:
            values[f"{column}_p{p}"] = nearest_rank(have, p)
    values["n_cost"] = sum(s.wall_ms is not None for s in rows)
    decoyed = [s for s in rows if s.decoy_present]  # over rows, as decoys are planted per case
    values["decoy_ranked_first"] = _rate([s.decoy_ranked_first for s in decoyed])
    values["n_decoy"] = len(decoyed)
    keep = {key for name in metrics if name in METRIC_KEYS for key in METRIC_KEYS[name]}
    return counts | {key: value for key, value in values.items() if key in keep}


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def with_rows(scores: Sequence[CaseScore], rows: Sequence[Mapping[str, object]]) -> list[CaseScore]:
    """The group's scores with their per_case rows' case_id, seed, variant, fold, status and
    verdict_hash (03 §13.2), which the calibration and proposal entries read. Row i is score i's row,
    as the runner appends both together; a row whose scored columns differ from its score's is
    refused, so a misaligned pair never yields a number."""
    if len(scores) != len(rows):
        raise ValueError(f"{len(scores)} scores but {len(rows)} per_case rows")
    out: list[CaseScore] = []
    for score, row in zip(scores, rows, strict=True):
        if any(row.get(column) != value for column, value in score.columns().items()):
            raise ValueError(f"per_case row of case {row.get('case_id')!r} is not its score's row")
        seed = row.get("seed")
        out.append(
            replace(
                score,
                case_id=_optional_str(row.get("case_id")),
                seed=seed if isinstance(seed, int) else None,
                variant=_optional_str(row.get("variant")),
                fold=_optional_str(row.get("fold")),
                status=_optional_str(row.get("status")),
                verdict_hash=_optional_str(row.get("verdict_hash")),
            )
        )
    return out


def _share(flags: Iterable[bool]) -> float | None:
    """Share of true flags; None for none."""
    return _mean([1.0 if flag else 0.0 for flag in flags])


def _folds(rows: Sequence[CaseScore]) -> list[str]:
    """The folds of the rows, sorted; a row with a null fold is not held out (03 §13.2)."""
    return sorted({s.fold for s in rows if s.fold is not None})


def _coverage(rows: Sequence[CaseScore], alpha: float) -> dict[str, object]:
    """Share of fault rows whose root is in the set (04 §7 Coverage), its gap to 1 - alpha, coverage
    given decision-pool retrieval, and per fold; null without a set channel (no verifier)."""
    fault = [s for s in rows if s.has_truth]
    coverage = _rate([s.in_set for s in fault], channel=True)
    per_fold = [(f, [s for s in fault if s.fold == f]) for f in _folds(rows)]
    return {
        "coverage": coverage,
        "coverage_gap": coverage - (1 - alpha) if coverage is not None else None,
        "pool_coverage": _rate([s.in_set for s in fault if s.pool_hit], channel=True),
        "n_fault": len(fault),
        "by_fold": [
            {"fold": f, "coverage": _rate([s.in_set for s in members], channel=True), "n_fault": len(members)}
            for f, members in per_fold
        ],
    }


def _set_size(rows: Sequence[CaseScore]) -> dict[str, object]:
    """Mean, nearest-rank median and singleton share of |C_i| over the fault rows with a set size
    (04 §7 Set size, H3b): a normal window declared NO_FAULT has an empty set by design."""
    sizes = [float(s.set_size) for s in rows if s.has_truth and s.set_size is not None]  # typed: number
    return {
        "set_size_mean": _mean(sizes),
        "set_size_median": nearest_rank(sizes, MEDIAN),
        "singleton_share": _share(n == 1 for n in sizes),
        "n_set": len(sizes),
    }


def _no_fault_rates(rows: Sequence[CaseScore]) -> dict[str, object]:
    """False alarms over normal rows, wrong NO_FAULT over fault rows, and NO_FAULT's precision and
    recall over all rows (04 §7 NO_FAULT rates); a failed run's empty status is not NO_FAULT."""
    verdicts = any(s.has_verdict for s in rows)
    normal = [s for s in rows if not s.has_truth]
    fault = [s for s in rows if s.has_truth]

    def share(flags: Iterable[bool]) -> float | None:
        return _share(flags) if verdicts else None

    per_fold = [(f, [s for s in normal if s.fold == f]) for f in _folds(rows)]
    return {
        "false_alarm_rate": share(s.status != NO_FAULT for s in normal),
        "n_normal": len(normal),
        "wrong_no_fault_rate": share(s.status == NO_FAULT for s in fault),
        "n_fault": len(fault),
        "no_fault_precision": share(not s.has_truth for s in rows if s.status == NO_FAULT),
        "no_fault_recall": share(s.status == NO_FAULT for s in normal),
        "by_fold": [
            {
                "fold": f,
                "false_alarm_rate": share(s.status != NO_FAULT for s in members),
                "n_normal": len(members),
            }
            for f, members in per_fold
        ],
    }


type OrderKey = tuple[float, float]


def _verified_key(s: CaseScore) -> OrderKey:
    """V's order, most confident first: status, then margin desc; no status or margin last."""
    rank = STATUS_ORDER.index(s.status) if s.status in STATUS_ORDER else len(STATUS_ORDER)
    return (float(rank), -round(s.margin, DECIMALS) if s.margin is not None else math.inf)


def _fused_key(s: CaseScore) -> OrderKey:
    """F's order: the leader's fused score desc; a row without one last."""
    fused = s.leader_fused_score
    return (0.0, -round(fused, DECIMALS) if fused is not None else math.inf)


def aurc(ranked: Iterable[tuple[OrderKey, bool]]) -> float | None:
    """Area under the risk-coverage curve of (order key, error) pairs, the smallest key answered
    first: the mean over prefixes j of (errors in the first j) / j (04 §7). A block of b tied keys
    with e errors counts t*e/b errors in its t-th prefix, the expectation over the tied orders, so
    the value never depends on row order; None for no rows."""
    blocks: dict[OrderKey, list[int]] = defaultdict(lambda: [0, 0])
    for key, error in ranked:
        blocks[key][0] += 1
        blocks[key][1] += int(error)
    risks: list[float] = []
    answered, errors = 0, 0
    for key in sorted(blocks):
        size, wrong = blocks[key]
        risks.extend((errors + t * wrong / size) / (answered + t) for t in range(1, size + 1))
        answered, errors = answered + size, errors + wrong
    return _mean(risks)


def _risk_coverage(rows: Sequence[CaseScore]) -> dict[str, object]:
    """AURC of the fault rows ordered by V and by F, the error being 1 - AC@1 (04 §7, H3c)."""
    fault = [s for s in rows if s.has_truth]
    verdicts = any(s.has_verdict for s in rows)

    def area(key: Callable[[CaseScore], OrderKey]) -> float | None:
        return aurc((key(s), not s.hit_at(1)) for s in fault) if verdicts else None

    return {"aurc_verdict": area(_verified_key), "aurc_fused": area(_fused_key), "n_fault": len(fault)}


def _selective_accuracy(rows: Sequence[CaseScore]) -> dict[str, object]:
    """AC@1 among the fault rows declared CONFIRMED, and CONFIRMED or LIKELY, with their answer
    rates (04 §7 Selective accuracy, H4b)."""
    fault = [s for s in rows if s.has_truth]
    verdicts = any(s.has_verdict for s in rows)
    out: dict[str, object] = {}
    for name, statuses in (("confirmed", {CONFIRMED}), ("likely_or_better", {CONFIRMED, LIKELY})):
        answered = [s for s in fault if s.status in statuses]
        out[f"ac_at_1_{name}"] = _rate([s.hit_at(1) for s in answered]) if verdicts else None
        out[f"answer_rate_{name}"] = _share(s.status in statuses for s in fault) if verdicts else None
    return out | {"n_fault": len(fault)}


def _variants(rows: Sequence[CaseScore], prefix: str) -> list[tuple[CaseScore, list[CaseScore]]]:
    """(unperturbed row, its `prefix` variants) per (case, seed) that has both (03 §13.2 variant)."""
    base: dict[tuple[str | None, int | None], CaseScore] = {}
    varied: dict[tuple[str | None, int | None], list[CaseScore]] = defaultdict(list)
    for s in rows:
        if s.variant is None:
            base[(s.case_id, s.seed)] = s
        elif s.variant.startswith(prefix):
            varied[(s.case_id, s.seed)].append(s)
    return [(base[k], varied[k]) for k in varied if k in base]


def _top1(s: CaseScore) -> str | None:
    return coarse_service(s.ranks[0]) if s.ranks else None


def _decoy_top1_change(rows: Sequence[CaseScore]) -> dict[str, object]:
    """Share of (case, seed) whose top-1 under any planted proposal differs from the unplanted run's;
    a planted run with no ranks counts as changed (04 §7 Decoy metrics, H2b)."""
    pairs = _variants(rows, PLANT_PREFIX)
    changed = [any(_top1(p) is None or _top1(p) != _top1(b) for p in planted) for b, planted in pairs]
    return {"decoy_top1_change": _share(changed), "n_pairs": len(pairs)}


def _permutation_invariance(rows: Sequence[CaseScore]) -> dict[str, object]:
    """Share of (case, seed) whose verdict_hash is one non-null value across the unpermuted run and
    every permutation (04 §7 Permutation invariance, H2c)."""
    cases = _variants(rows, PERM_PREFIX)
    hashes = [[s.verdict_hash for s in (b, *permuted)] for b, permuted in cases]
    return {
        "permutation_invariance": _share(None not in hs and len(set(hs)) == 1 for hs in hashes),
        "n_cases": len(cases),
    }


type RowEntry = Callable[[Sequence[CaseScore], float], dict[str, object]]
#: The bench_summary 1.2 entries (#404), computed from scores that carry their rows' columns.
ROW_ENTRIES: Mapping[str, RowEntry] = MappingProxyType(
    {
        "coverage": _coverage,
        "set_size": lambda rows, _: _set_size(rows),
        "no_fault_rates": lambda rows, _: _no_fault_rates(rows),
        "risk_coverage": lambda rows, _: _risk_coverage(rows),
        "selective_accuracy": lambda rows, _: _selective_accuracy(rows),
        "decoy_top1_change": lambda rows, _: _decoy_top1_change(rows),
        "permutation_invariance": lambda rows, _: _permutation_invariance(rows),
    }
)


def entries(scores: Iterable[CaseScore], metrics: Collection[str], *, alpha: float) -> dict[str, object]:
    """One group's bench_summary `metrics` object (03 §13.3): every METRIC_KEYS name, its entry when
    `metrics` lists it, else null. `scores` carry their rows' columns (`with_rows`) for the
    ROW_ENTRIES; `alpha` is the experiment's calibration.alpha, for coverage_gap."""
    rows = list(scores)
    flat = summarize(rows, [name for name in metrics if name not in ROW_ENTRIES])
    out: dict[str, object] = {}
    for name, keys in METRIC_KEYS.items():
        if name not in metrics:
            out[name] = None
        elif name in ROW_ENTRIES:
            out[name] = ROW_ENTRIES[name](rows, alpha)
        else:
            out[name] = {key: flat[key] for key in keys}
    return out
