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
        for metric in (m for m in exp.metrics if m in ("decoy_top1_change", "permutation_invariance")):
            for m in methods(exp):
                cell = listed(exp, res, metric) or cells.not_run("no summary entry")
                rows.append(
                    Row((cells.text(exp.experiment_id), cells.text(m), cells.text(metric), cell), res)
                )
    caption = (
        "Planted decoy proposals (H2b, share of cases whose top-1 changed) and proposal permutations (H2c)."
    )
    title = "Table 6d: RQ2 planted and permuted proposals"
    tables.append(
        Table(
            "t06d-rq2-proposal-arms",
            title,
            caption,
            ("Experiment", "Method", "Metric", "Value"),
            tuple(rows),
            key=(0, 1, 2),
        )
    )
    return tables


CALIBRATION = ("coverage", "set_size", "risk_coverage", "no_fault_rates")
COLUMNS7 = ("Experiment", "Split", "Alpha", "System", "Method", "AC@1", "Retrieval@K", "Coverage",
            "Set size", "Risk-coverage (AURC)", "NO_FAULT rates", "Fault-case runs (cases × seeds)",
            "Normal windows")  # fmt: skip


def _calibration_row(exp: Experiment, res: Results, part: str, method: str) -> Row:
    sys = res.system_of(part)
    acc = [
        listed(exp, res, entry) or res.metric(part, sys, method, entry, key)
        for entry, key in (("ac_at_k", "ac_at_1"), ("retrieval_at_k", "retrieval_at_k"))
    ]
    calib = [listed(exp, res, m) or cells.not_run("no summary entry") for m in CALIBRATION]
    counts = [res.count(part, sys, method, k) for k in ("n_fault", "n_no_truth")]
    labels = (
        exp.experiment_id,
        f"{exp.split.scheme} ({exp.split.family})",
        f"{exp.calibration.alpha:g}",
        sys,
        method,
    )
    return Row((*map(cells.text, labels), *acc, *calib, *counts), res)


def calibration(ctx: Context) -> list[Table]:
    """Table 7: every RQ3 experiment, per system and method."""
    exps = [ctx.spec(e.experiment_id) for e in ctx.experiments if "RQ3" in e.rq]
    rows = [
        _calibration_row(exp, ctx.get(exp.experiment_id), part, m)
        for exp in exps for part in exp.dataset.parts for m in methods(exp)
    ]  # fmt: skip
    alphas = ", ".join(sorted({f"{e.calibration.alpha:g}" for e in exps}))
    caption = (
        f"Held-out folds only (04 §5.4); alpha {alphas} (each experiment's calibration.alpha, Alpha column); "
        "coverage, set size, risk-coverage and NO_FAULT rates need bench_summary entries that 1.1 does not "
        "have. Protocol of each experiment: see Sources."
    )
    title = "Table 7: RQ3 calibration"
    return [Table("t07-rq3-calibration", title, caption, COLUMNS7, tuple(rows), key=(0, 3, 4))]
