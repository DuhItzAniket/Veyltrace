"""alert: protocols, onset shift, half-open windows clamped to the data span, rejections (03 §2.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts.models import Alert, CaseManifest
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import plugins
from veyltrace_core.adapters import AlertDetection, TelemetryTables
from veyltrace_core.alert import NS_PER_S, clamp_window, compute_alert, run_alert_step
from veyltrace_core.config import resolve_config
from veyltrace_core.context import RunContext
from veyltrace_core.errors import CaseRejected, ConfigError, NoAlert
from veyltrace_core.ids import case_id
from veyltrace_core.plugins import Plugin

REPO = Path(__file__).resolve().parents[3]
T0 = 1_700_000_000_000_000_000
SPAN_S = 1920
HINT = T0 + 1320 * NS_PER_S
CASE = case_id("synth-01")


def manifest(hint: int | None = HINT, start: int = T0, end: int = T0 + SPAN_S * NS_PER_S) -> CaseManifest:
    return CaseManifest.model_validate(
        dict(
            schema_version=CONTRACTS["case_manifest"].version,
            case_id=CASE,
            dataset="synth",
            system="ob",
            t_alert_hint_ns=hint,
            hint_source="oracle" if hint is not None else "none",
            data_start_ns=start,
            data_end_ns=end,
            sources={"metrics": True, "logs": True, "traces": True, "events": True},
            services=["checkout", "frontend"],
            inputs=[],
            adapter={"name": "synth", "version": "1"},
            scrub={"rules_version": "1", "dropped_attributes": 0, "dropped_rows": 0},
        )
    )


def core(protocol: str = "oracle", shift_s: Any = 0, reject: Any = True, **windows: Any) -> dict[str, Any]:
    return {
        "alert": {"protocol": protocol, "shift_s": shift_s, "reject_hint_outside_span": reject},
        "windows": {"baseline_s": [-1200, -120], "incident_s": [-120, 480], **windows},
    }


def test_oracle_default_windows() -> None:
    alert = compute_alert(manifest(), core())
    assert alert.t_alert_ns == HINT
    assert alert.shift_ns == 0
    assert alert.detector is None
    assert alert.windows.baseline == (HINT - 1200 * NS_PER_S, HINT - 120 * NS_PER_S)
    assert alert.windows.incident == (HINT - 120 * NS_PER_S, HINT + 480 * NS_PER_S)
    assert alert.clamped is False


def test_shift_applies_to_t_alert_and_windows() -> None:
    alert = compute_alert(manifest(), core(shift_s=-120))
    assert alert.shift_ns == -120 * NS_PER_S
    assert alert.t_alert_ns == HINT - 120 * NS_PER_S
    assert alert.windows.incident[0] == alert.t_alert_ns - 120 * NS_PER_S


def test_clamping_is_half_open_at_data_end() -> None:
    end = HINT + 100 * NS_PER_S
    alert = compute_alert(manifest(end=end), core())
    assert alert.windows.incident == (HINT - 120 * NS_PER_S, end + 1)
    assert alert.clamped is True
    assert clamp_window((5, 9), 6, 7) == ((6, 8), True)
    assert clamp_window((6, 8), 6, 7) == ((6, 8), False)


def test_rejections() -> None:
    with pytest.raises(CaseRejected) as err:
        compute_alert(manifest(hint=None), core())
    assert err.value.reason == "no_hint"
    outside = T0 - 5 * NS_PER_S
    with pytest.raises(CaseRejected) as err:
        compute_alert(manifest(hint=outside), core())
    assert err.value.reason == "hint_outside_span"
    with pytest.raises(CaseRejected) as err:  # allowed outside the span, but the baseline is empty
        compute_alert(manifest(hint=outside), core(reject=False))
    assert err.value.reason == "empty_window"


@pytest.mark.parametrize(
    "cfg",
    [
        core(protocol="psychic"),
        core(shift_s=1.5),
        core(shift_s=True),
        core(reject="yes"),
        core(baseline_s=[-120]),
        core(baseline_s=[10, -10]),
        core(incident_s="0,1"),
        {"alert": {"protocol": "oracle", "shift_s": 0, "reject_hint_outside_span": True}},
    ],
)
def test_bad_config(cfg: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        compute_alert(manifest(), cfg)


def test_detected_uses_detector_and_hides_hint() -> None:
    seen: list[CaseManifest] = []

    def detector(telemetry: TelemetryTables, m: CaseManifest, config: Any) -> AlertDetection | None:
        seen.append(m)
        assert config == "anomara-config"
        return AlertDetection(HINT + 60 * NS_PER_S, ("web", "api"), "latency_p99", 0.5)

    alert = compute_alert(
        manifest(),
        core(protocol="detected", shift_s=30),
        telemetry=TelemetryTables.from_tables(),
        detector=detector,
        detector_config="anomara-config",
    )
    assert seen[0].t_alert_hint_ns is None
    assert alert.t_alert_ns == HINT + 90 * NS_PER_S
    assert alert.detector is not None
    assert alert.detector.entry_services == ["api", "web"]
    assert alert.detector.signal == "latency_p99"
    with pytest.raises(NoAlert):
        compute_alert(
            manifest(),
            core(protocol="detected"),
            telemetry=TelemetryTables.from_tables(),
            detector=lambda *_: None,
        )
    with pytest.raises(ConfigError):
        compute_alert(manifest(), core(protocol="detected"), telemetry=TelemetryTables.from_tables())


def _ctx(tmp_path: Path, overrides: dict[str, Any] | None = None, step: str = "alert") -> RunContext:
    resolved = resolve_config(overrides or {}, config_dir=REPO / "config", ai_mode="off")
    return RunContext(
        case_id=CASE,
        run_id="0123456789abcdef",
        dataset="synth",
        run_dir=tmp_path,
        ai_mode="off",
        engine="core",
        config=resolved.engine("core"),
        step=step,
        resolved=resolved,
    )


def test_run_alert_step_writes_alert_json(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, step="")  # the step name is forced to "alert", so the hint is visible
    ctx.write("case_manifest", manifest())
    result = run_alert_step(ctx)
    assert result.engine == "core"
    assert [n for n, _ in result.outputs] == ["alert"]
    stored = ctx.read("alert")
    assert isinstance(stored, Alert)
    assert stored.t_alert_ns == HINT
    assert (tmp_path / "alert.json").read_bytes().endswith(b"}\n")


def test_run_alert_step_detected_without_plugin_is_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugins, "discover", lambda group: ())
    ctx = _ctx(tmp_path, {"core.alert.protocol": "detected"})
    ctx.write("case_manifest", manifest(hint=None))
    with pytest.raises(ConfigError, match="alert_detectors:default"):
        run_alert_step(ctx)


def test_run_alert_step_detected_gets_run_anomara_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got: list[Any] = []

    def detector(telemetry: TelemetryTables, m: CaseManifest, config: Any) -> AlertDetection | None:
        got.append(config)
        return None

    found = (Plugin(plugins.ALERT_DETECTORS, "default", "x:y", "d", lambda: detector),)
    monkeypatch.setattr(plugins, "discover", lambda group: found if group == plugins.ALERT_DETECTORS else ())
    ctx = _ctx(tmp_path, {"core.alert.protocol": "detected"})
    ctx.write("case_manifest", manifest(hint=None))
    with pytest.raises(NoAlert):
        run_alert_step(ctx)
    assert got[0].engine == "anomara"
    assert not (tmp_path / "alert.json").exists()


def test_provisional_manifest_describes_live_tables() -> None:
    import pyarrow as pa

    from veyltrace_core import io
    from veyltrace_core.alert import provisional_manifest

    t0 = 1_767_225_600_000_000_000
    row = {
        "component": "c-1",
        "name": "cpu",
        "metric_type": "gauge",
        "attrs_json": "{}",
        "value": 1.0,
        "unit": "1",
        "source_system": "prometheus",
    }
    rows = [{**row, "t_ns": t0, "service": "cart"}, {**row, "t_ns": t0 + 60, "service": "api"}]
    schema = io.arrow_schema("telemetry.metrics")
    metrics = pa.Table.from_pylist([{n: r[n] for n in schema.names} for r in rows], schema=schema)
    tables = TelemetryTables.from_tables(metrics=metrics)
    m = provisional_manifest("ob", tables)
    assert (m.data_start_ns, m.data_end_ns) == (t0, t0 + 60)
    assert m.services == ["api", "cart"]
    assert (m.sources.metrics, m.sources.logs, m.sources.traces, m.sources.events) == (
        True,
        False,
        False,
        False,
    )
    assert (m.t_alert_hint_ns, m.hint_source, m.dataset, m.adapter.name) == (
        None,
        "none",
        "live",
        "otlp_live",
    )
    assert provisional_manifest("ob", tables).case_id == m.case_id  # same window, same id
    io.prepare("case_manifest", m)  # schema-valid
    with pytest.raises(ValueError, match="empty"):
        provisional_manifest("ob", TelemetryTables.from_tables())
