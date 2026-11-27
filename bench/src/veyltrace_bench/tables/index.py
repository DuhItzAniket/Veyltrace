"""Table A0, every reportable experiment of the 04 §6 matrix and whether it ran (R-16 fills each
cell or marks it "not run" with a reason; 04 §10.8), and Table A2, the development cases, which no
test table includes and which are reported separately (04 §1, §10.5).

A0 lists every committed results folder (R4): the experiments, then the side results (RQ3
intervals, replay sites, AI cost, Observe's performance sample), then the 04 §6 cells that only the
register names or that nothing covers. "Not run" is kept for a cut experiment or cell (R1); a
revised pre-registered experiment says which revision replaces it, and results in an older summary
minor say they ran but are not tabulated (R5).
"""

from __future__ import annotations

import pyarrow as pa

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.summary import METRIC_KEYS
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.context import CELLS, DEV_CASES, Context, Side
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import ENTRY_OF, EXACT_SHARES, PER_CASE, Replay, Results
from veyltrace_contracts.models import SummaryGroupMetrics
from veyltrace_core import io
from veyltrace_core.errors import ConfigError

NO_DEV_REPORT = "no committed per_case.csv has a row for this case; it is reported separately (04 §1)"
DASH = "-"
NOT_BENCH = "not bench output: the folder has no summary.json"
NO_COVER = (
    "no experiment YAML covers it and not_run.yaml gives no reason (04 §6: R-16 fills or marks every cell)"
)
#: 04 §6 columns by method kind; a veyltrace method's column is its Relentra mode.
KIND_COLUMN = {"rcaeval": "baselines", "internal_baseline": "baselines", "causatrix": "rankers",
               "agent_only": "agent-only"}  # fmt: skip


def matrix_row(exp: Experiment) -> str:
    """The 04 §6 row an experiment fills, from its protocol: the perturbation it applies, else its
    calibration scheme, normal windows or alert, else its benchmark under the oracle alert."""
    bench, p, split = exp.dataset.parts[0].split("-", 1)[0], exp.protocol, exp.split.scheme
    checks = (
        (split == "transfer", f"re2-to-{bench}"),
        (p.decoys is not None, "rcaevalc-decoy-grid"),
        (p.inject_proposals is not None or p.permute_proposals is not None, f"{bench}-proposal-decoys"),
        (p.shift_s != 0, f"{bench}-onset-shift"),
        (bool(p.sources_drop), f"{bench}-telemetry-ablation"),
        (split == "loso", f"{bench}-loso"),
        (bench == "re2" and exp.dataset.normal_windows != "none", f"{bench}-calibration"),
        (p.alert == "detected", f"{bench}-detected"),
    )
    return next((row for hit, row in checks if hit), f"{bench}-oracle")


def covered(exp: Experiment) -> set[str]:
    """The 04 §6 cells `exp` fills: its row, one column per method."""
    row = matrix_row(exp)
    cols = {KIND_COLUMN.get(m.kind) or (m.ai.relentra_mode or "off") for m in exp.methods}
    return {f"{row}/{col}" for col in cols}


def _without_interval(res: Results) -> list[str]:
    """The summary entries with a value in some group but no interval in any committed file
    (summary.json, rq3-intervals; the shares the tables give an exact interval excepted), R3."""
    if res.summary is None or isinstance(stats := res.summary.statistics, str):
        return []
    have = {ENTRY_OF.get(i.metric) for i in stats.intervals}
    have |= {ENTRY_OF.get(metric) for _, metric in (res.rq3.intervals if res.rq3 else {})}
    valued: set[str] = set()
    for group in res.summary.groups:
        for entry in SummaryGroupMetrics.model_fields:
            if (values := getattr(group.metrics, entry)) is None:
                continue
            keys = [k for k in METRIC_KEYS.get(entry, ()) if not k.startswith("n_") and k != "retrieval_k"]
            if any(getattr(values, k, None) is not None for k in keys):
                valued.add(entry)
    return sorted(valued - have - set(EXACT_SHARES))


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _statistics(res: Results, status: cells.Cell) -> cells.Cell:
    """The summary's interval, comparison and not-run counts, the RQ3 intervals beside it, and the
    metrics no committed file gives an interval (R3); `status` when there is no summary."""
    if res.old is not None:
        found = res.old.statistics or "no statistics string"
        return cells.Cell("none", f"bench_summary {res.old.version} statistics: {found}")
    if res.summary is None:
        return status
    if res.stats_reason is not None:
        return cells.not_run(res.stats_reason)
    stats = res.summary.statistics
    assert not isinstance(stats, str)
    counts = (len(stats.intervals), len(stats.comparisons), len(stats.not_run))
    text = "{} intervals, {} comparisons, {} not run".format(*counts)
    if res.rq3 is not None:
        text += f"; + {_plural(len(res.rq3.intervals), 'RQ3 interval')} ({res.rq3.name})"
    if missing := _without_interval(res):
        text += f"; {_plural(len(missing), 'metric')} without interval ({', '.join(missing)})"
    return cells.text(text)


def _status(exp: Experiment, res: Results) -> cells.Cell:
    if res.summary is not None:
        return cells.text("run")
    if res.old is not None:
        return cells.Cell(f"run (bench_summary {res.old.version})", res.reason)
    why = res.reason or "no results"
    ran = res.revision_methods  # the arms of the pre-registered experiment its revisions drop
    if ran is not None and (dropped := sorted({m.id for m in exp.methods} - ran)):
        why += f"; the revision does not run {', '.join(dropped)}"
    return cells.not_run(why)


def _experiment_row(ctx: Context, exp: Experiment) -> Row:
    res = ctx.get(exp.experiment_id)
    status = _status(exp, res)
    if res.summary is not None:
        groups = cells.count(len(res.summary.groups))
    elif res.old is not None:
        groups = cells.count(res.old.groups)
    else:
        groups = status
    labels = (exp.experiment_id, ", ".join(exp.rq) or DASH, "yes" if exp.prereg else "no")
    return Row((*map(cells.text, labels), status, groups, _statistics(res, status)), res)


def _side_row(side: Side) -> Row:
    na = cells.not_applicable(NOT_BENCH)
    stats = (
        cells.text(
            f"{_plural(len(side.rq3.intervals), 'interval')} ({side.rq3.level:.0%} cluster bootstrap, "
            f"{side.rq3.resamples} resamples)"
        )
        if side.rq3 is not None
        else na
    )
    name = side.source.experiment_id
    return Row(
        (cells.text(name), cells.text(side.rq), cells.text(DASH), cells.text("run"), na, stats), side.source
    )


def _replay_row(replay: Replay) -> Row:
    src, summary = replay.source, replay.summary
    if summary is None:
        blank = cells.not_run(src.reason or "no result")
        return Row(
            (cells.text(src.experiment_id), cells.text("RQ6"), cells.text(DASH), blank, blank, blank), src
        )
    tiers = [t for t, got in (("Tier 1", summary.tier1), ("Tier 2", summary.tier2)) if got is not None]
    na = cells.not_applicable("a replay summary has no groups (03 §13.5)")
    stats = cells.text(f"{_plural(len(tiers), 'interval')} ({' and '.join(tiers)}, exact binomial)")
    return Row(
        (cells.text(src.experiment_id), cells.text("RQ6"), cells.text(DASH), cells.text("run"), na, stats),
        src,
    )


def _cell_row(cell: str, blank: cells.Cell) -> Row:
    return Row(
        (cells.text(f"04 §6 cell {cell}"), cells.text(DASH), cells.text(DASH), blank, blank, blank), None
    )


def results_index(ctx: Context) -> list[Table]:
    rows = [_experiment_row(ctx, exp) for exp in ctx.experiments]
    rows += [_side_row(side) for side in ctx.sides]
    rows += [_replay_row(replay) for _, replay in sorted(ctx.replays.items())]
    rows += [_cell_row(cell, cells.not_run(reason)) for cell, reason in sorted(ctx.cells.items())]
    filled = {c for exp in ctx.experiments for c in covered(exp)}
    rows += [_cell_row(cell, cells.not_run(NO_COVER)) for cell in sorted(CELLS - filled - set(ctx.cells))]
    caption = (
        "Every experiment YAML in bench/experiments (synth smoke excluded) and the state of its "
        "committed results; then the other committed results folders (RQ3 intervals, replay sites, "
        "AI cost, performance samples); then the 04 §6 matrix cells that only bench/results/not_run.yaml "
        "names or that no experiment YAML covers."
    )
    columns = ("Experiment", "RQ", "Pre-registered", "Status", "Groups", "Statistics")
    return [Table("a0-results-index", "Table A0: results index", caption, columns, tuple(rows))]


def _dev_rows(ctx: Context) -> dict[str, list[tuple[Results, dict[str, object]]]]:
    """The per_case.csv rows of the development cases, by case, from every committed experiment
    that kept them (an older summary minor included, R5), in experiment order."""
    dev = set(ctx.dev_cases or ())
    found: dict[str, list[tuple[Results, dict[str, object]]]] = {case: [] for case in sorted(dev)}
    for exp in ctx.experiments:
        res = ctx.get(exp.experiment_id)
        if res.path is None or (res.reason is not None and res.old is None):
            continue
        if res.manifest is not None and not dev & {c for d in res.manifest.datasets for c in d.cases}:
            continue  # the manifest shows it ran none of them
        table = io.read_path("bench_result", res.path / PER_CASE, validate=True)
        if not isinstance(table, pa.Table):  # bench_result is a CSV contract, so io returns a table
            raise ConfigError(f"{PER_CASE} of {res.experiment_id} did not read as a table")
        for row in table.to_pylist():
            if (case := str(row["case_id"])) in dev:
                found[case].append((res, row))
    return found


def _hit(row: dict[str, object], k: int) -> cells.Cell:
    value = row[f"hit_at_{k}"]
    return cells.count(int(value)) if isinstance(value, bool | int) else cells.rate(None)


def development_cases(ctx: Context) -> list[Table]:
    """Table A2: the development cases' rows in committed per_case.csv files, reported apart from
    every test table (04 §1); a case no committed file has says so."""
    columns = ("Case", "Dataset", "Method", "Outcome", "Hit@1", "Hit@3", "Hit@5")
    if ctx.dev_cases is None:
        blank = cells.not_run(f"no bench/{DEV_CASES}")
        rows = [Row((cells.text(DASH), *[blank] * (len(columns) - 1)), None)]
    else:
        rows = []
        for case, found in _dev_rows(ctx).items():
            if not found:
                blank = cells.not_run(NO_DEV_REPORT)
                rows.append(Row((cells.text(case), *[blank] * (len(columns) - 1)), None))
            for res, row in found:
                seed, variant = row["seed"], row["variant"]
                method = str(row["method"]) + (f" seed {seed}" if seed is not None else "")
                method += f" ({variant})" if variant else ""
                labels = (case, str(row["dataset"]), method, str(row["run_outcome"]))
                rows.append(Row((*map(cells.text, labels), *(_hit(row, k) for k in (1, 3, 5))), res))
    caption = (
        f"The cases of bench/{DEV_CASES}, as the committed per_case.csv files report them: every "
        "pre-registered experiment excludes them (04 §1), so only experiments that keep them have rows. "
        "Hit@k is 1 when the root service is in the run's top k (a non-ok run is a miss, 04 §7); one run "
        "per row, so no interval."
    )
    title = "Table A2: development cases (reported separately)"
    return [Table("a2-development-cases", title, caption, columns, tuple(rows))]
