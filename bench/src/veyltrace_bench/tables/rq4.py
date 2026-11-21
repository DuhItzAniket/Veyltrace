"""RQ4 robustness tables (11 §5.4): alert-time shift (H4a), telemetry ablation (H4b) and the
RCAEval-C decoy grid (H4c), in long form: one row per (grid point, system, method), so every row
comes from one experiment. The grid coordinates are read from each experiment's YAML protocol,
never typed here; the unperturbed point is the RQ1 (or RQ2, for the AI arm) experiment.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.summary import ALL_METRICS
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import Results
from veyltrace_bench.tables.rq1 import OUTCOMES, POOLED, methods, n_a, outcomes, system_of

UNPERTURBED = ("re2-oracle-rq1-v1", "re2-oracle-rq2-v1")  # shift 0, all sources, no decoys
#: Methods the robustness tables keep: the floors, the fused slate and the pipeline arms.
KEEP = frozenset({"rcaeval:nsigma", "rcaeval:baro", "simplerca", "naive-change", "causatrix:rrf",
                  "veyltrace:off", "veyltrace:brief", "agent-only:brief"})  # fmt: skip
Metric = tuple[str, str, str]  # (column, summary entry, key)
ACCURACY: tuple[Metric, ...] = (("AC@1", "ac_at_k", "ac_at_1"), ("AC@3", "ac_at_k", "ac_at_3"),
                                ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"))  # fmt: skip
DECOY: tuple[Metric, ...] = (ACCURACY[0], ("Decoy ranked first", "decoy_ranked_first", "decoy_ranked_first"),
                             ("Decoy cases", "decoy_ranked_first", "n_decoy"))  # fmt: skip
PERTURBED: dict[str, Callable[[Experiment], bool]] = {
    "shift": lambda e: e.protocol.shift_s != 0,
    "drop": lambda e: bool(e.protocol.sources_drop) and e.protocol.decoys is None,
    "decoys": lambda e: e.protocol.decoys is not None,
}


def absent(res: Results, metric: str) -> Cell:
    """A 04 §9 metric the experiment lists but bench_summary 1.1 has no entry for (03 §13.3)."""
    if res.reason is not None:
        return cells.not_run(res.reason)
    return cells.not_run(f"bench_summary 1.1 has no `{metric}` entry (03 §13.3); it needs a contract change")


def listed(exp: Experiment, res: Results, metric: str) -> Cell | None:
    """None when the summary can hold `metric`; else its not-run cell (unlisted or no entry)."""
    if metric not in exp.metrics:
        return cells.not_run(res.reason or f"the experiment does not list the metric `{metric}`")
    return None if metric in ALL_METRICS else absent(res, metric)


def perturbed(ctx: Context, test: str) -> list[Experiment]:
    """The experiments whose protocol perturbs `test` (shift, drop or decoys), sorted by id."""
    return [e for e in ctx.experiments if PERTURBED[test](e)]


def grid(
    ctx: Context, points: Sequence[tuple[str, str]], metrics: Sequence[Metric], extra: Sequence[str]
) -> list[Row]:
    """Per (label, experiment) point, part and kept method: the `metrics`, the `extra` metrics'
    cells, fault cases and outcomes; then the point's pooled rows."""
    rows: list[Row] = []
    for label, eid in points:
        exp, res = ctx.spec(eid), ctx.get(eid)
        kept = [m for m in methods(exp) if m in KEEP]
        for part in exp.dataset.parts:
            sys = system_of(part)
            for m in kept:
                values = [res.metric(part, sys, m, entry, key) for _, entry, key in metrics]
                more = [listed(exp, res, x) or cells.not_run("no summary entry") for x in extra]
                tail = (res.count(part, sys, m, "n_fault"), outcomes(res, part, m))
                rows.append(
                    Row((cells.text(label), cells.text(sys), cells.text(m), *values, *more, *tail), res)
                )
        bench = exp.dataset.parts[0].split("-")[0]
        for m in kept:
            values = [
                res.pooled(bench, m, key) if key != "n_decoy" else n_a("a count") for _, _, key in metrics
            ]
            tail = [n_a("pooled rows report the per-system values above")] * (len(extra) + 2)
            rows.append(Row((cells.text(label), cells.text(POOLED), cells.text(m), *values, *tail), res))
    return rows


def _table(name: str, title: str, caption: str, point: str, labelled: Sequence[tuple[str, str]], ctx: Context,
           metrics: Sequence[Metric] = ACCURACY, extra: Sequence[str] = ()) -> list[Table]:  # fmt: skip
    columns = (point, "System", "Method", *(c for c, _, _ in metrics), *extra, "Fault cases",
               "Outcomes " + "/".join(OUTCOMES))  # fmt: skip
    return [Table(name, title, caption, columns, tuple(grid(ctx, labelled, metrics, extra)))]


def shift(ctx: Context) -> list[Table]:
    """H4a: accuracy against the alert shift (04 §5.2); negative = alert earlier."""
    points = [(e.protocol.shift_s, e.experiment_id) for e in perturbed(ctx, "shift")]
    labelled = [
        (f"{s:+d} s" if s else "0 s", eid) for s, eid in sorted(points + [(0, u) for u in UNPERTURBED])
    ]
    caption = "RE2, oracle alert moved by the shift, all sources; per-system rows, then pooled."
    return _table(
        "t10-rq4-shift", "Table 10: RQ4 alert-shift robustness (H4a)", caption, "Shift", labelled, ctx
    )


def ablation(ctx: Context) -> list[Table]:
    """H4b: accuracy under dropped telemetry sources; selective accuracy has no summary entry."""
    drops = sorted(
        ("drop " + ";".join(e.protocol.sources_drop), e.experiment_id) for e in perturbed(ctx, "drop")
    )
    caption = "RE2, oracle alert, no shift, the named sources dropped before ingest (04 §5.2)."
    labelled = [("none", UNPERTURBED[0]), *drops]
    title = "Table 11: RQ4 telemetry ablation (H4b)"
    return _table("t11-rq4-ablation", title, caption, "Sources", labelled, ctx, extra=("selective_accuracy",))


def decoy_point(e: Experiment) -> tuple[float, float]:
    """(π, decoy rate per hour) of an RCAEval-C experiment's protocol."""
    d = e.protocol.decoys or {}
    return float(str(d.get("pi"))), float(str(d.get("rate_per_h")))


def decoys(ctx: Context) -> list[Table]:
    """H4c: the RCAEval-C grid of true-change share π × decoy rate (04 §5.2)."""
    exps = sorted(perturbed(ctx, "decoys"), key=lambda e: (*decoy_point(e), e.experiment_id))
    labelled = [("pi={:g}, rate={:g}/h".format(*decoy_point(e)), e.experiment_id) for e in exps]
    windows = ", ".join(sorted({str((e.protocol.decoys or {}).get("window_s")) for e in exps}))
    caption = f"RCAEval-C on RE2, oracle alert; decoys planted in {windows} s around the alert (04 §5.2)."
    title = "Table 12: RQ4 RCAEval-C decoy grid (H4c)"
    return _table("t12-rq4-rcaevalc", title, caption, "Grid point", labelled, ctx, DECOY)
