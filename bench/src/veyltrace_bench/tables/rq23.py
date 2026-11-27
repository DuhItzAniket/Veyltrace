"""RQ2 and RQ3 tables (11 §5.2, §5.3): Table 6 (proposer lift per benchmark, the H2a comparisons,
the planted-decoy and permutation arms) and Table 7 (calibration per system and pooled, 7b per
held-out fold, 7c the literal τ_nf sensitivity analysis).

The experiments come from their YAML's `rq` and protocol, so a new RQ2 or RQ3 experiment gets its
rows without a code change. Table 6 shows the 04 §10.3 floors from the RQ1 experiment of the same
benchmark and alert protocol where the cases match (review M5). Metrics an experiment lists that
a bench_summary 1.1 file has no entry for (coverage, set size, risk–coverage, NO_FAULT rates, decoy
top-1 change, permutation invariance) become "not run" cells that name the missing entry. Values no
committed file has (a pooled H2b/H2c share, the exploratory verifier vs agent-only comparison, 04
§7 proposal outcomes) say so; the tables compute no new statistics (04 §10.2).
"""

from __future__ import annotations

from dataclasses import replace

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import (
    CASE_MEAN,
    EXACT_SHARES,
    NO_INTERVAL,
    POOLED_SCOPE,
    RQ3_TOLERANCE,
    Results,
)
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
from veyltrace_core.errors import ConfigError

ARMS = EXACT_SHARES  # entry -> its pair count
#: The AC@k keys Table 6d shows for a proposal arm (its YAML's primary metric family, 04 §7).
ARM_AC = ("ac_at_1", "ac_at_3", "ac_at_5")
AC_ENTRY = "ac_at_k"
#: bench_summary keeps the H2b/H2c shares per system only; a pooled share would be a new statistic.
NO_POOLED_SHARE = (
    "no pooled value in the committed results: summary.json reports `{}` per system only "
    "(03 §13.3), and the tables compute no new statistics (04 §10.2)"
)
#: 04 §7 "Proposal outcomes" have no bench_summary entry, so Table 6 says so instead of a column.
PROPOSAL_OUTCOMES = (
    " Proposal outcomes (admitted, accepted, rejection reasons; 04 §7) are not tabulated: summary.json "
    "has no proposal-outcome entry (03 §13.3), so they need a contract change; Pool retrieval is the "
    "decision-pool retrieval."
)
#: 04 §2 RQ2 and the experiment's YAML header name verifier vs agent-only exploratory; summary.json
#: has a comparison only where its statistics block computed one, so a missing pair says so.
EXPLORATORY = "exploratory"
NO_EXPLORATORY = (
    "no value in the committed results: summary.json statistics has no {a} − {b} comparison; 04 §2 RQ2 "
    "names verifier vs agent-only exploratory (unadjusted, 04 §8), and the tables compute no new "
    "statistics (04 §10.2)"
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


#: (column, bench_summary 1.2 entry, key) of Table 7 (03 §13.3, CCR #404, 04 §7 Coverage, Set size,
#: NO_FAULT rates). AC@1 and Retrieval@K take summary.json's bootstrap interval; coverage, the AURCs
#: and the NO_FAULT rates take rq3-intervals'; the other values say they have none.
CALIBRATION = (
    ("AC@1", "ac_at_k", "ac_at_1"), ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"),
    ("Coverage", "coverage", "coverage"), ("Coverage − (1 − alpha)", "coverage", "coverage_gap"),
    ("Coverage given pool", "coverage", "pool_coverage"), ("Mean set size", "set_size", "set_size_mean"),
    ("Median set size", "set_size", "set_size_median"), ("Singleton share", "set_size", "singleton_share"),
    ("AURC verifier", "risk_coverage", "aurc_verdict"), ("AURC fused", "risk_coverage", "aurc_fused"),
)  # fmt: skip
NO_FAULT = (
    ("False-alarm rate", "no_fault_rates", "false_alarm_rate"),
    ("Wrong NO_FAULT rate", "no_fault_rates", "wrong_no_fault_rate"),
    ("NO_FAULT precision", "no_fault_rates", "no_fault_precision"),
    ("NO_FAULT recall", "no_fault_rates", "no_fault_recall"),
)
RISK, DIFFERENCE = "risk_coverage", "aurc_difference"  # H3c: AURC(V) − AURC(F), rq3-intervals only
COUNTS7 = ("Fault-case runs (cases × seeds)", "Runs with a set", "Unranked", "Runs not ok", "Normal windows")
COLUMNS7 = ("Experiment", "Split", "Alpha", "System", "Method", *(c for c, _, _ in CALIBRATION),
            "AURC V − F", *(c for c, _, _ in NO_FAULT), *COUNTS7)  # fmt: skip
NOT_OK = ("failed", "rejected", "timeout", "no_alert")  # summary outcomes other than ok (03 §13.3)
NO_DIFFERENCE = (
    "no value in the committed results: AURC V − F and its interval are in rq3-intervals/<id>/summary.json "
    "(`aurc_difference`), and no such file is committed for this experiment; the tables compute no new "
    "statistics (04 §10.2)"
)
NO_POOLED_RQ3 = (
    "no pooled value in the committed results: summary.json reports `{}` per system only and no "
    "rq3-intervals file has a pooled one; the tables compute no new statistics (04 §10.2)"
)
NO_NORMAL = (
    "undefined: the experiment has no normal windows (dataset.normal_windows: none), so the rate has "
    "no denominator"
)
NO_DECLARED = (
    "undefined: no run declared NO_FAULT (false-alarm rate 1, wrong NO_FAULT rate 0), so the precision "
    "has no denominator (03 §13.3)"
)
NO_FOLDS = "the experiment does not list `coverage`, so it has no folds"


def _bench(exp: Experiment) -> str:
    return exp.dataset.parts[0].split("-")[0]


def _labels(exp: Experiment, system: str, method: str) -> tuple[Cell, ...]:
    split = f"{exp.split.scheme} ({exp.split.family})"
    return tuple(map(cells.text, (exp.experiment_id, split, f"{exp.calibration.alpha:g}", system, method)))


def _undefined(res: Results, part: str, sys: str, method: str, key: str, cell: Cell) -> Cell:
    """A null NO_FAULT rate says why it is undefined when the summary shows it."""
    group = res.group(part, sys, method)
    rates = group.metrics.no_fault_rates if group is not None else None
    if cell.note != cells.UNDEFINED_NOTE or rates is None:
        return cell
    if key in ("false_alarm_rate", "no_fault_recall") and rates.n_normal == 0:
        return Cell(cells.UNDEFINED, NO_NORMAL)
    if (
        key == "no_fault_precision"
        and rates.wrong_no_fault_rate == 0
        and rates.false_alarm_rate in (1.0, None)
    ):
        return Cell(cells.UNDEFINED, NO_DECLARED)
    return cell


def _difference(exp: Experiment, res: Results, scope: str, why: str | None, areas: tuple[float, ...]) -> Cell:
    """AURC V − F (H3c) with its rq3-intervals interval; it must equal the two areas' difference."""
    if (gap := listed(exp, res, RISK)) is not None:
        return gap
    if why is not None:
        return cells.not_run(why)
    if (found := res.side_bounds(scope, DIFFERENCE)) is None:
        return no_value(NO_DIFFERENCE)
    if len(areas) == 2 and abs(found[0] - (areas[0] - areas[1])) > 2 * RQ3_TOLERANCE:
        raise ConfigError(f"rq3-intervals {scope} {DIFFERENCE} {found[0]!r} is not summary.json's AURC V − F")
    return cells.rate(found[0], (found[1], found[2]))


def _not_ok(res: Results, part: str, sys: str, method: str) -> Cell:
    """The group's runs that are not ok, by outcome (04 §10 rule 5), or "none"."""
    if (why := res.missing(part, sys, method)) is not None:
        return cells.not_run(why)
    group = res.group(part, sys, method)
    assert group is not None
    found = [
        f"{k.replace('_', ' ')} {getattr(group.outcomes, k)}" for k in NOT_OK if getattr(group.outcomes, k)
    ]
    return cells.text(", ".join(found) or "none")


def _calibration_row(exp: Experiment, res: Results, part: str, method: str) -> Row:
    sys = res.system_of(part)
    values = [listed(exp, res, e) or res.metric(part, sys, method, e, k) for _, e, k in CALIBRATION]
    rates = [
        listed(exp, res, e) or _undefined(res, part, sys, method, k, res.metric(part, sys, method, e, k))
        for _, e, k in NO_FAULT
    ]
    group = res.group(part, sys, method)
    risk = group.metrics.risk_coverage if group is not None else None
    areas = (risk.aurc_verdict, risk.aurc_fused) if risk is not None else (None, None)
    known = tuple(a for a in areas if a is not None)
    diff = _difference(exp, res, sys, res.missing(part, sys, method), known)
    counts = [
        res.count(part, sys, method, "n_fault"),
        listed(exp, res, "set_size") or res.metric(part, sys, method, "set_size", "n_set"),
        res.count(part, sys, method, "n_unranked"),
        _not_ok(res, part, sys, method),
        res.count(part, sys, method, "n_no_truth"),
    ]
    return Row((*_labels(exp, sys, method), *values, diff, *rates, *counts), res)


def _pooled_cell(exp: Experiment, res: Results, method: str, entry: str, key: str) -> Cell:
    """A pooled estimate (system as stratum) from summary.json or rq3-intervals, else why none."""
    if (gap := listed(exp, res, entry)) is not None:
        return gap
    if (why := res.why(method)) is not None:
        return cells.not_run(why)
    if key in ("false_alarm_rate", "no_fault_recall") and exp.dataset.normal_windows == "none":
        return Cell(cells.UNDEFINED, NO_NORMAL)
    if key in CASE_MEAN or (res.rq3 is not None and (POOLED_SCOPE, key) in res.rq3.intervals):
        return res.pooled(_bench(exp), method, key)
    return no_value(NO_POOLED_RQ3.format(key))


def _pooled_row(exp: Experiment, res: Results, method: str) -> Row:
    values = [_pooled_cell(exp, res, method, e, k) for _, e, k in (*CALIBRATION, *NO_FAULT)]
    diff = _difference(exp, res, POOLED_SCOPE, res.why(method), ())
    body = (*values[: len(CALIBRATION)], diff, *values[len(CALIBRATION) :])
    why = res.why(method)
    counts = cells.not_run(why) if why is not None else n_a(POOLED_COUNTS)
    return Row((*_labels(exp, POOLED, method), *body, *[counts] * len(COUNTS7)), res)


def _has_rows(res: Results) -> bool:
    """Whether an experiment gets pooled, fold and τ_nf rows: it has results, or a revision replaces
    it (whose pass fills them, generate.paired); a not-run experiment shows its reason in Table 7."""
    return res.reason is None or bool(res.revised_as)


def _fold_rows(exp: Experiment, res: Results, part: str, method: str) -> list[Row]:
    """Table 7b: coverage and false-alarm rate per held-out fold (04 §7 "per system, per fold")."""
    sys = res.system_of(part)
    every = _labels(exp, sys, method)
    labels = (*every[:2], *every[3:])  # no Alpha column
    if (why := res.missing(part, sys, method)) is not None:
        return [Row((*labels, *[cells.not_run(why)] * 5), res)]
    group = res.group(part, sys, method)
    assert group is not None
    cov, nf = group.metrics.coverage, group.metrics.no_fault_rates
    if cov is None:
        return [Row((*labels, *[n_a(NO_FOLDS)] * 5), res)]
    normal = {f.fold: f for f in nf.by_fold} if nf is not None else {}
    rows: list[Row] = []
    for fold in cov.by_fold:
        windows = normal.get(fold.fold)
        if windows is None:
            n, alarm = (n_a("the experiment does not list `no_fault_rates`"),) * 2
        elif windows.n_normal == 0:
            n, alarm = cells.count(0), Cell(cells.UNDEFINED, NO_NORMAL)
        else:
            n, alarm = cells.count(windows.n_normal), cells.rate(windows.false_alarm_rate, note=NO_INTERVAL)
        cover = cells.rate(fold.coverage, note=NO_INTERVAL)
        rows.append(Row((*labels, cells.text(fold.fold), cells.count(fold.n_fault), cover, n, alarm), res))
    return rows


COLUMNS7B = ("Experiment", "Split", "System", "Method", "Held-out fold", "Fault-case runs", "Coverage",
             "Normal windows", "False-alarm rate")  # fmt: skip
TAU_FIT = ("tau_nf_literal", "lands_on_infinity", "n_never", "m_literal", "m_fitted")  # rq3-intervals keys
TAU_RATES = ("false_alarm_rate", "wrong_no_fault_rate")
COLUMNS7C = ("Experiment", "Method", "Scope", "τ_nf (literal)", "Index lands on +∞",
             "Windows never NO_FAULT", "m (literal)", "m (fitted)", "False-alarm rate (literal τ_nf)",
             "Wrong NO_FAULT rate (literal τ_nf)", "False-alarm rate (Table 7)",
             "Wrong NO_FAULT rate (Table 7)")  # fmt: skip
FOLD_ROW = "a held-out fold's fit; the rates are per system and pooled (the rows that follow)"
RATE_ROW = "a rate row; τ_nf and m are per held-out fold (the rows before)"
NO_LITERAL = (
    "no value in the committed results: the literal τ_nf analysis is in rq3-intervals/<id>/summary.json "
    "(`literal_tau_sensitivity`), and no such file is committed for this experiment"
)


def _fit_cell(fit: dict[str, object], key: str) -> Cell:
    value = fit.get(key)
    if isinstance(value, bool):
        return cells.text("yes" if value else "no")
    if key == "tau_nf_literal" and isinstance(value, int | float):
        return cells.text(cells.fixed(float(value)))
    if isinstance(value, int):
        return cells.count(value)
    raise ConfigError(f"rq3-intervals {key} {value!r} is not a number or a flag")


def _tau_rows(exp: Experiment, res: Results) -> list[Row]:
    """Table 7c: the literal 04 §5.4 τ_nf (04 §12 row of 2026-11-21) per held-out fold, then its
    NO_FAULT rates per system and pooled next to Table 7's, each with its rq3-intervals interval."""
    method = methods(exp)[0]
    head = tuple(map(cells.text, (exp.experiment_id, method)))
    width = len(COLUMNS7C) - 3
    if (why := res.why(method)) is not None:
        return [Row((*head, cells.text("all"), *[cells.not_run(why)] * width), res)]
    if res.rq3 is None or not res.rq3.held_out:
        return [Row((*head, cells.text("all"), *[no_value(NO_LITERAL)] * width), res)]
    rows = [
        Row(
            (
                *head,
                cells.text(f"held-out {fold}"),
                *(_fit_cell(fit, k) for k in TAU_FIT),
                *[n_a(FOLD_ROW)] * 4,
            ),
            res,
        )
        for fold, fit in res.rq3.held_out
    ]
    scopes: list[tuple[str | None, str]] = [(p, res.system_of(p)) for p in exp.dataset.parts]
    for part, scope in [*scopes, (None, POOLED_SCOPE)]:
        literal = [res.rq3.literal.get((scope, k)) for k in TAU_RATES]
        shown = [cells.rate(b[0], (b[1], b[2])) if b else no_value(NO_LITERAL) for b in literal]
        main = [
            res.pooled(_bench(exp), method, k)
            if part is None
            else res.metric(part, scope, method, "no_fault_rates", k)
            for k in TAU_RATES
        ]
        rows.append(Row((*head, cells.text(scope), *[n_a(RATE_ROW)] * 5, *shown, *main), res))
    return rows


def calibration(ctx: Context) -> list[Table]:
    """Table 7: every RQ3 experiment, per system and pooled; Table 7b: per held-out fold; Table 7c:
    the literal τ_nf sensitivity analysis."""
    specs = (ctx.spec(e.experiment_id) for e in ctx.experiments)
    exps = [(exp, ctx.get(exp.experiment_id)) for exp in specs if "RQ3" in exp.rq]
    rows: list[Row] = []
    for exp, res in exps:
        rows += [_calibration_row(exp, res, part, m) for part in exp.dataset.parts for m in methods(exp)]
        rows += [_pooled_row(exp, res, m) for m in methods(exp)] if _has_rows(res) else []
    alphas = ", ".join(sorted({f"{e.calibration.alpha:g}" for e, _ in exps}))
    caption = (
        f"Held-out folds only (04 §5.4); alpha {alphas} (each experiment's calibration.alpha, Alpha column). "
        "Coverage, set size, risk-coverage AURC (verified score V vs fused score F; H3c: AURC V − F below 0 "
        "favours V) and NO_FAULT rates are bench_summary 1.2 entries (03 §13.3), pooled over seeds; lower "
        "AURC is better. AC@1 and Retrieval@K carry summary.json's 95% cluster-bootstrap interval; coverage, "
        "the AURCs, AURC V − F and the false-alarm and wrong NO_FAULT rates carry the 95% cluster-bootstrap "
        "interval of rq3-intervals/<id>/summary.json where one is committed (scripts/rq3_intervals.py, #555; "
        "04 §8). Set-size columns are over the runs with a set; Runs not ok counts all the group's rows "
        "(fault cases and normal windows). τ_nf follows the 04 §12 row of 2026-11-21 (logged 26 Nov; ADR "
        "20261121-ak-calibration-fit-conventions): when its rank index lands on +∞, τ_nf = default_tau with "
        "calibrated = false, which gives a held-out false-alarm rate of 1; Table 7c is the literal 04 §5.4 "
        "reading that row reports as a sensitivity analysis. Pooled rows (system as stratum) are secondary "
        "(04 §10 rule 3). Protocol: see Sources."
    )
    folds = [
        r for exp, res in exps if _has_rows(res)
        for p in exp.dataset.parts for m in methods(exp) for r in _fold_rows(exp, res, p, m)
    ]  # fmt: skip
    caption_b = (
        "Coverage and false-alarm rate per held-out fold (04 §7: per system, per fold, pooled over folds; "
        "Table 7 has the values pooled over folds), bench_summary 1.2 `by_fold` entries (03 §13.3). No "
        "committed file has a per-fold interval (04 §8 asks for one). Experiments without results are in "
        "Table 7. Protocol: see Sources."
    )
    taus = [
        r for exp, res in exps if _has_rows(res) and exp.dataset.normal_windows != "none"
        for r in _tau_rows(exp, res)
    ]  # fmt: skip
    caption_c = (
        "Sensitivity analysis of the 04 §12 row of 2026-11-21 (logged 26 Nov; ADR "
        "20261121-ak-calibration-fit-conventions), computed after the results: τ_nf as the literal 04 §5.4 "
        "rule gives it, without the +∞ fallback, per held-out fold (windows that can never be NO_FAULT and "
        "m as rq3-intervals records them), then the false-alarm and wrong NO_FAULT rates it gives per "
        "system and pooled, with 95% cluster-bootstrap intervals (rq3-intervals/<id>/summary.json "
        "`literal_tau_sensitivity`), next to Table 7's. Experiments without normal windows have no "
        "τ_nf. Protocol: see Sources."
    )
    t7 = Table(
        "t07-rq3-calibration", "Table 7: RQ3 calibration", caption, COLUMNS7, tuple(rows), key=(0, 3, 4)
    )
    t7b = Table("t07b-rq3-folds", "Table 7b: RQ3 per held-out fold", caption_b, COLUMNS7B, tuple(folds))
    t7c = Table("t07c-rq3-tau-sensitivity", "Table 7c: RQ3 literal τ_nf", caption_c, COLUMNS7C, tuple(taus))
    return [t7, t7b, t7c]
