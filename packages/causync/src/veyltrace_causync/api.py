"""Engine entry point of Causync (registered as `veyltrace.engines:causync`; 04 §2).

Pipeline step 4: writes `alignment.json` (clock offsets onto the reference clock and the
comparison tolerance) and `changes` (the change timeline with its evidence). Telemetry is never
rewritten: offsets are published and consumers add them. A case without change events gets a
zero-row `changes`, which is the expected abstention on public benchmarks, not an error.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from veyltrace_causync.changes import EVENT_COLUMNS, aligned_onsets, aligned_t_onset, evidence, timeline
from veyltrace_causync.crossalign import JOIN_LOG_COLUMNS, comovement_offset, log_span_offsets
from veyltrace_causync.peers import ANOMALY_COLUMNS, peer_contrast, replica_scores, replicas
from veyltrace_causync.settings import causync_config
from veyltrace_causync.steps import SERIES_COLUMNS, source_steps, tolerance
from veyltrace_causync.tracepairs import PAIR_COLUMNS, Offset, trace_offsets
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import duck, io
from veyltrace_core.context import EngineResult, RunContext

__all__ = ["run"]


def _table(contract: str, cols: dict[str, list[Any]]) -> pa.Table:
    schema: Any = io.arrow_schema(contract)
    array: Any = pa.array  # pyarrow-stubs overloads carry Unknown parts
    return pa.Table.from_arrays(
        [array(cols[n], type=schema.field(n).type) for n in schema.names], schema=schema
    )


def run(ctx: RunContext) -> EngineResult:
    """Write `alignment` and `changes` for one run (04 §2)."""
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    onsets = ctx.read_model("onsets", models.Onsets)
    cfg = causync_config(ctx.config)
    sources = manifest.sources
    series = ctx.read_table("signal_cube.series", columns=SERIES_COLUMNS)
    steps = source_steps(series)
    tol = tolerance(source_steps(series, cfg.align.tolerance_step_quantile))
    reference = "traces" if sources.traces else "metrics"  # 03 §5.1, also for a logs-only case
    offsets: list[Offset] = []
    spans = ctx.read_table("telemetry.spans", columns=PAIR_COLUMNS) if sources.traces else None
    if spans is not None:
        offsets.append(Offset("traces", None, 0, "reference", 1.0))
        offsets += trace_offsets(spans, list(onsets.entry_services), cfg.align)
    if sources.metrics:
        if reference == "metrics":
            offsets.append(Offset("metrics", None, 0, "reference", 1.0))
        else:
            offsets.append(comovement_offset(series, "metrics", reference, steps, cfg.align))
    if sources.logs:
        joined: list[Offset] = []
        if spans is not None:
            logs = ctx.read_table("telemetry.logs", columns=JOIN_LOG_COLUMNS)
            per_service = {o.service: o.offset_ns for o in offsets if o.source == "traces" and o.service}
            joined = log_span_offsets(logs, spans, cfg.align, per_service)
        offsets += joined or [comovement_offset(series, "logs", reference, steps, cfg.align)]
    if sources.events:
        offsets.append(Offset("events", None, 0, "none", 0.0))  # no estimator for events (04 §3.3)
    offsets.sort(key=lambda o: (o.source, o.service is not None, o.service or ""))
    alignment = {
        "schema_version": CONTRACTS["alignment"].version,
        "reference": reference,
        "offsets": [o.as_dict() for o in offsets],
        "tolerance_ns": tol,
    }
    pods = replicas(series)
    changes = []
    if sources.events:
        events = ctx.read_table("telemetry.events", columns=EVENT_COLUMNS)
        changes = timeline(events, list(manifest.services), pods.service_of, cfg)
    by_service = aligned_onsets(onsets, offsets)
    t_onset = aligned_t_onset(onsets, offsets)
    with duck.connect(ctx.config, ctx.run_dir) as con:
        cols = evidence(con, changes, by_service, t_onset, tol, cfg)
    if changes:
        scores = replica_scores(ctx.read_table("anomalies", columns=ANOMALY_COLUMNS))
        metrics_offset = next(
            (o.offset_ns for o in offsets if o.source == "metrics" and o.service is None), 0
        )
        cols["peer_contrast"] = [
            peer_contrast(
                c, by_service.get(c.service or "", t_onset), pods, scores, cfg.min_replicas, metrics_offset
            )
            for c in changes
        ]
    outputs = [
        ("alignment", ctx.write("alignment", alignment)),
        ("changes", ctx.write("changes", _table("changes", cols))),
    ]
    return EngineResult(engine="causync", status="ok", outputs=tuple(sorted(outputs)))
