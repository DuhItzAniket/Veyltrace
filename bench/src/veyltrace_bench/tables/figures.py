"""The data figures of 11 §5 (R-17): Figs 4, 7, 8, 9 drawn; Figs 5 and 6 as reasoned gaps.

Each figure writes `figures/<name>.csv` (every plotted value with its interval, status and source
experiment and commit: the figure's data of record) and one SVG per panel. A point that is not
run is a CSV row with its reason and is left out of the plot, never drawn as 0; the SVG says how
many points it lacks. Coordinates (shift, sources dropped, decoy grid) come from the YAMLs.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass

from veyltrace_bench.tables import svg
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.results import Point, Results
from veyltrace_bench.tables.rq1 import system_of
from veyltrace_bench.tables.rq4 import UNPERTURBED, decoy_point, perturbed

FIGURES_DIR = "figures"
CSV_COLUMNS = ("panel", "series", "x", "value", "low", "high", "status", "experiment", "commit")
OURS = "veyltrace:off"
SHIFT_SERIES = ("rcaeval:nsigma", "rcaeval:baro", "simplerca", "causatrix:rrf", OURS, "veyltrace:brief")
AC1 = ("ac_at_k", "ac_at_1")  # (summary entry, key)


@dataclass(frozen=True)
class Datum:
    """One plotted value at (panel, series, x) and the experiment it comes from."""

    panel: str
    series: str
    x: str
    point: Point
    source: Results


def data(ctx: Context, eid: str, method: str, entry_key: tuple[str, str], series: str, x: str) -> list[Datum]:
    """One datum per dataset part of the experiment (from its YAML, so a part without results is
    still listed), the panel being the part's system."""
    res = ctx.get(eid)
    parts = ctx.spec(eid).dataset.parts
    return [
        Datum(system_of(p), series, x, res.point(p, system_of(p), method, *entry_key), res) for p in parts
    ]


def to_csv(rows: Sequence[Datum]) -> bytes:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(CSV_COLUMNS)
    for d in rows:
        nums = ["" if v is None else repr(v) for v in (d.point.value, d.point.low, d.point.high)]
        out.writerow(
            [d.panel, d.series, d.x, *nums, d.point.status, d.source.experiment_id, d.source.commit or ""]
        )
    return buf.getvalue().encode("utf-8")


def _note(rows: Sequence[Datum]) -> str:
    n = sum(d.point.value is None for d in rows)
    return f"{n} of {len(rows)} points not run or undefined; see the CSV" if n else "all points present"


def fig4(ctx: Context) -> dict[str, bytes]:
    """Fig 4: AC@1 = Retrieval@K × Rerank@1 per RE2 system (oracle, veyltrace:off)."""
    eid = "re2-oracle-rq1-v1"
    metrics = (("Retrieval@K", ("retrieval_at_k", "retrieval_at_k")),
               ("Rerank@1", ("rerank_at_1", "rerank_at_1")), ("AC@1", AC1))  # fmt: skip
    rows = [d for c, ek in metrics for d in data(ctx, eid, OURS, ek, OURS, c)]
    panels = sorted({d.panel for d in rows})
    values = [
        [next(d.point.value for d in rows if d.panel == p and d.x == c) for c, _ in metrics] for p in panels
    ]
    title = "Fig. 4: retrieval vs re-ranking, RE2 oracle, veyltrace:off"
    image = svg.heatmap(title, panels, [c for c, _ in metrics], values, _note(rows))
    return {"fig4-retrieval-rerank.csv": to_csv(rows), "fig4-retrieval-rerank.svg": image.encode()}


def fig7(ctx: Context) -> dict[str, bytes]:
    """Fig 7: AC@1 against the alert shift, one panel per RE2 system."""
    points = sorted(
        [(e.protocol.shift_s, e.experiment_id) for e in perturbed(ctx, "shift")]
        + [(0, u) for u in UNPERTURBED]
    )
    rows = [
        d for s, eid in points for m in ctx.spec(eid).methods if m.id in SHIFT_SERIES
        for d in data(ctx, eid, m.id, AC1, m.id, str(s))
    ]  # fmt: skip
    files = {"fig7-shift.csv": to_csv(rows)}
    xs = sorted({float(d.x) for d in rows})
    for panel in sorted({d.panel for d in rows}):
        mine = [d for d in rows if d.panel == panel]
        drawn = [(d, v) for d in mine if (v := d.point.value) is not None]
        series = {
            m: [(float(d.x), v, d.point.low, d.point.high) for d, v in drawn if d.series == m]
            for m in SHIFT_SERIES
        }
        title = f"Fig. 7: AC@1 vs alert shift, RE2-{panel.upper()}"
        files[f"fig7-shift-{panel}.svg"] = svg.lines(
            title, "shift (s)", "AC@1", xs, series, _note(mine)
        ).encode()
    return files


def _heatmaps(ctx: Context, name: str, title: str, cells: Sequence[tuple[str, str, str]]) -> dict[str, bytes]:
    """A heatmap per RE2 system of veyltrace:off's AC@1 over (row label, column label, experiment)."""
    rows = [d for row, col, eid in cells for d in data(ctx, eid, OURS, AC1, row, col)]
    files = {f"{name}.csv": to_csv(rows)}
    labels, cols = list(dict.fromkeys(r for r, _, _ in cells)), list(dict.fromkeys(c for _, c, _ in cells))
    for panel in sorted({d.panel for d in rows}):
        mine = [d for d in rows if d.panel == panel]
        found = {(d.series, d.x): d.point.value for d in mine}
        values = [[found.get((r, c)) for c in cols] for r in labels]
        files[f"{name}-{panel}.svg"] = svg.heatmap(
            f"{title}, RE2-{panel.upper()}", labels, cols, values, _note(mine)
        ).encode()
    return files


def fig8(ctx: Context) -> dict[str, bytes]:
    """Fig 8: AC@1 of veyltrace:off under each telemetry ablation (the status mix has no summary entry)."""
    drops = sorted(
        ("drop " + ";".join(e.protocol.sources_drop), e.experiment_id) for e in perturbed(ctx, "drop")
    )
    cells = [("none", "AC@1", UNPERTURBED[0]), *((label, "AC@1", eid) for label, eid in drops)]
    return _heatmaps(ctx, "fig8-ablation", "Fig. 8: AC@1 under telemetry ablation", cells)


def fig9(ctx: Context) -> dict[str, bytes]:
    """Fig 9: AC@1 of veyltrace:off over the RCAEval-C grid, π (rows) × decoy rate (columns)."""
    exps = sorted(
        (e for e in perturbed(ctx, "decoys") if any(m.id == OURS for m in e.methods)), key=decoy_point
    )
    cells = [(f"pi={decoy_point(e)[0]:g}", f"{decoy_point(e)[1]:g}/h", e.experiment_id) for e in exps]
    return _heatmaps(ctx, "fig9-rcaevalc", "Fig. 9: AC@1 over the RCAEval-C grid", cells)


GAPS = (
    ("fig5-predicate-requests", "Fig. 5: predicate requests vs claim-pass outcome",
     "predicate requests live in each run's proposals.json; bench_summary 1.1 has no entry for them"),
    ("fig6-risk-coverage", "Fig. 6: risk-coverage, ranker vs verifier",
     "bench_summary 1.1 has no `risk_coverage` entry (03 §13.3); it needs a contract change"),
)  # fmt: skip


def figures(ctx: Context) -> dict[str, bytes]:
    """Every figure file, as {path relative to the results root: bytes}."""
    files: dict[str, bytes] = {}
    for build in (fig4, fig7, fig8, fig9):
        files |= build(ctx)
    for name, title, reason in GAPS:
        files[f"{name}.svg"] = svg.placeholder(title, reason).encode()
    return {f"{FIGURES_DIR}/{k}": v for k, v in sorted(files.items())}
