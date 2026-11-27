"""The data figures of 11 §5 (R-17): Figs 4, 6, 7, 8, 9 drawn; Fig 5 as a reasoned gap (no data).

Each figure writes `figures/<name>.csv` (every plotted value with its interval, status and source
experiment and commit: the figure's data of record) and one SVG per panel. A point without a value
is a CSV row with its reason and is left out of the plot, never drawn as 0; the SVG says how many
points it lacks, and how many have no interval. Coordinates (shift, sources dropped, decoy grid)
come from the YAMLs. Figures pair a pre-registered experiment with its 04 §12 revisions as the
tables do (generate.paired, lead rule R1): each revised point follows the pre-registered point it
replaces, and both are labelled by their source.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from veyltrace_bench.tables import cells, svg
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.results import NO_INTERVAL, UNLISTED, Point, Results
from veyltrace_bench.tables.rq1 import NO_VALUE, methods
from veyltrace_bench.tables.rq4 import BRIEF, H4A_SHIFTS_S, RQ1, brief_zero, decoy_point, drops, perturbed
from veyltrace_bench.tables.rq23 import DIFFERENCE, NO_DIFFERENCE, RISK

FIGURES_DIR = "figures"
CSV_COLUMNS = ("panel", "series", "x", "value", "low", "high", "status", "experiment", "commit", "source")
OURS = "veyltrace:off"
SHIFT_SERIES = ("rcaeval:nsigma", "rcaeval:baro", "simplerca", "causatrix:rrf", OURS, "veyltrace:brief")
AC1 = ("ac_at_k", "ac_at_1")  # (summary entry, key)
RQ3 = "re2-oracle-rq3-v1"  # the pre-registered RQ3 experiment of Fig 6; its revisions are paired in
RQ2 = "re2-oracle-rq2-v1"  # the experiment of Fig 5 (predicate requests, 04 §7 proposal outcomes)


@dataclass(frozen=True)
class Datum:
    """One plotted value at (panel, series, x) and the experiment it comes from."""

    panel: str
    series: str
    x: str
    point: Point
    source: Results


def data(
    ctx: Context,
    eid: str,
    method: str,
    entry_key: tuple[str, str],
    series: str,
    x: str,
    res: Results | None = None,
) -> list[Datum]:
    """One datum per dataset part of the experiment (from its spec, so a part without results is
    still listed), the panel being the part's system; `res` replaces the experiment's results for a
    computed point (review H1)."""
    res = res or ctx.get(eid)
    parts = ctx.spec(eid).dataset.parts
    return [
        Datum(res.system_of(p), series, x, res.point(p, res.system_of(p), method, *entry_key), res)
        for p in parts
    ]


def to_csv(rows: Sequence[Datum]) -> bytes:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(CSV_COLUMNS)
    for d in rows:
        nums = ["" if v is None else repr(v) for v in (d.point.value, d.point.low, d.point.high)]
        source = (d.source.experiment_id, d.source.commit or "", d.source.label)
        out.writerow([d.panel, d.series, d.x, *nums, d.point.status, *source])
    return buf.getvalue().encode("utf-8")


def _note(rows: Sequence[Datum]) -> str:
    """How many points have no value, and how many have a value but no interval (R3)."""
    n = sum(d.point.value is None for d in rows)
    bare = sum(d.point.value is not None and d.point.status != "ok" for d in rows)
    lacking = f"{n} of {len(rows)} points have no value (see the CSV status)" if n else "all points present"
    return lacking + (f"; {bare} without an interval ({NO_INTERVAL})" if bare else "")


def _label(d: Datum) -> str:
    """A series label that tells a pre-registered point from its revision's (R1)."""
    return f"{d.series} ({d.source.role})" if d.source.role else d.series


Rows = Callable[[Context], list[Datum]]
Draw = Callable[[Context, list[Datum]], dict[str, bytes]]


def _key(d: Datum) -> tuple[str, str, str]:
    return d.panel, d.series, d.x


def paired(rows_of: Rows, ctx: Context) -> list[Datum]:
    """`rows_of`'s data and, for each 04 §12 revision (sorted by id), the data of a pass on
    Context.revised that stand in for the experiment it revises, each right after the last
    pre-registered datum with the same (panel, series, x); a revised datum without that key goes at
    the end, and the revision's own data under its own id are left out (as generate.paired does for
    table rows)."""
    rows = rows_of(ctx)
    if not ctx.revises:
        return rows
    revised: dict[tuple[str, str, str], list[Datum]] = {}
    replaced: set[str] = set()
    for new in sorted(ctx.revises):
        for d in rows_of(ctx.revised(new)):
            if d.source.stands_in_for is not None:
                revised.setdefault(_key(d), []).append(d)
                replaced.add(new)
    rows = [d for d in rows if d.source.stands_in_for is not None or d.source.experiment_id not in replaced]
    last = {_key(d): n for n, d in enumerate(rows)}
    out: list[Datum] = []
    for n, d in enumerate(rows):
        out.append(d)
        if last[_key(d)] == n:
            out += revised.pop(_key(d), [])
    return out + [d for key in sorted(revised) for d in revised[key]]


FIG4 = (
    ("Retrieval@K", ("retrieval_at_k", "retrieval_at_k")),
    ("Rerank@1", ("rerank_at_1", "rerank_at_1")),
    ("AC@1", AC1),
)


def rows4(ctx: Context) -> list[Datum]:
    return [d for c, ek in FIG4 for d in data(ctx, RQ1, OURS, ek, OURS, c)]


def draw4(ctx: Context, rows: list[Datum]) -> dict[str, bytes]:
    """Fig 4: AC@1 = Retrieval@K × Rerank@1 per RE2 system (oracle, veyltrace:off)."""
    panels = sorted({d.panel for d in rows})
    values = [
        [next(d.point.value for d in rows if d.panel == p and d.x == c) for c, _ in FIG4] for p in panels
    ]
    title = "Fig. 4: retrieval vs re-ranking, RE2 oracle, veyltrace:off"
    image = svg.heatmap(title, panels, [c for c, _ in FIG4], values, _note(rows))
    return {"fig4-retrieval-rerank.csv": to_csv(rows), "fig4-retrieval-rerank.svg": image.encode()}


#: Fig 7 marks the shifts H4a does not test (04 §2: ±30 s is exploratory).
EXPLORATORY_NOTE = (
    f"; H4a tests ±{' and ±'.join(map(str, sorted(H4A_SHIFTS_S)))} s, other shifts are exploratory (04 §2)"
)


def rows7(ctx: Context) -> list[Datum]:
    """Fig 7's data: the deterministic arms' 0 s point is re2-oracle-rq1-v1; the brief arm's is
    rq4.brief_zero's, as Table 10: re2-oracle-rq2-v1 on all cases with its intervals when no
    shifted brief run has results, else computed on their subset (review H1)."""
    exps = perturbed(ctx, "shift")
    det = [(e.protocol.shift_s, e.experiment_id) for e in exps if BRIEF not in methods(e)] + [(0, RQ1)]
    rows = [
        d for s, eid in sorted(det) for m in methods(ctx.spec(eid)) if m in SHIFT_SERIES and m != BRIEF
        for d in data(ctx, eid, m, AC1, m, str(s))
    ]  # fmt: skip
    zero = brief_zero(ctx)
    brief = sorted([(e.protocol.shift_s, e.experiment_id, None) for e in exps if BRIEF in methods(e)]
                   + [(0, zero.experiment_id, zero.results)], key=lambda p: (p[0], p[1]))  # fmt: skip
    return rows + [d for s, eid, res in brief for d in data(ctx, eid, BRIEF, AC1, BRIEF, str(s), res)]


def draw7(ctx: Context, rows: list[Datum]) -> dict[str, bytes]:
    """Fig 7: AC@1 against the alert shift, one panel per RE2 system."""
    files = {"fig7-shift.csv": to_csv(rows)}
    xs = sorted({float(d.x) for d in rows})
    computed = brief_zero(ctx).subset  # set whether or not the subset point could be computed
    for panel in sorted({d.panel for d in rows}):
        mine = [d for d in rows if d.panel == panel]
        drawn = [(d, v) for d in mine if (v := d.point.value) is not None]
        series = {
            m: [(float(d.x), v, d.point.low, d.point.high) for d, v in drawn if d.series == m]
            for m in SHIFT_SERIES
        }
        title = f"Fig. 7: AC@1 vs alert shift, RE2-{panel.upper()}"
        note = _note(mine) + (f"; {BRIEF} at 0 s {computed}" if computed else "") + EXPLORATORY_NOTE
        files[f"fig7-shift-{panel}.svg"] = svg.lines(title, "shift (s)", "AC@1", xs, series, note).encode()
    return files


def _heatmaps(
    name: str, title: str, rows: list[Datum], cols: Sequence[str] | None = None, extra: str = ""
) -> dict[str, bytes]:
    """A heatmap per panel of the data's values: a row per series label, a column per x; `extra`
    is appended to each panel's note."""
    files = {f"{name}.csv": to_csv(rows)}
    labels = list(dict.fromkeys(_label(d) for d in rows))
    xs = list(cols) if cols is not None else list(dict.fromkeys(d.x for d in rows))
    for panel in sorted({d.panel for d in rows}):
        mine = [d for d in rows if d.panel == panel]
        found = {(_label(d), d.x): d.point.value for d in mine}
        values = [[found.get((r, c)) for c in xs] for r in labels]
        files[f"{name}-{panel}.svg"] = svg.heatmap(
            f"{title}{panel.upper()}", labels, xs, values, _note(mine) + extra
        ).encode()
    return files


def _off(ctx: Context, grid: Sequence[tuple[str, str, str]], entry_key: tuple[str, str] = AC1) -> list[Datum]:
    """veyltrace:off's `entry_key` (AC@1) per RE2 system over (row label, column label, experiment)."""
    return [d for row, col, eid in grid for d in data(ctx, eid, OURS, entry_key, row, col)]


#: Fig 8's columns: AC@1 and the status mix bench_summary 1.2 gives per cell (`selective_accuracy`,
#: CCR #404): the shares of fault-case runs with a CONFIRMED, and a CONFIRMED or LIKELY, verdict.
#: The full four-status mix is only in per_case.csv, which the figures do not count (R3).
FIG8 = (
    ("AC@1", AC1),
    ("CONFIRMED share", ("selective_accuracy", "answer_rate_confirmed")),
    ("CONFIRMED or LIKELY share", ("selective_accuracy", "answer_rate_likely_or_better")),
)


def rows8(ctx: Context) -> list[Datum]:
    """Fig 8's data: the 'none' cell is re2-oracle-rq1-v1, then the ablation cells in 04 §5.2 order
    with Table 11's labels (rq4.drops)."""
    cells_ = [("none", RQ1), *drops(ctx)]
    return [d for col, ek in FIG8 for d in _off(ctx, [(label, col, eid) for label, eid in cells_], ek)]


def draw8(ctx: Context, rows: list[Datum]) -> dict[str, bytes]:
    """Fig 8: AC@1 and the CONFIRMED and CONFIRMED-or-LIKELY shares of veyltrace:off under each
    telemetry ablation."""
    title = "Fig. 8: AC@1 and status mix under telemetry ablation, RE2-"
    return _heatmaps("fig8-ablation", title, rows, [c for c, _ in FIG8])


def rows9(ctx: Context) -> list[Datum]:
    exps = sorted(
        (e for e in perturbed(ctx, "decoys") if any(m.id == OURS for m in e.methods)), key=decoy_point
    )
    return _off(
        ctx, [(f"pi={decoy_point(e)[0]:g}", f"{decoy_point(e)[1]:g}/h", e.experiment_id) for e in exps]
    )


def draw9(ctx: Context, rows: list[Datum]) -> dict[str, bytes]:
    """Fig 9: AC@1 of veyltrace:off over the RCAEval-C grid, π (rows) × decoy rate (columns)."""
    return _heatmaps("fig9-rcaevalc", "Fig. 9: AC@1 over the RCAEval-C grid, RE2-", rows)


FIG6 = (("AURC verifier", ("risk_coverage", "aurc_verdict")), ("AURC fused", ("risk_coverage", "aurc_fused")))
DIFF6 = "AURC V − F"  # H3c's difference, below 0 favours V: only rq3-intervals has it (R4)
#: Why Fig 6 shows areas, not curves: no committed summary holds a curve (R3: no new statistics).
NO_CURVES = (
    "; curves not drawn: summary.json keeps the areas only, and the tables compute no curve from "
    "rq3-intervals rows.csv (R3)"
)


def _difference(ctx: Context, eid: str, method: str) -> list[Datum]:
    """AURC V − F per system with its rq3-intervals interval, or why it has none."""
    res, exp = ctx.get(eid), ctx.spec(eid)
    out: list[Datum] = []
    for part in exp.dataset.parts:
        sys = res.system_of(part)
        if (why := res.missing(part, sys, method)) is not None:
            point = Point(None, status=cells.not_run(why).note or "")
        elif RISK not in exp.metrics:
            point = Point(None, status=cells.not_applicable(UNLISTED.format(RISK)).note or "")
        elif (found := res.side_bounds(sys, DIFFERENCE)) is None:
            point = Point(None, status=f"{NO_VALUE}: {NO_DIFFERENCE}")
        else:
            point = Point(*found)
        out.append(Datum(sys, method, DIFF6, point, res))
    return out


def rows6(ctx: Context) -> list[Datum]:
    """Fig 6's data: AURC of V and of F per method and RE2 system (bench_summary 1.2
    `risk_coverage`, 03 §13.3), with the rq3-intervals bounds where committed (R3), and their
    difference V − F (H3c) from rq3-intervals."""
    return [
        d
        for m in methods(ctx.spec(RQ3))
        for d in [*(d for c, ek in FIG6 for d in data(ctx, RQ3, m, ek, m, c)), *_difference(ctx, RQ3, m)]
    ]


def draw6(ctx: Context, rows: list[Datum]) -> dict[str, bytes]:
    """Fig 6 (H3c): AURC of the verified score V against the fused score F (lower is better), and
    V − F. bench_summary keeps the areas, not the curves, so the figure shows the areas side by side."""
    title = "Fig. 6: risk-coverage AURC, verifier vs fused score, RE2-"
    return _heatmaps("fig6-risk-coverage", title, rows, [*(c for c, _ in FIG6), DIFF6], NO_CURVES)


FIGURES: tuple[tuple[Rows, Draw], ...] = (
    (rows4, draw4), (rows6, draw6), (rows7, draw7), (rows8, draw8), (rows9, draw9),
)  # fmt: skip
#: Figures whose experiment ran but whose data no committed result holds (lead rule R7): (name,
#: title, experiment, series, x, reason). The figure is not generated, and its CSV has one status row
#: naming the experiment, so it is never read as "not run".
GAPS = (
    ("fig5-predicate-requests", "Fig. 5: predicate requests vs claim-pass outcome", RQ2,
     "predicate requests", "claim-pass outcome",
     "no data in the committed results: predicate requests and claim-pass outcomes (04 §7 \"Proposal "
     "outcomes\") are only in each run's proposals.json and verdict.json, in run directories that are "
     "not committed; summary.json has no proposal-outcome entry (03 §13.3), so the figure needs a "
     "contract change before it can be drawn"),
)  # fmt: skip


def gap_rows(ctx: Context, eid: str, series: str, x: str, reason: str) -> list[Datum]:
    """The one status row of a figure without data: no value, the reason, and the experiment."""
    return [Datum("all", series, x, Point(None, status=reason), ctx.get(eid))]


def figures(ctx: Context) -> dict[str, bytes]:
    """Every figure file, as {path relative to the results root: bytes}, revisions paired (R1)."""
    files: dict[str, bytes] = {}
    for rows_of, draw in FIGURES:
        files |= draw(ctx, paired(rows_of, ctx))
    for name, title, eid, series, x, reason in GAPS:
        files[f"{name}.csv"] = to_csv(gap_rows(ctx, eid, series, x, reason))
        files[f"{name}.svg"] = svg.placeholder(title, reason).encode()
    return {f"{FIGURES_DIR}/{k}": v for k, v in sorted(files.items())}
