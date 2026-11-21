"""RQ2 and RQ3 tables (11 §5.2, §5.3): Table 6 (proposer lift per benchmark, the H2a comparisons,
the planted-decoy and permutation arms) and Table 7 (calibration).

The experiments come from their YAML's `rq` and protocol, so a new RQ2 or RQ3 experiment gets its
rows without a code change. Table 6 shows the 04 §10.3 floors from the RQ1 experiment of the same
benchmark and alert protocol where the cases match (review M5). Metrics an experiment lists that
bench_summary 1.1 has no entry for (coverage, set size, risk–coverage, NO_FAULT rates, decoy top-1
change, permutation invariance) become "not run" cells that name the missing entry.
"""

from __future__ import annotations

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import Results
from veyltrace_bench.tables.rq1 import ACCURACY, accuracy_table, comparisons, methods
from veyltrace_bench.tables.rq4 import listed

ARMS = {"decoy_top1_change": "n_pairs", "permutation_invariance": "n_cases"}  # entry -> its pair count


def _is_proposal_arm(e: Experiment) -> bool:
    return e.protocol.inject_proposals is not None or e.protocol.permute_proposals is not None


def floor_sources(ctx: Context, exp: Experiment) -> tuple[str | None, str | None]:
    """(prior-only, baseline) experiments for `exp`'s floors: the ACCURACY entry with the same
    dataset parts and alert protocol, or none."""
    for _, _, rq1, prior in ACCURACY:
        spec = ctx.spec(rq1)
        if spec.dataset.parts == exp.dataset.parts and spec.protocol.alert == exp.protocol.alert:
            return prior, rq1
    return None, None


def proposer(ctx: Context) -> list[Table]:
    """Table 6 per RQ2 experiment, the H2a comparisons, and the H2b/H2c proposal arms."""
    tables: list[Table] = []
    for exp in (ctx.spec(e.experiment_id) for e in ctx.experiments):
        if "RQ2" not in exp.rq or _is_proposal_arm(exp):
            continue
        eid = exp.experiment_id
        prior, base = floor_sources(ctx, exp)
        tables.append(
            accuracy_table(ctx, f"t06-rq2-{eid}", f"Table 6: RQ2 proposer, {eid}", eid, prior, base)
        )
    with_comparisons = tuple(
        e.experiment_id for e in ctx.experiments if "RQ2" in e.rq and e.statistics.noninferiority
    )
    tables.append(
        comparisons(ctx, "t06c-rq2-comparisons", "Table 6c: RQ2 comparisons (H2a)", with_comparisons)
    )
    rows: list[Row] = []
    for exp in (ctx.spec(e.experiment_id) for e in ctx.experiments if _is_proposal_arm(e)):
        res = ctx.get(exp.experiment_id)
        for metric in (m for m in exp.metrics if m in ARMS):
            for part in exp.dataset.parts:
                sys = res.system_of(part)
                for m in methods(exp):
                    value = listed(exp, res, metric) or res.metric(part, sys, m, metric, metric)
                    pairs = listed(exp, res, metric) or res.metric(part, sys, m, metric, ARMS[metric])
                    labels = (exp.experiment_id, sys, m, metric)
                    rows.append(Row((*map(cells.text, labels), value, pairs), res))
    caption = (
        "Planted decoy proposals (H2b: share of (case, seed) whose top-1 changed under a planted proposal) "
        "and proposal permutations (H2c: share of (case, seed) with one verdict_hash across permutations); "
        "bench_summary 1.2 entries (03 §13.3). Protocol: see Sources."
    )
    title = "Table 6d: RQ2 planted and permuted proposals"
    columns = ("Experiment", "System", "Method", "Metric", "Value", "Pairs")
    tables.append(Table("t06d-rq2-proposal-arms", title, caption, columns, tuple(rows), key=(0, 1, 2, 3)))
    return tables


#: (column, bench_summary 1.2 entry, key) of Table 7 (03 §13.3, CCR #404); no interval for these.
CALIBRATION = (
    ("AC@1", "ac_at_k", "ac_at_1"), ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"),
    ("Coverage", "coverage", "coverage"), ("Coverage − (1 − alpha)", "coverage", "coverage_gap"),
    ("Coverage given pool", "coverage", "pool_coverage"), ("Mean set size", "set_size", "set_size_mean"),
    ("Singleton share", "set_size", "singleton_share"), ("AURC verifier", "risk_coverage", "aurc_verdict"),
    ("AURC fused", "risk_coverage", "aurc_fused"), ("False-alarm rate", "no_fault_rates", "false_alarm_rate"),
    ("Wrong NO_FAULT rate", "no_fault_rates", "wrong_no_fault_rate"),
)  # fmt: skip
COLUMNS7 = ("Experiment", "Split", "Alpha", "System", "Method", *(c for c, _, _ in CALIBRATION),
            "Fault-case runs (cases × seeds)", "Normal windows")  # fmt: skip


def _calibration_row(exp: Experiment, res: Results, part: str, method: str) -> Row:
    sys = res.system_of(part)
    values = [
        listed(exp, res, entry) or res.metric(part, sys, method, entry, key) for _, entry, key in CALIBRATION
    ]
    counts = [res.count(part, sys, method, k) for k in ("n_fault", "n_no_truth")]
    labels = (
        exp.experiment_id,
        f"{exp.split.scheme} ({exp.split.family})",
        f"{exp.calibration.alpha:g}",
        sys,
        method,
    )
    return Row((*map(cells.text, labels), *values, *counts), res)


def calibration(ctx: Context) -> list[Table]:
    """Table 7: every RQ3 experiment, per system and method."""
    exps = [ctx.spec(e.experiment_id) for e in ctx.experiments if "RQ3" in e.rq]
    rows = [
        _calibration_row(exp, ctx.get(exp.experiment_id), part, m)
        for exp in exps for part in exp.dataset.parts for m in methods(exp)
    ]  # fmt: skip
    alphas = ", ".join(sorted({f"{e.calibration.alpha:g}" for e in exps}))
    caption = (
        f"Held-out folds only (04 §5.4); alpha {alphas} (each experiment's calibration.alpha, Alpha column). "
        "Coverage, set size, risk-coverage AURC (verified score V vs fused score F, H3c) and NO_FAULT "
        "rates are bench_summary 1.2 entries (03 §13.3), pooled over seeds; lower AURC is better. "
        "Protocol: see Sources."
    )
    title = "Table 7: RQ3 calibration"
    return [Table("t07-rq3-calibration", title, caption, COLUMNS7, tuple(rows), key=(0, 3, 4))]
