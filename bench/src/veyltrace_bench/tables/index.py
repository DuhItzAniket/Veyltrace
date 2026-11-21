"""Table A0, every reportable experiment of the 04 §6 matrix and whether it ran (R-16 fills each
cell or marks it "not run" with a reason; 04 §10.8), and Table A2, the development cases, which no
test table includes and which are reported separately (04 §1, §10.5)."""

from __future__ import annotations

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.context import DEV_CASES, Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import Results

NO_DEV_REPORT = "no experiment reports the development cases yet; they are reported separately (04 §1)"


def _statistics(res: Results) -> cells.Cell:
    if res.summary is None or res.stats_reason is not None:
        return cells.not_run(res.stats_reason or "no results")
    stats = res.summary.statistics
    assert not isinstance(stats, str)
    parts = (len(stats.intervals), len(stats.comparisons), len(stats.not_run))
    return cells.text("{} intervals, {} comparisons, {} not run".format(*parts))


def results_index(ctx: Context) -> list[Table]:
    rows: list[Row] = []
    for exp in ctx.experiments:
        res = ctx.get(exp.experiment_id)
        run = res.summary is not None
        status = cells.text("run") if run else cells.not_run(res.reason or "no results")
        groups = cells.count(len(res.summary.groups)) if res.summary is not None else status
        labels = (exp.experiment_id, ", ".join(exp.rq) or "-", "yes" if exp.prereg else "no")
        rows.append(Row((*map(cells.text, labels), status, groups, _statistics(res)), res))
    for cell, reason in sorted(ctx.cells.items()):  # 04 §6 cells that have no experiment YAML
        blank = cells.not_run(reason)
        rows.append(
            Row(
                (cells.text(f"04 §6 cell {cell}"), cells.text("-"), cells.text("-"), blank, blank, blank),
                None,
            )
        )
    caption = (
        "Every experiment YAML in bench/experiments (synth smoke excluded) and the state of its "
        "committed results, then the 04 §6 matrix cells that only bench/results/not_run.yaml names."
    )
    columns = ("Experiment", "RQ", "Pre-registered", "Status", "Groups", "Statistics")
    return [Table("a0-results-index", "Table A0: results index", caption, columns, tuple(rows))]


def development_cases(ctx: Context) -> list[Table]:
    """Table A2: the slot for the development cases' results, reported apart from every test table."""
    if ctx.dev_cases is None:
        rows = (Row((cells.text("-"), cells.not_run(f"no bench/{DEV_CASES}")), None),)
    else:
        rows = tuple(Row((cells.text(case), cells.not_run(NO_DEV_REPORT)), None) for case in ctx.dev_cases)
    caption = f"The cases of bench/{DEV_CASES}: every pre-registered experiment excludes them (04 §1)."
    title = "Table A2: development cases (reported separately)"
    return [Table("a2-development-cases", title, caption, ("Case", "Result"), rows)]
