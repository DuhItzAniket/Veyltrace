"""RQ4 robustness tables (11 §5.4): alert-time shift (H4a), telemetry ablation (H4b) and the
RCAEval-C decoy grid (H4c), in long form: one row per (grid point, system, method), so every row
comes from one experiment. The grid coordinates are read from each experiment's spec (its
manifest when it ran), never typed here. The unperturbed point of the deterministic arms is
re2-oracle-rq1-v1; the calibrated unperturbed protocol whose calibration files every perturbed run
reuses (their YAML headers, 04 §5.4 item 4), re2-oracle-rq3-v1, is the reference of the coverage
and set-size columns, paired with its 04 §12 revision. Each point shows its 04 §10.3 floors
where their cases match (review M5), the Causatrix rankers alone (04 §6 M3, M4), the fused slate
and the pipeline arms.

The brief arm's shifted runs use the 90-case subset. When one of them has results, its 0 s point
is computed from re2-oracle-rq2-v1's per_case.csv on the same case ids and seeds, as the frozen
shift YAMLs say (review H1); when none has, nothing pairs with a subset point, so the 0 s point is
re2-oracle-rq2-v1 on all cases with its summary.json intervals (gap 52 of the R-17 audit).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import get_args

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import POOLED_SCOPE, UNLISTED, Results
from veyltrace_bench.tables.rq1 import (
    FLOORS,
    OTHER_CASES,
    POOLED,
    POOLED_COUNTS,
    Line,
    Metric,
    columns,
    floor_lines,
    kinds,
    method_line,
    methods,
    n_a,
    na_line,
    no_value,
    pooled_value,
    same_cases,
    seeded,
)  # fmt: skip
from veyltrace_bench.tables.subset import COMPUTED, case_list, on_subset
from veyltrace_contracts.models import Source, SummaryGroupMetrics

RQ1, RQ2, PRIOR = "re2-oracle-rq1-v1", "re2-oracle-rq2-v1", "re2-oracle-prior-only-v1"
#: The calibrated unperturbed RE2 protocol: every perturbed YAML reuses its calibration files.
RQ3 = "re2-oracle-rq3-v1"
BRIEF, OURS = "veyltrace:brief", "veyltrace:off"
#: Methods the robustness tables keep: the floors, the fused slate and the pipeline arms, and every
#: method of a KEPT_KINDS kind (each Causatrix ranker alone: 04 §6 pre-registers "rankers alone"
#: for every RQ4 row, and no other table shows their accuracy).
KEEP = frozenset({*FLOORS, "naive-change", "causatrix:rrf", OURS, BRIEF, "agent-only:brief"})
KEPT_KINDS = frozenset({"causatrix"})
VERIFIED = "veyltrace"  # the method kind with a verdict: a status and a conformal set (04 §4)
#: 04 §2 H4a: AC@1 drops ≤ 10 points under ±60 and ±120 s; ±30 s is exploratory there.
H4A_SHIFTS_S = frozenset({60, 120})
EXPLORATORY = " (exploratory)"
#: The telemetry sources (contract `Source`), in the order 04 §5.2 lists the ablation cells.
SOURCES: tuple[str, ...] = get_args(Source)
LIFT: tuple[Metric, ...] = (("Lift@1", "lift", "lift_at_1"), ("AC@1 − Chance@1", "lift", "chance_diff_at_1"))
ACCURACY: tuple[Metric, ...] = (("AC@1", "ac_at_k", "ac_at_1"), ("AC@3", "ac_at_k", "ac_at_3"),
                                ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"), *LIFT)  # fmt: skip
#: Every perturbed YAML lists coverage and set size "so coverage drift under the perturbation is
#: visible" (04 §5.4 item 4).
COVERAGE: tuple[Metric, ...] = (
    ("Coverage", "coverage", "coverage"),
    ("Coverage gap", "coverage", "coverage_gap"),
    ("Mean set size", "set_size", "set_size_mean"),
)
SHIFT: tuple[Metric, ...] = (*ACCURACY, *COVERAGE)
DECOY: tuple[Metric, ...] = (*ACCURACY,
                             ("Decoy ranked first", "decoy_ranked_first", "decoy_ranked_first"),
                             ("Decoy cases", "decoy_ranked_first", "n_decoy"), *COVERAGE)  # fmt: skip
SELECTIVE: tuple[Metric, ...] = (  # H4b, bench_summary 1.2 (CCR #404); counts: results.DERIVED_COUNTS
    ("AC@1 among CONFIRMED", "selective_accuracy", "ac_at_1_confirmed"),
    ("CONFIRMED verdicts", "selective_accuracy", "n_confirmed"),
    ("Answer rate CONFIRMED", "selective_accuracy", "answer_rate_confirmed"),
    ("AC@1 among CONFIRMED or LIKELY", "selective_accuracy", "ac_at_1_likely_or_better"),
    ("Answer rate CONFIRMED or LIKELY", "selective_accuracy", "answer_rate_likely_or_better"),
)
ABLATION: tuple[Metric, ...] = (*ACCURACY, *COVERAGE, *SELECTIVE)
COUNTS = frozenset({"n_decoy", "n_confirmed"})  # per-system counts: a pooled row does not repeat them
#: Entries of the verified set and status (04 §7), which only a method with a verdict has; summary.json
#: reports them per system only, so a pooled value needs an rq3-intervals file.
VERDICT_ENTRIES = frozenset({"coverage", "set_size", "selective_accuracy"})
#: The answer rate behind each selective share and count, the status it counts, and what a null
#: share means for H4b (which reads CONFIRMED verdicts only, 04 §2).
ANSWERED = {
    "ac_at_1_confirmed": ("answer_rate_confirmed", "CONFIRMED", " (H4b is vacuous here)"),
    "n_confirmed": ("answer_rate_confirmed", "CONFIRMED", " (H4b is vacuous here)"),
    "ac_at_1_likely_or_better": ("answer_rate_likely_or_better", "CONFIRMED or LIKELY", ""),
}
NO_VERDICT = (
    "has no verdict: coverage, set size and selective accuracy belong to the verifier's status and "
    "conformal set (04 §7), which only veyltrace arms have"
)
NO_ANSWER = "no {} verdict in this group (answer rate 0), so AC@1 among them is undefined{}"
NO_DECOY = "no case of this group has a decoy-changed service (Decoy cases = 0), so the share is undefined"
NO_POOLED_ENTRY = (
    "no pooled value in the committed results: summary.json reports `{}` per system only and no "
    "rq3-intervals file has a pooled one; the tables compute no new statistics (04 §10.2)"
)
INTERVALS = (
    " 95% cluster-bootstrap intervals in brackets; a value without one says so (04 §8); failed, "
    "timed-out, no-alert, rejected and unranked runs count as misses."
)
#: summary.json `outcomes` counts all the group's rows per run outcome (03 §13.3), normal windows
#: included, so it can exceed the fault-case runs (Table 7 says the same of Runs not ok).
OUTCOME_ROWS = (
    " Outcomes counts all the group's rows per run outcome (03 §13.3): its fault-case runs and, in an "
    "experiment with normal windows, one row per normal window, so it can exceed Fault-case runs."
)
OMITTED = (
    " Avg@5, MRR, Fine AC@k and Rerank@1 are listed by these experiments and are in each one's "
    "summary.json, but not tabulated here."
)
PERTURBED: dict[str, Callable[[Experiment], bool]] = {
    "shift": lambda e: e.protocol.shift_s != 0,
    "drop": lambda e: bool(e.protocol.sources_drop) and e.protocol.decoys is None,
    "decoys": lambda e: e.protocol.decoys is not None,
}


@dataclass(frozen=True)
class Point:
    """One grid point: its label, experiment, and (for a computed point) the results and methods
    to use instead of the experiment's own; `floors` False for a point whose floors another point
    of the same cases already shows (a reference row, the brief arm's full-case 0 s point)."""

    label: str
    experiment_id: str
    results: Results | None = None
    methods: tuple[str, ...] | None = None
    subset: str | None = None  # a point computed on a case subset (review H1), whatever its outcome
    floors: bool = True


def absent(res: Results, metric: str) -> Cell:
    """A 04 §9 metric the experiment lists but bench_summary 1.1 has no entry for (03 §13.3)."""
    if res.reason is not None:
        return cells.not_run(res.reason)
    return cells.not_run(f"bench_summary 1.1 has no `{metric}` entry (03 §13.3); it needs a contract change")


def listed(exp: Experiment, res: Results, metric: str) -> Cell | None:
    """None when the summary can hold `metric`; else its cell: n/a when unlisted, not run
    when the summary has no entry for it."""
    if metric not in exp.metrics:
        return cells.not_run(res.reason) if res.reason else cells.not_applicable(UNLISTED.format(metric))
    return None if metric in SummaryGroupMetrics.model_fields else absent(res, metric)


def perturbed(ctx: Context, test: str) -> list[Experiment]:
    """The experiments whose protocol perturbs `test` (shift, drop or decoys), sorted by id."""
    return [e for e in (ctx.spec(x.experiment_id) for x in ctx.experiments) if PERTURBED[test](e)]


def case_set(ctx: Context, eid: str) -> str:
    """The case set of an experiment as its spec names it: all cases, or the list and its size."""
    cases = ctx.spec(eid).dataset.cases
    if cases == "all" or ctx.root is None or not (ctx.root / cases).is_file():
        return "all" if cases == "all" else cases
    return f"{len(case_list(ctx.root / cases))}-case subset ({cases})"


def shift_label(shift_s: int) -> str:
    """A shift point's label; a shift H4a does not test is marked exploratory (04 §2)."""
    if not shift_s:
        return "0 s"
    return f"{shift_s:+d} s" + ("" if abs(shift_s) in H4A_SHIFTS_S else EXPLORATORY)


def ablation_label(exp: Experiment) -> str:
    """An ablation cell as 04 §5.2 names it: "drop <sources>", or "<source> only"."""
    dropped = exp.protocol.sources_drop
    left = [s for s in SOURCES if s not in dropped]
    return f"{left[0]} only" if len(left) == 1 else "drop " + ";".join(s for s in SOURCES if s in dropped)


def drops(ctx: Context) -> list[tuple[str, str]]:
    """(label, experiment id) of each ablation cell, in 04 §5.2 order: one source dropped (metrics,
    logs, traces, events), then the cells that drop more."""

    def order(e: Experiment) -> tuple[int, tuple[int, ...], str]:
        dropped = e.protocol.sources_drop
        return len(dropped), tuple(sorted(SOURCES.index(s) for s in dropped)), e.experiment_id

    return [(ablation_label(e), e.experiment_id) for e in sorted(perturbed(ctx, "drop"), key=order)]


def brief_zero(ctx: Context) -> Point:
    """The brief arm's 0 s point: on the subset the shift brief arms ran when one of them has
    results (review H1), else re2-oracle-rq2-v1 on all cases (no subset point to pair with)."""
    briefs = [e for e in perturbed(ctx, "shift") if BRIEF in methods(e)]
    if all(ctx.get(e.experiment_id).reason is not None for e in briefs):
        return Point("0 s", RQ2, None, (BRIEF,), floors=False)
    lists = sorted({e.dataset.cases for e in briefs})
    seeds = sorted({s for e in briefs for m in e.methods if m.id == BRIEF for s in m.ai.seeds})
    res = ctx.get(RQ2)
    if len(lists) != 1 or lists[0] == "all" or ctx.root is None:
        return Point("0 s", RQ2, res, (BRIEF,), floors=False)  # no subset to restrict to: rq2 as it is
    label = case_set(ctx, briefs[0].experiment_id).split(" (")[0]
    computed = on_subset(res, BRIEF, case_list(ctx.root / lists[0]), seeds, label)
    return Point("0 s", RQ2, computed, (BRIEF,), subset=f"{COMPUTED}, {label}")


def reference(label: str) -> Point:
    """The calibrated unperturbed reference of the coverage columns: re2-oracle-rq3-v1's
    veyltrace:off, whose floors the rq1 point of the same cases shows."""
    return Point(label, RQ3, methods=(OURS,), floors=False)


def _raw(res: Results, part: str, method: str, entry: str, key: str) -> object:
    """The summary value `metrics[entry][key]` of a group, None without one."""
    group = res.group(part, res.system_of(part), method)
    values = None if group is None else getattr(group.metrics, entry)
    return None if values is None else getattr(values, key)


def reason(res: Results, part: str | None, method: str, metric: Metric, kind: str | None, cell: Cell) -> Cell:
    """A null cell (cells.UNDEFINED_NOTE) says why when the robustness columns explain it: no
    verdict, no CONFIRMED (or LIKELY) verdict, or no decoy case; `part` None: a pooled cell."""
    _, entry, key = metric
    if cell.text != cells.UNDEFINED or cell.note != cells.UNDEFINED_NOTE:
        return cell
    if entry in VERDICT_ENTRIES and kind != VERIFIED:
        return n_a(NO_VERDICT)
    answered = ANSWERED.get(key)
    if part is not None and answered is not None and _raw(res, part, method, entry, answered[0]) == 0:
        return n_a(NO_ANSWER.format(*answered[1:]))
    if entry == "decoy_ranked_first":
        return n_a(NO_DECOY)
    return cell


def _explained(res: Results, part: str, method: str, metrics: Sequence[Metric], kind: str | None,
               body: list[Cell]) -> list[Cell]:  # fmt: skip
    """`body` with each metric cell's null reason (`reason`); the count cells after them unchanged."""
    return [*(reason(res, part, method, m, kind, c) for m, c in zip(metrics, body, strict=False)),
            *body[len(metrics) :]]  # fmt: skip


def line(
    ctx: Context, res: Results, part: str, method: str, metrics: Sequence[Metric], *, seeds: bool
) -> Line:
    """One method's row body (rq1.method_line), each null cell with the reason it is null."""
    kind = kinds(ctx.spec(res.experiment_id)).get(method)
    name, src, body = method_line(res, part, method, metrics, seeds=seeds, per_seed=False, kind=kind)
    return name, src, _explained(res, part, method, metrics, kind, body)


def pooled(exp: Experiment, res: Results, method: str, metric: Metric) -> Cell:
    """A pooled cell: n/a for a count or an entry the experiment does not list, else
    rq1.pooled_value; an entry summary.json reports per system only has a value only from an
    rq3-intervals file."""
    _, entry, key = metric
    kind, bench = kinds(exp).get(method), exp.dataset.parts[0].split("-")[0]
    if (why := res.why(method)) is not None:
        return cells.not_run(why)
    if entry not in exp.metrics:
        return n_a(UNLISTED.format(entry))
    if key in COUNTS:
        return n_a(POOLED_COUNTS)
    if entry in VERDICT_ENTRIES and kind != VERIFIED:
        return n_a(NO_VERDICT)
    if entry in VERDICT_ENTRIES and (res.rq3 is None or (POOLED_SCOPE, key) not in res.rq3.intervals):
        return no_value(NO_POOLED_ENTRY.format(key))  # the field, as Table 7: `coverage` may have one
    return reason(res, None, method, metric, kind, pooled_value(res, bench, method, entry, key, kind))


def kept(exp: Experiment) -> list[str]:
    """The methods a robustness table shows of an experiment, in rq1.methods order."""
    known = kinds(exp)
    return [m for m in methods(exp) if m in KEEP or known[m] in KEPT_KINDS]


def grid(ctx: Context, points: Sequence[Point], metrics: Sequence[Metric]) -> list[Row]:
    """Per point and part: the floors, then each kept method's `metrics`, fault-case runs,
    unranked runs and outcomes; then the point's pooled rows."""
    rows: list[Row] = []
    for point in points:
        eid, exp = point.experiment_id, ctx.spec(point.experiment_id)
        res = point.results or ctx.get(eid)
        shown = list(point.methods or kept(exp))
        arms, label = seeded(exp), cells.text(point.label)
        cases = cells.text(point.subset or case_set(ctx, eid))
        for part in exp.dataset.parts:
            lines: list[Line] = _floors(ctx, point, part, metrics) if point.floors else []
            lines += [line(ctx, res, part, m, metrics, seeds=m in arms) for m in shown]
            rows += [
                Row((label, cases, cells.text(res.system_of(part)), cells.text(method), *body), src)
                for method, src, body in lines
            ]
        for m in shown:
            values = [pooled(exp, res, m, metric) for metric in metrics]
            tail = [n_a("pooled rows report the per-system values above")] * 3
            rows.append(Row((label, cases, cells.text(POOLED), cells.text(m), *values, *tail), res))
    return rows


def _floors(ctx: Context, point: Point, part: str, metrics: Sequence[Metric]) -> list[Line]:
    """The floors of a point: chance, prior-only and the FLOORS the experiment lacks. A computed
    subset point has none of its own cases' floors; a perturbed point does not borrow baselines run
    under another protocol, but a floor of a different case set says so."""
    if point.subset is not None:
        why = f"{OTHER_CASES} ({point.subset})"
        return [na_line(f, why, metrics, False) for f in ("chance", "prior-only", *FLOORS)]
    eid, p = point.experiment_id, ctx.spec(point.experiment_id).protocol
    # Decoys add change events only, which N-Sigma, BARO (metrics) and SimpleRCA (metrics, logs,
    # traces) never read, so a decoy point borrows rq1's floors; a shift or a dropped source changes
    # their input, so such a point shows a floor only when it ran the floor itself.
    reads_same_input = p.shift_s == 0 and not p.sources_drop
    base = RQ1 if reads_same_input or not same_cases(ctx, eid, RQ1) else None
    omitted = "not run under this protocol (the experiment omits this floor)"
    found = floor_lines(ctx, eid, part, metrics, prior=PRIOR, base=base, per_seed=False, omitted=omitted)
    lines: list[Line] = []
    for m, src, body in found:  # the robustness columns' null reasons, as for the kept methods
        kind = None if src is None else kinds(ctx.spec(src.experiment_id)).get(m)
        lines.append((m, src, body if src is None else _explained(src, part, m, metrics, kind, body)))
    if p.decoys is None or eid == RQ1:
        return lines
    # Manager decision (21 Nov): a borrowed floor says where it comes from and why it may be borrowed;
    # floor_lines already gives a subset point (the AI decoy cells) "different case set" instead.
    borrowed = f"from {RQ1} (baselines ignore events)"
    return [(f"{m} ({borrowed})" if src is ctx.get(RQ1) else m, src, body) for m, src, body in lines]


def _reference_note(ctx: Context, what: str) -> str:
    """The caption sentence on the two unperturbed points: rq1 and the calibrated reference."""
    revised = ctx.revisions_of(RQ3) if ctx.get(RQ3).revised_as else ()
    ref = RQ3 + (f" (revised as {' and '.join(revised)})" if revised else "")
    scheme = ctx.spec(RQ1).split.scheme
    return (
        f" The {what} point is {RQ1}, whose verdicts are uncalibrated (split {scheme}); the {what} rows of "
        f"{ref} are the calibrated unperturbed reference for coverage and set size, since every perturbed "
        "run reuses its calibration files (04 §5.4 item 4)."
    )


def _table(name: str, title: str, caption: str, point: str, points: Sequence[Point], ctx: Context,
           metrics: Sequence[Metric]) -> list[Table]:  # fmt: skip
    seeds = any(seeded(ctx.spec(p.experiment_id)) for p in points)
    cols = (point, "Case set", "System", "Method", *columns(seeds, per_seed=False, metrics=metrics))
    caption += INTERVALS + OUTCOME_ROWS + OMITTED + " Protocol of each experiment: see Sources."
    return [Table(name, title, caption, cols, tuple(grid(ctx, points, metrics)), key=(0, 2, 3))]


def shift(ctx: Context) -> list[Table]:
    """H4a: accuracy and coverage against the alert shift (04 §5.2); negative = alert earlier."""
    exps = perturbed(ctx, "shift")
    det = sorted(
        [(e.protocol.shift_s, e.experiment_id) for e in exps if BRIEF not in methods(e)] + [(0, RQ1)]
    )
    ai = sorted((e.protocol.shift_s, e.experiment_id) for e in exps if BRIEF in methods(e))
    points: list[Point] = []
    for s, eid in det:
        points += [Point(shift_label(s), eid), *([reference(shift_label(0))] if eid == RQ1 else [])]
    zero = brief_zero(ctx)
    points += [Point(shift_label(s), eid) for s, eid in ai if s < 0] + [zero]
    points += [Point(shift_label(s), eid) for s, eid in ai if s > 0]
    if zero.subset is not None:
        brief = (
            f"the brief arm runs on its subset, and its 0 s point is computed from {RQ2}'s per_case.csv "
            "on the same case ids and seeds (no interval)"
        )
    else:
        brief = (
            f"no shifted brief run has results (Sources), so the brief arm's 0 s point is {RQ2} on all "
            "cases with its intervals, and no shifted brief point pairs with it"
        )
    caption = (
        "RE2, oracle alert moved by the shift, all sources; ±60 and ±120 s test H4a, ±30 s is "
        f"exploratory (04 §2). Deterministic arms at every shift, then the brief arm; {brief}."
        + _reference_note(ctx, "0 s")
    )
    title = "Table 10: RQ4 alert-shift robustness (H4a)"
    return _table("t10-rq4-shift", title, caption, "Shift", points, ctx, SHIFT)


def ablation(ctx: Context) -> list[Table]:
    """H4b: accuracy, coverage and selective accuracy under dropped telemetry sources."""
    points = [Point("none", RQ1), reference("none"), *(Point(label, eid) for label, eid in drops(ctx))]
    refs = [RQ1, *(ctx.revisions_of(RQ3) if ctx.get(RQ3).revised_as else (RQ3,))]
    unlisted = [r for r in refs if "selective_accuracy" not in ctx.spec(r).metrics]
    verb = "does" if len(unlisted) == 1 else "do"
    control = (
        f" {' and '.join(unlisted)} {verb} not list selective_accuracy, so no unperturbed row has a "
        "selective-accuracy value."
        if unlisted
        else ""
    )
    caption = (
        "RE2, oracle alert, no shift, the named sources dropped before ingest, in 04 §5.2 order. H4b reads "
        "AC@1 among CONFIRMED in every cell. CONFIRMED verdicts is derived, not read: it is "
        "answer_rate_confirmed × n_fault of summary.json's selective_accuracy entry, rounded to the "
        "integer k, and the generator stops unless that product is within 1e-6 of k (a k / n check, "
        "03 §13.3), so it is the exact count behind the rate, not a new statistic."
        f"{control}" + _reference_note(ctx, "none")
    )
    title = "Table 11: RQ4 telemetry ablation (H4b)"
    return _table("t11-rq4-ablation", title, caption, "Sources", points, ctx, ABLATION)


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
