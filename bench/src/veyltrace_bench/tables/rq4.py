"""RQ4 robustness tables (11 §5.4): alert-time shift (H4a), telemetry ablation (H4b) and the
RCAEval-C decoy grid (H4c), in long form: one row per (grid point, system, method), so every row
comes from one experiment. The grid coordinates are read from each experiment's spec (its
manifest when it ran), never typed here. The unperturbed point of the deterministic arms is
re2-oracle-rq1-v1. The brief arm runs on the 90-case subset, so its 0 s point is computed from
re2-oracle-rq2-v1's per_case.csv on the same case ids and seeds, as the frozen shift YAMLs say
(review H1). Each point shows its 04 §10.3 floors where their cases match (review M5).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.summary import ALL_METRICS
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import Results
from veyltrace_bench.tables.rq1 import (
    FLOORS,
    OTHER_CASES,
    POOLED,
    Line,
    Metric,
    columns,
    floor_lines,
    method_line,
    methods,
    n_a,
    na_line,
    same_cases,
    seeded,
)  # fmt: skip
from veyltrace_bench.tables.subset import case_list, on_subset

RQ1, RQ2, PRIOR = "re2-oracle-rq1-v1", "re2-oracle-rq2-v1", "re2-oracle-prior-only-v1"
BRIEF = "veyltrace:brief"
#: Methods the robustness tables keep: the floors, the fused slate and the pipeline arms.
KEEP = frozenset({*FLOORS, "naive-change", "causatrix:rrf", "veyltrace:off", BRIEF, "agent-only:brief"})
ACCURACY: tuple[Metric, ...] = (("AC@1", "ac_at_k", "ac_at_1"), ("AC@3", "ac_at_k", "ac_at_3"),
                                ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"))  # fmt: skip
DECOY: tuple[Metric, ...] = (ACCURACY[0], ("Decoy ranked first", "decoy_ranked_first", "decoy_ranked_first"),
                             ("Decoy cases", "decoy_ranked_first", "n_decoy"))  # fmt: skip
PERTURBED: dict[str, Callable[[Experiment], bool]] = {
    "shift": lambda e: e.protocol.shift_s != 0,
    "drop": lambda e: bool(e.protocol.sources_drop) and e.protocol.decoys is None,
    "decoys": lambda e: e.protocol.decoys is not None,
}


@dataclass(frozen=True)
class Point:
    """One grid point: its label, experiment, and (for a computed point) the results and methods
    to use instead of the experiment's own."""

    label: str
    experiment_id: str
    results: Results | None = None
    methods: tuple[str, ...] | None = None


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
    return [e for e in (ctx.spec(x.experiment_id) for x in ctx.experiments) if PERTURBED[test](e)]


def case_set(ctx: Context, eid: str) -> str:
    """The case set of an experiment as its spec names it: all cases, or the list and its size."""
    cases = ctx.spec(eid).dataset.cases
    if cases == "all" or ctx.root is None or not (ctx.root / cases).is_file():
        return "all" if cases == "all" else cases
    return f"{len(case_list(ctx.root / cases))}-case subset ({cases})"


def brief_zero(ctx: Context) -> Point:
    """The brief arm's 0 s point on the subset the shift brief arms ran (review H1)."""
    briefs = [e for e in perturbed(ctx, "shift") if BRIEF in methods(e)]
    lists = sorted({e.dataset.cases for e in briefs})
    seeds = sorted({s for e in briefs for m in e.methods if m.id == BRIEF for s in m.ai.seeds})
    res = ctx.get(RQ2)
    if len(lists) != 1 or lists[0] == "all" or ctx.root is None:
        return Point("0 s", RQ2, res, (BRIEF,))  # no subset to restrict to: rq2 as it is
    label = case_set(ctx, briefs[0].experiment_id).split(" (")[0]
    return Point("0 s", RQ2, on_subset(res, BRIEF, case_list(ctx.root / lists[0]), seeds, label), (BRIEF,))


def grid(
    ctx: Context, points: Sequence[Point], metrics: Sequence[Metric], extra: Sequence[str] = ()
) -> list[Row]:
    """Per point and part: the floors, then each kept method's `metrics`, the `extra` metrics'
    cells, fault-case runs, unranked runs and outcomes; then the point's pooled rows."""
    rows: list[Row] = []
    for point in points:
        eid, exp = point.experiment_id, ctx.spec(point.experiment_id)
        res = point.results or ctx.get(eid)
        kept = list(point.methods or [m for m in methods(exp) if m in KEEP])
        arms, label, cases = seeded(exp), cells.text(point.label), cells.text(case_set(ctx, eid))
        if point.results is not None and point.results.interval_note:
            cases = cells.text(f"{point.results.role}")
        for part in exp.dataset.parts:
            lines: list[Line] = _floors(ctx, point, part, metrics)
            lines += [method_line(res, part, m, metrics, seeds=m in arms, per_seed=False) for m in kept]
            for method, src, line in lines:
                more = [
                    line[0] if src is None else _extra(ctx, src, x) for x in extra
                ]  # n/a keeps its reason
                body = (*line[: len(metrics)], *more, *line[len(metrics) :])
                rows.append(
                    Row((label, cases, cells.text(res.system_of(part)), cells.text(method), *body), src)
                )
        bench = exp.dataset.parts[0].split("-")[0]
        for m in kept:
            values = [
                res.pooled(bench, m, key) if key != "n_decoy" else n_a("a count") for _, _, key in metrics
            ]
            tail = [n_a("pooled rows report the per-system values above")] * (len(extra) + 3)
            rows.append(Row((label, cases, cells.text(POOLED), cells.text(m), *values, *tail), res))
    return rows


def _extra(ctx: Context, src: Results, metric: str) -> Cell:
    return listed(ctx.spec(src.experiment_id), src, metric) or cells.not_run("no summary entry")


def _floors(ctx: Context, point: Point, part: str, metrics: Sequence[Metric]) -> list[Line]:
    """The floors of a point: chance, prior-only and the FLOORS the experiment lacks. A computed
    subset point has none of its own cases' floors; a perturbed point does not borrow baselines run
    under another protocol, but a floor of a different case set says so."""
    if point.results is not None and point.results.interval_note:
        why = f"{OTHER_CASES} ({point.results.role})"
        return [na_line(f, why, metrics, False) for f in ("chance", "prior-only", *FLOORS)]
    eid = point.experiment_id
    base = None if same_cases(ctx, eid, RQ1) else RQ1  # same cases: run it under this protocol or omit
    omitted = "not run under this protocol (the experiment omits this floor)"
    return floor_lines(ctx, eid, part, metrics, prior=PRIOR, base=base, per_seed=False, omitted=omitted)


def _table(name: str, title: str, caption: str, point: str, points: Sequence[Point], ctx: Context,
           metrics: Sequence[Metric] = ACCURACY, extra: Sequence[str] = ()) -> list[Table]:  # fmt: skip
    seeds = any(seeded(ctx.spec(p.experiment_id)) for p in points)
    body = columns(seeds, per_seed=False, metrics=metrics)
    cols = (point, "Case set", "System", "Method", *body[: len(metrics)], *extra, *body[len(metrics) :])
    caption += " Protocol of each experiment: see Sources."
    return [Table(name, title, caption, cols, tuple(grid(ctx, points, metrics, extra)))]


def shift(ctx: Context) -> list[Table]:
    """H4a: accuracy against the alert shift (04 §5.2); negative = alert earlier."""
    exps = perturbed(ctx, "shift")
    det = sorted(
        [(e.protocol.shift_s, e.experiment_id) for e in exps if BRIEF not in methods(e)] + [(0, RQ1)]
    )
    ai = sorted((e.protocol.shift_s, e.experiment_id) for e in exps if BRIEF in methods(e))
    points = [Point(f"{s:+d} s" if s else "0 s", eid) for s, eid in det]
    points += [Point(f"{s:+d} s", eid) for s, eid in ai if s < 0] + [brief_zero(ctx)]
    points += [Point(f"{s:+d} s", eid) for s, eid in ai if s > 0]
    caption = (
        "RE2, oracle alert moved by the shift, all sources; deterministic arms at every shift, then the "
        "brief arm on its subset, whose 0 s point is computed from re2-oracle-rq2-v1's per_case.csv."
    )
    return _table(
        "t10-rq4-shift", "Table 10: RQ4 alert-shift robustness (H4a)", caption, "Shift", points, ctx
    )


def ablation(ctx: Context) -> list[Table]:
    """H4b: accuracy under dropped telemetry sources; selective accuracy has no summary entry."""
    drops = sorted(
        ("drop " + ";".join(e.protocol.sources_drop), e.experiment_id) for e in perturbed(ctx, "drop")
    )
    points = [Point("none", RQ1), *(Point(label, eid) for label, eid in drops)]
    caption = "RE2, oracle alert, no shift, the named sources dropped before ingest (04 §5.2)."
    title = "Table 11: RQ4 telemetry ablation (H4b)"
    return _table("t11-rq4-ablation", title, caption, "Sources", points, ctx, extra=("selective_accuracy",))


def decoy_point(e: Experiment) -> tuple[float, float]:
    """(π, decoy rate per hour) of an RCAEval-C experiment's protocol."""
    d = e.protocol.decoys or {}
    return float(str(d.get("pi"))), float(str(d.get("rate_per_h")))


def decoys(ctx: Context) -> list[Table]:
    """H4c: the RCAEval-C grid of true-change share π × decoy rate (04 §5.2)."""
    exps = sorted(perturbed(ctx, "decoys"), key=lambda e: (*decoy_point(e), e.experiment_id))
    points = [Point("pi={:g}, rate={:g}/h".format(*decoy_point(e)), e.experiment_id) for e in exps]
    windows = ", ".join(sorted({str((e.protocol.decoys or {}).get("window_s")) for e in exps}))
    caption = (
        f"RCAEval-C on RE2, oracle alert; decoys planted in {windows} s around the alert (04 §5.2); the AI "
        "cells run on the 90-case subset (Case set column)."
    )
    title = "Table 12: RQ4 RCAEval-C decoy grid (H4c)"
    return _table("t12-rq4-rcaevalc", title, caption, "Grid point", points, ctx, DECOY)
