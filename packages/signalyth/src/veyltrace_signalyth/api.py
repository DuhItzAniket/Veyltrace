"""Engine entry point of Signalyth (registered as `veyltrace.engines:signalyth`; 02 §2).

Pipeline step 2: telemetry → `signal_cube`. Metric series on their native grid and trace series on
the 10 s grid never read `alert.json`; edges and the critical path are per alert window. Log
lines are masked and mined into Drain3 templates per service; log series and template text never
read `alert.json`, only the templates' per-window counts do. `telemetry.events` and the alert hint
are never read (02-signalyth AGENTS Never 1).
"""

from __future__ import annotations

from typing import Any, Final

import pyarrow as pa

from veyltrace_contracts.models import Alert, CaseManifest
from veyltrace_core import duck, io
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_signalyth.loglines import LOG_COLUMNS, LogRules, load_lines
from veyltrace_signalyth.logseries import load_templates, log_series, template_rows
from veyltrace_signalyth.metrics import MetricRules, metric_series
from veyltrace_signalyth.paths import critical_path_rows, edge_rows, trace_paths
from veyltrace_signalyth.spans import SPAN_COLUMNS, TraceRules, build_forest, trace_series
from veyltrace_signalyth.templates import distinct_messages, mine_templates

__all__ = ["run"]

METRIC_COLUMNS: Final = ("t_ns", "service", "component", "name", "value", "unit")


def _table(contract: str, cols: dict[str, list[Any]]) -> pa.Table:
    schema: Any = io.arrow_schema(contract)
    array: Any = pa.array  # pyarrow-stubs overloads carry Unknown parts
    return pa.Table.from_arrays(
        [array(cols[n], type=schema.field(n).type) for n in schema.names], schema=schema
    )


def _series(parts: list[tuple[str, dict[str, list[Any]]]]) -> dict[str, list[Any]]:
    """Concatenate (source, columns) parts into series columns with their series_id."""
    out: dict[str, list[Any]] = {n: [] for n in io.arrow_schema("signal_cube.series").names}
    for source, cols in parts:
        n = len(cols["t_ns"])
        components = cols.get("component", cols["service"])  # trace series: component = service
        out["series_id"] += [
            f"{s}|{c}|{g}|{source}"
            for s, c, g in zip(cols["service"], components, cols["signal"], strict=True)
        ]
        out["component"] += list(components)
        out["source"] += [source] * n
        for name in ("service", "signal", "family", "klass", "unit", "t_ns", "value"):
            out[name] += cols[name]
    return out


def run(ctx: RunContext) -> EngineResult:
    """Write `signal_cube/{series,edges,templates,critical_path}.parquet` (02 §2)."""
    manifest = ctx.read_model("case_manifest", CaseManifest)
    alert = ctx.read_model("alert", Alert)
    w = alert.windows
    windows = {
        "baseline": (int(w.baseline[0]), int(w.baseline[1])),
        "incident": (int(w.incident[0]), int(w.incident[1])),
    }
    parts: list[tuple[str, dict[str, list[Any]]]] = []
    edges: dict[str, list[Any]] = {n: [] for n in io.arrow_schema("signal_cube.edges").names}
    critical: dict[str, list[Any]] = {n: [] for n in io.arrow_schema("signal_cube.critical_path").names}
    if manifest.sources.metrics:
        metrics = ctx.read_table("telemetry.metrics", columns=METRIC_COLUMNS)
        parts.append(("metrics", metric_series(metrics, MetricRules.from_config(ctx.config))))
    if manifest.sources.traces:
        rules = TraceRules.from_config(ctx.config)
        forest = build_forest(ctx.read_table("telemetry.spans", columns=SPAN_COLUMNS), rules, ctx.case_id)
        parts.append(("traces", trace_series(forest, rules, manifest.data_start_ns, manifest.data_end_ns)))
        edges = edge_rows(forest, rules, windows)
        paths = trace_paths(forest, rules, windows, ctx.case_id)
        critical = critical_path_rows(forest, paths, rules.min_spans_per_quantile)
    templates: dict[str, list[Any]] = {n: [] for n in io.arrow_schema("signal_cube.templates").names}
    notes: tuple[str, ...] = ()
    if manifest.sources.logs:
        log_rules = LogRules.from_config(ctx.config)
        logs = ctx.read_table("telemetry.logs", columns=LOG_COLUMNS)
        with duck.connect(ctx.config, ctx.run_dir) as con:
            load_lines(con, logs, log_rules)
            mined, fallback = mine_templates(distinct_messages(con), log_rules.drain)
            load_templates(con, mined)
            templates = template_rows(con, windows)
            parts.append(("logs", log_series(con, log_rules, manifest.data_start_ns, manifest.data_end_ns)))
        notes = tuple(f"drain3 failed for {s}: its masked messages are its templates" for s in fallback)
    outputs = [
        ("signal_cube.series", ctx.write("signal_cube.series", _table("signal_cube.series", _series(parts)))),
        ("signal_cube.edges", ctx.write("signal_cube.edges", _table("signal_cube.edges", edges))),
        (
            "signal_cube.templates",
            ctx.write("signal_cube.templates", _table("signal_cube.templates", templates)),
        ),
        (
            "signal_cube.critical_path",
            ctx.write("signal_cube.critical_path", _table("signal_cube.critical_path", critical)),
        ),
    ]
    return EngineResult(engine="signalyth", status="ok", outputs=tuple(sorted(outputs)), notes=notes)
