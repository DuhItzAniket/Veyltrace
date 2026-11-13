"""detect_alert's metrics fallback and its plugin registration (03-anomara §3.8 step 2, §7)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from veyltrace_anomara.alert import detect_alert
from veyltrace_anomara.settings import anomara_config
from veyltrace_anomara.slis import metric_slis, quantile_of
from veyltrace_contracts.models import CaseManifest
from veyltrace_core import io, plugins
from veyltrace_core.adapters import TelemetryTables
from veyltrace_core.config import EngineConfig, resolve_config

NS = 1_000_000_000
T0 = 1_767_225_600 * NS
STEP = 15 * NS
N = 80  # 20 min of 15 s scrapes


def _config() -> EngineConfig:
    return resolve_config({}, dataset="synth", ai_mode="off").engine("anomara")


def _manifest() -> CaseManifest:
    return CaseManifest.model_validate(
        {
            "schema_version": "0.1.0",
            "case_id": "c0c0c0c0c0c0",
            "dataset": "handmade",
            "system": "ss",
            "t_alert_hint_ns": None,
            "hint_source": "none",
            "data_start_ns": T0,
            "data_end_ns": T0 + N * STEP,
            "sources": {"metrics": True, "logs": False, "traces": False, "events": False},
            "services": ["carts", "front-end"],
            "inputs": [],
            "adapter": {"name": "handmade", "version": "1"},
            "scrub": {"rules_version": "none", "dropped_attributes": 0, "dropped_rows": 0},
        }
    )


def _metrics(series: dict[tuple[str, str | None], list[float]]) -> TelemetryTables:
    """front-end metrics, one point per 15 s scrape: {(name, unit): values}."""
    rows: list[dict[str, Any]] = []
    for (name, unit), values in sorted(series.items(), key=lambda kv: kv[0][0]):
        for k, value in enumerate(values):
            rows.append(
                {
                    "t_ns": T0 + k * STEP,
                    "service": "front-end",
                    "component": "front-end",
                    "name": name,
                    "metric_type": None,
                    "attrs_json": None,
                    "value": value,
                    "unit": unit,
                    "source_system": "csv",
                }
            )
    table = pa.Table.from_pylist(rows, schema=io.arrow_schema("telemetry.metrics"))
    return TelemetryTables.from_tables(metrics=io.conform_table("telemetry.metrics", table))


def _wiggle(base: float, after: float | None = None, at: int = N) -> list[float]:
    return [(after if k >= at and after is not None else base) * (1.0 + 0.01 * (k % 3 - 1)) for k in range(N)]


@pytest.mark.parametrize(
    ("name", "q"),
    [
        ("latency-90", 0.9),
        ("front-end_latency-50", 0.5),
        ("latency_p99", 0.99),
        ("duration{quantile=0.999}", 0.999),
        ('latency{quantile="0.99"}', 0.99),
        ("latency{quantile=1}", 1.0),
        ("latency_p99.9", 0.999),
        ("frontend-2_latency", -1.0),  # a hyphen-digit inside the name is not a quantile
        ("http2_latency", -1.0),
        ("latency", -1.0),
    ],
)
def test_quantile_in_the_name(name: str, q: float) -> None:
    assert quantile_of(name) == q


def test_a_histograms_count_and_sum_are_not_the_latency_sli() -> None:
    # Infralume keeps a histogram as <name>_count and <name>_sum counters (01-infralume §3.9).
    tables = _metrics(
        {
            ("front-end_http_server_duration_count", None): [float(5 * k) for k in range(N)],
            ("front-end_http_server_duration_sum", "s"): [float(k) for k in range(N)],
            ("front-end_latency_p90", "s"): _wiggle(0.02),
        }
    )
    slis = metric_slis(tables.metrics, "front-end", anomara_config(_config()).slo)
    assert [s.signal for s in slis if s.family == "latency"] == ["front-end_latency_p90"]


def test_highest_quantile_latency_in_ms_and_counter_rates() -> None:
    tables = _metrics(
        {
            ("front-end_latency-50", "s"): _wiggle(0.01),
            ("front-end_latency-90", "s"): _wiggle(0.02),
            ("front-end_errors_total", None): [float(3 * k) for k in range(N)],
        }
    )
    slis = metric_slis(tables.metrics, "front-end", anomara_config(_config()).slo)
    latency, errors = slis
    assert (latency.signal, errors.signal) == ("front-end_latency-90", "front-end_errors_total")
    assert latency.x.max() == pytest.approx(20.0 * 1.01)  # seconds -> ms
    assert errors.x.tolist() == pytest.approx([0.2] * (N - 1))  # 3 per 15 s scrape -> 0.2 per second


def test_metrics_fallback_finds_a_latency_breach_on_the_hinted_entry() -> None:
    tables = _metrics({("front-end_latency-90", "s"): _wiggle(0.02, 0.08, at=60)})
    found = detect_alert(tables, _manifest(), _config())
    assert found is not None
    assert (found.t_alert_ns, found.signal, found.entry_services) == (
        T0 + 60 * STEP,
        "front-end_latency-90",
        ("front-end",),
    )


def test_metrics_fallback_is_quiet_on_flat_metrics() -> None:
    assert (
        detect_alert(_metrics({("front-end_latency-90", "s"): _wiggle(0.02)}), _manifest(), _config()) is None
    )


def test_core_finds_the_default_alert_detector() -> None:
    # D-2: core's alert step loads veyltrace.alert_detectors:default (declared in pyproject.toml).
    assert plugins.load_one(plugins.ALERT_DETECTORS, plugins.ALERT_DETECTOR_NAME) is detect_alert
