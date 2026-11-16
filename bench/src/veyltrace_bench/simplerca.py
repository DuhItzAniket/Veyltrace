"""SimpleRCA, the alert-count baseline `simplerca` (04 §4; Fang et al., arXiv 2510.04711v2 §3.1.2).

Rule-based alerts per source, then the service with the most alerts first. Metric alert: one per
series whose detection-window mean exceeds mean + k sigma or the P-th percentile of its history. Trace
alert: one per service whose detection-window P95 span latency is at least `factor` times its
history P95. Log alert: one per service whose rate of lines matching an error keyword rises above
`factor` times its history rate. History and detection windows come from the run's `alert.json`
(history = windows.baseline, detection = [t_alert, incident end)), so the baseline gets the same
t_alert as Veyltrace (04 §4). It reads Infralume's normalised tables only (03 §2), never raw data.
Thresholds live in bench/baselines.yaml with their sources; ties go A→Z (a priori).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

from veyltrace_contracts.models import Alert, CaseManifest
from veyltrace_core import io

type Vec = np.ndarray[Any, Any]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricRule(_Strict):
    sigma: float = Field(gt=0)
    percentile: float = Field(gt=0, lt=100)


class TraceRule(_Strict):
    percentile: float = Field(gt=0, lt=100)
    factor: float = Field(gt=0)


class LogRule(_Strict):
    keywords: tuple[str, ...] = Field(min_length=1)
    factor: float = Field(gt=0)
    min_count: int = Field(ge=1)


class SimpleRcaConfig(_Strict):
    """The `simplerca` section of bench/baselines.yaml (values and sources there)."""

    metric: MetricRule
    trace: TraceRule
    log: LogRule


def _in(t: Vec, window: tuple[int, int]) -> Vec:
    """Mask of timestamps in the half-open window [start, end) (03 §2.6)."""
    return (t >= window[0]) & (t < window[1])


def _groups(table: pa.Table, keys: Sequence[str]) -> Iterable[tuple[tuple[str, ...], Vec]]:
    """(key values, row indices) per distinct key, keys sorted, so alerts never depend on row order."""
    cols = [np.asarray(table.column(k).to_pylist(), dtype=object) for k in keys]
    index: dict[tuple[str, ...], list[int]] = {}
    for i, key in enumerate(zip(*cols, strict=True)):
        index.setdefault(tuple(str(v) for v in key), []).append(i)
    for key in sorted(index):
        yield key, np.asarray(index[key], dtype=np.int64)


def metric_alerts(
    metrics: pa.Table, history: tuple[int, int], detect: tuple[int, int], rule: MetricRule
) -> Counter[str]:
    """Alerting series per service: detection mean > min(mean + k sigma, P-th percentile) of history.
    A series without history or detection points cannot alert."""
    t = np.asarray(metrics.column("t_ns").to_numpy(), dtype=np.int64)
    v = np.asarray(metrics.column("value").to_numpy(), dtype=np.float64)
    out: Counter[str] = Counter()
    for (service, _component, _name), rows in _groups(metrics, ("service", "component", "name")):
        h, d = v[rows][_in(t[rows], history)], v[rows][_in(t[rows], detect)]
        if h.size == 0 or d.size == 0:
            continue
        threshold = min(float(h.mean() + rule.sigma * h.std()), float(np.percentile(h, rule.percentile)))
        if float(d.mean()) > threshold:
            out[service] += 1
    return out


def trace_alerts(
    spans: pa.Table, history: tuple[int, int], detect: tuple[int, int], rule: TraceRule
) -> Counter[str]:
    """One alert per service whose detection P95 latency is >= factor x its history P95 (> 0)."""
    start = np.asarray(spans.column("start_ns").to_numpy(), dtype=np.int64)
    latency = np.asarray(spans.column("end_ns").to_numpy(), dtype=np.int64) - start
    out: Counter[str] = Counter()
    for (service,), rows in _groups(spans, ("service",)):
        h, d = latency[rows][_in(start[rows], history)], latency[rows][_in(start[rows], detect)]
        if h.size == 0 or d.size == 0:
            continue
        base = float(np.percentile(h, rule.percentile))
        if base > 0 and float(np.percentile(d, rule.percentile)) >= rule.factor * base:
            out[service] = 1
    return out


def log_alerts(
    logs: pa.Table, history: tuple[int, int], detect: tuple[int, int], rule: LogRule
) -> Counter[str]:
    """One alert per service whose matching-line rate in detection > factor x its history rate."""
    t = np.asarray(logs.column("t_ns").to_numpy(), dtype=np.int64)
    bodies = [str(b).lower() for b in logs.column("body").to_pylist()]
    hit = np.asarray([any(k in b for k in rule.keywords) for b in bodies], dtype=bool)
    span_h, span_d = max(history[1] - history[0], 1), max(detect[1] - detect[0], 1)
    out: Counter[str] = Counter()
    for (service,), rows in _groups(logs, ("service",)):
        n_h = int((hit[rows] & _in(t[rows], history)).sum())
        n_d = int((hit[rows] & _in(t[rows], detect)).sum())
        if n_d >= rule.min_count and n_d / span_d > rule.factor * n_h / span_h:
            out[service] = 1
    return out


def rank(services: Iterable[str], alerts: Mapping[str, int]) -> tuple[str, ...]:
    """Every service once, most alerts first, ties A→Z (a priori)."""
    return tuple(sorted(set(services) | set(alerts), key=lambda s: (-alerts.get(s, 0), s)))


def windows(alert: Alert) -> tuple[tuple[int, int], tuple[int, int]]:
    """(history, detection): windows.baseline and [t_alert, incident end) of alert.json."""
    base, incident = alert.windows.baseline, alert.windows.incident
    return (base[0], base[1]), (alert.t_alert_ns, max(alert.t_alert_ns, incident[1]))


def run(run_dir: Path, cfg: SimpleRcaConfig) -> tuple[str, ...]:
    """SimpleRCA's ranks for the case in `run_dir` (a run through core's alert step)."""
    case = io.read_model("case_manifest", run_dir, CaseManifest)
    history, detect = windows(io.read_model("alert", run_dir, Alert))
    alerts = metric_alerts(io.read_table("telemetry.metrics", run_dir), history, detect, cfg.metric)
    alerts.update(trace_alerts(io.read_table("telemetry.spans", run_dir), history, detect, cfg.trace))
    alerts.update(log_alerts(io.read_table("telemetry.logs", run_dir), history, detect, cfg.log))
    return rank(case.services, alerts)
