"""Template counts and log series (02 §3.5 steps 6 and 7, log series table).

Lines join their template through (service, masked). The `templates` table lists every template
with its per-window counts, so only those counts move with `alert.json`; the series (`log_rate`,
`log_error_rate`, `tmpl:{template_id}`) sit on the epoch-aligned bucket grid of the whole data
range and never read the windows. All three are count-type, so they are zero-filled for every
service with a log row (02 §3.1): a service that stops logging shows zeros, not missing data.
"""

from __future__ import annotations

from typing import Any, Final

import duckdb
import pyarrow as pa

from veyltrace_signalyth.loglines import NS, LogRules
from veyltrace_signalyth.templates import TemplateRow

__all__ = ["load_templates", "log_series", "template_rows"]

_SERIES: Final = ("service", "signal", "family", "klass", "unit", "t_ns", "value")
_TEMPLATES: Final = (
    "service", "template_id", "template", "count_baseline", "count_incident", "error_level", "first_seen_ns",
)  # fmt: skip


def load_templates(con: duckdb.DuckDBPyConnection, rows: list[TemplateRow]) -> None:
    """Create the table `tmpl(service, masked, template_id, template)` from the mined rows."""
    names = ("service", "masked", "template_id", "template")
    array: Any = pa.array  # pyarrow-stubs overloads carry Unknown parts (as api._table)
    columns = [array([r[i] for r in rows], type=pa.string()) for i in range(len(names))]
    con.register("tmpl_in", pa.Table.from_arrays(columns, names=list(names)))
    con.execute("CREATE OR REPLACE TEMP TABLE tmpl AS SELECT * FROM tmpl_in")
    con.unregister("tmpl_in")


def template_rows(
    con: duckdb.DuckDBPyConnection, windows: dict[str, tuple[int, int]]
) -> dict[str, list[Any]]:
    """`signal_cube.templates` columns: every template with its line counts per (half-open) alert
    window, whether any of its lines is error-level, and its earliest line in the data range."""
    (b0, b1), (i0, i1) = windows["baseline"], windows["incident"]
    rows = con.execute(
        "SELECT t.service, t.template_id, t.template, "
        "count(*) FILTER (l.t_ns >= ? AND l.t_ns < ?), count(*) FILTER (l.t_ns >= ? AND l.t_ns < ?), "
        "bool_or(l.error), min(l.t_ns) "
        "FROM lines l JOIN tmpl t ON l.service = t.service AND l.masked = t.masked "
        "GROUP BY t.service, t.template_id, t.template ORDER BY t.service, t.template_id",
        [b0, b1, i0, i1],
    ).fetchall()
    return {name: [r[i] for r in rows] for i, name in enumerate(_TEMPLATES)}


def log_series(
    con: duckdb.DuckDBPyConnection, rules: LogRules, data_start: int, data_end: int
) -> dict[str, list[Any]]:
    """Log series columns on the bucket grid from `data_start` to `data_end`: `log_rate` and
    `log_error_rate` per service, and `tmpl:{template_id}` for templates with at least
    `min_template_count` lines, at most `max_template_series_per_service` per service by (lines
    desc, template_id asc)."""
    b = rules.bucket_ns
    first, n_buckets = (data_start // b) * b, int(data_end // b - data_start // b) + 1
    seconds = b / NS
    lines: dict[str, dict[int, tuple[int, int]]] = {}
    for service, t, n, errors in con.execute(
        "SELECT service, (t_ns // ?) * ?, count(*), count(*) FILTER (error) FROM lines GROUP BY 1, 2", [b, b]
    ).fetchall():
        lines.setdefault(str(service), {})[int(t)] = (int(n), int(errors))
    per_template: dict[str, dict[str, dict[int, int]]] = {}
    for service, tid, t, n in con.execute(
        "SELECT t.service, t.template_id, (l.t_ns // ?) * ?, count(*) "
        "FROM lines l JOIN tmpl t ON l.service = t.service AND l.masked = t.masked GROUP BY 1, 2, 3",
        [b, b],
    ).fetchall():
        per_template.setdefault(str(service), {}).setdefault(str(tid), {})[int(t)] = int(n)
    cols: dict[str, list[Any]] = {k: [] for k in _SERIES}
    grid = [first + k * b for k in range(n_buckets)]

    def emit(service: str, signal: str, klass: str, unit: str, values: list[float]) -> None:
        for name, item in zip(_SERIES[:5], (service, signal, "logs", klass, unit), strict=True):
            cols[name].extend([item] * n_buckets)
        cols["t_ns"].extend(grid)
        cols["value"].extend(values)

    for service in sorted(lines):
        seen = lines[service]
        emit(service, "log_rate", "context", "1/s", [seen.get(t, (0, 0))[0] / seconds for t in grid])
        emit(service, "log_error_rate", "internal", "1/s", [seen.get(t, (0, 0))[1] / seconds for t in grid])
        totals = sorted((-sum(c.values()), tid) for tid, c in per_template.get(service, {}).items())
        kept = [tid for total, tid in totals if -total >= rules.min_template_count]
        for tid in kept[: rules.max_template_series_per_service]:
            counts = per_template[service][tid]
            emit(service, f"tmpl:{tid}", "internal", "count", [float(counts.get(t, 0)) for t in grid])
    return cols
