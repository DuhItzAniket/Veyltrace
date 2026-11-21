"""Table A0: every reportable experiment of the 04 §6 matrix and whether it ran (R-16 fills each
cell or marks it "not run" with a reason; 04 §10.8)."""

from __future__ import annotations

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import Results


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
    caption = (
        "Every experiment YAML in bench/experiments (synth smoke excluded) and the state of its "
        "committed results."
    )
    columns = ("Experiment", "RQ", "Pre-registered", "Status", "Groups", "Statistics")
    return [Table("a0-results-index", "Table A0: results index", caption, columns, tuple(rows))]
