"""RQ2 and RQ3 tables (11 §5.2, §5.3): Table 6 (proposer lift per benchmark, the H2a comparisons,
the planted-decoy and permutation arms) and Table 7 (calibration).

The experiments come from their YAML's `rq` and protocol, so a new RQ2 or RQ3 experiment gets its
rows without a code change. Table 6 shows the 04 §10.3 floors from the RQ1 experiment of the same
benchmark and alert protocol where the cases match (review M5). Metrics an experiment lists that
a bench_summary 1.1 file has no entry for (coverage, set size, risk–coverage, NO_FAULT rates, decoy
top-1 change, permutation invariance) become "not run" cells that name the missing entry. Values no
committed file has (a pooled H2b/H2c share, the exploratory verifier vs agent-only comparison, 04
§7 proposal outcomes) say so; the tables compute no new statistics (lead rule R3).
"""

from __future__ import annotations

from dataclasses import replace

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import EXACT_SHARES, Results
from veyltrace_bench.tables.rq1 import (
    ACCURACY,
    COMPARISON_COLUMNS,
    POOLED,
    POOLED_COUNTS,
    accuracy_table,
    comparisons,
    methods,
    n_a,
    no_value,
)
from veyltrace_bench.tables.rq4 import listed

ARMS = EXACT_SHARES  # entry -> its pair count
#: The AC@k keys Table 6d shows for a proposal arm (its YAML's primary metric family, 04 §7).
ARM_AC = ("ac_at_1", "ac_at_3", "ac_at_5")
AC_ENTRY = "ac_at_k"
#: bench_summary keeps the H2b/H2c shares per system only; a pooled share would be a new statistic (R3).
NO_POOLED_SHARE = (
    "no pooled value in the committed results: summary.json reports `{}` per system only "
    "(03 §13.3), and the tables compute no new statistics (R3)"
)
#: 04 §7 "Proposal outcomes" have no bench_summary entry, so Table 6 says so instead of a column.
PROPOSAL_OUTCOMES = (
    " Proposal outcomes (admitted, accepted, rejection reasons; 04 §7) are not tabulated: summary.json "
    "has no proposal-outcome entry (03 §13.3), so they need a contract change; Pool retrieval is the "
    "decision-pool retrieval."
)
#: 04 §2 RQ2 and the experiment's YAML header name verifier vs agent-only exploratory; summary.json
#: has a comparison only where its statistics block computed one, so a missing pair says so (R1).
EXPLORATORY = "exploratory"
NO_EXPLORATORY = (
    "no value in the committed results: summary.json statistics has no {a} − {b} comparison; 04 §2 RQ2 "
    "names verifier vs agent-only exploratory (unadjusted, 04 §8), and the tables compute no new "
    "statistics (R3)"
)
SEEDED_MCNEMAR = "a seeded arm's per-case hit is a mean over seeds, not boolean, so no McNemar (04 §8)"
UNADJUSTED = "no Holm family: non-inferiority and exploratory comparisons are unadjusted (04 §8)"


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


def _proposes(exp: Experiment) -> bool:
    """Whether a verifier arm of the experiment takes LLM proposals (04 §7 proposal outcomes)."""
    return any(m.kind == "veyltrace" and m.ai.seeds for m in exp.methods)


def exploratory_pairs(exp: Experiment) -> list[tuple[str, str]]:
    """(verifier arm, agent-only arm) with the same Relentra mode: 04 §2 RQ2's exploratory pair."""
    arms = [m for m in exp.methods if m.ai.seeds]
    return [
        (a.id, b.id)
        for a in arms if a.kind == "veyltrace"
        for b in arms if b.kind == "agent_only" and b.ai.relentra_mode == a.ai.relentra_mode
    ]  # fmt: skip


def _exploratory_rows(ctx: Context, eid: str) -> list[Row]:
    """A "no value" row per scope for each exploratory pair summary.json has no comparison of."""
    res, exp = ctx.get(eid), ctx.spec(eid)
    if res.summary is None or isinstance(stats := res.summary.statistics, str):
        return []  # the experiment's comparison rows already say why it has none
    done = {frozenset((c.method_a, c.method_b)) for c in stats.comparisons}
    bench = exp.dataset.parts[0].split("-")[0]
    scopes = [f"{p} {res.system_of(p)}" for p in exp.dataset.parts] + [f"{bench} {POOLED}"]
    rows: list[Row] = []
    for a, b in (p for p in exploratory_pairs(exp) if frozenset(p) not in done):
        gap, mcnemar = no_value(NO_EXPLORATORY.format(a=a, b=b)), n_a(SEEDED_MCNEMAR)
        labels = (exp.statistics.primary_metric, f"{a} − {b}", EXPLORATORY, "none")
        body: tuple[Cell, ...] = (*map(cells.text, labels), *[gap] * 4, mcnemar, mcnemar, n_a(UNADJUSTED))
        rows += [Row((cells.text(scope), *body), res) for scope in scopes]
    assert all(len(r.cells) == len(COMPARISON_COLUMNS) for r in rows)
    return rows


def _arm_rows(ctx: Context, exp: Experiment) -> list[Row]:
    """Table 6d's rows of one proposal-arm experiment: the H2b/H2c shares it lists per system and
    pooled, then its AC@k per system and pooled (summary.json intervals, 04 §8)."""
    res, eid, rows = ctx.get(exp.experiment_id), exp.experiment_id, list[Row]()
    for metric in (m for m in exp.metrics if m in ARMS):
        for part in exp.dataset.parts:
            sys = res.system_of(part)
            for m in methods(exp):
                value = listed(exp, res, metric) or res.metric(part, sys, m, metric, metric)
                pairs = listed(exp, res, metric) or res.metric(part, sys, m, metric, ARMS[metric])
                rows.append(Row((*map(cells.text, (eid, sys, m, metric)), value, pairs), res))
        for m in methods(exp):
            why = res.why(m)
            gap = cells.not_run(why) if why is not None else no_value(NO_POOLED_SHARE.format(metric))
            rows.append(Row((*map(cells.text, (eid, POOLED, m, metric)), gap, gap), res))
    if AC_ENTRY not in exp.metrics:
        return rows
    for part in exp.dataset.parts:
        sys = res.system_of(part)
        for m in methods(exp):
            runs = res.count(part, sys, m, "n_fault")
            for key in ARM_AC:
                value = res.metric(part, sys, m, AC_ENTRY, key)
                rows.append(Row((*map(cells.text, (eid, sys, m, key)), value, runs), res))
    bench = exp.dataset.parts[0].split("-")[0]
    for m in methods(exp):
        for key in ARM_AC:
            pooled = res.pooled(bench, m, key)
            rows.append(Row((*map(cells.text, (eid, POOLED, m, key)), pooled, n_a(POOLED_COUNTS)), res))
    return rows


def proposer(ctx: Context) -> list[Table]:
    """Table 6 per RQ2 experiment, the H2a comparisons with the exploratory pairs, and the H2b/H2c
    proposal arms."""
    tables: list[Table] = []
    for exp in (ctx.spec(e.experiment_id) for e in ctx.experiments):
        if "RQ2" not in exp.rq or _is_proposal_arm(exp):
            continue
        eid = exp.experiment_id
        prior, base = floor_sources(ctx, exp)
        note = PROPOSAL_OUTCOMES if _proposes(exp) else ""
        title = f"Table 6: RQ2 proposer, {eid}"
        tables.append(accuracy_table(ctx, f"t06-rq2-{eid}", title, eid, prior, base, note))
    with_comparisons = tuple(
        e.experiment_id for e in ctx.experiments if "RQ2" in e.rq and e.statistics.noninferiority
    )
    h2a = comparisons(ctx, "t06c-rq2-comparisons", "Table 6c: RQ2 comparisons (H2a)", with_comparisons)
    extra = [r for eid in with_comparisons for r in _exploratory_rows(ctx, eid)]
    caption = h2a.caption.removesuffix(" Protocol: see Sources.") + (
        " Exploratory rows (04 §2 RQ2, verifier vs agent-only) are unadjusted (04 §8). Protocol: see Sources."
    )
    tables.append(replace(h2a, caption=caption, rows=(*h2a.rows, *extra)))
    arms = [ctx.spec(e.experiment_id) for e in ctx.experiments if _is_proposal_arm(e)]
    rows = [r for exp in arms for r in _arm_rows(ctx, exp)]
    caption = (
        "Planted decoy proposals (H2b: share of (case, seed) whose top-1 changed under a planted proposal) "
        "and proposal permutations (H2c: share of (case, seed) with one verdict_hash across permutations), "
        "bench_summary 1.2 entries (03 §13.3), with 95% exact (Clopper–Pearson) binomial intervals over the "
        "(case, seed) pairs in brackets, as 04 §2 RQ2 pre-registers for H2b and H2c (04 §8 lists decoy "
        "flips under cluster-bootstrap intervals where clusters exist; no committed file has a "
        "case-clustered interval for them). AC@k of each arm with its 95% cluster-bootstrap interval "
        "(04 §8); on an AC@k row, Pairs is the group's fault-case runs (n_fault: cases × seeds, times the "
        "unpermuted run and its permutations on a permute arm). The unperturbed arms are in Table 6 "
        "(re2-oracle-rq2-v1). Protocol: see Sources."
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
