"""Core's alert step (pipeline step 1): alert time, onset shift and analysis windows (02 §5.1).

Engines never see the injection time; they read `alert.json`, written here (03 §2.6):

- `oracle` / `live`: the base time is case_manifest.t_alert_hint_ns (the dataset's published
  injection time, or the live trigger). A missing hint, or one outside the data span when
  `core.alert.reject_hint_outside_span` is set, rejects the case (01 §11 Q8).
- `detected`: the base time is the first sustained SLO breach found by the
  `veyltrace.alert_detectors:default` plugin (Anomara, D-2), called with the run's own Anomara
  config so experiment overrides and replay locks apply (critic gap, accepted). No breach is
  NoAlert; a missing plugin is a ConfigError.
- Every protocol then adds `core.alert.shift_s` (whole seconds) and builds the half-open
  baseline and incident windows from `core.windows`, clamped to [data_start_ns, data_end_ns + 1).
  An empty window rejects the case (D-14).

This step and Infralume are the only readers of t_alert_hint_ns (packages/core/AGENTS.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast, get_args

from veyltrace_contracts.models import (
    Alert,
    AlertDetector,
    AlertProtocol,
    AlertWindows,
    CaseManifest,
)
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io as contract_io
from veyltrace_core.adapters import AlertDetection, DetectAlert, TelemetryTables
from veyltrace_core.context import EngineResult, RunContext, redact_hint
from veyltrace_core.errors import CaseRejected, ConfigError, ContractValidationError, NoAlert
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.steps import CORE_ENGINE

__all__ = [
    "ALERT_STEP",
    "NS_PER_S",
    "PROTOCOLS",
    "Window",
    "clamp_window",
    "compute_alert",
    "provisional_manifest",
    "run_alert_step",
]

ALERT_STEP = "alert"
NS_PER_S = 1_000_000_000  # 03 §2.6: shift_ns = shift_s * 10^9; windows are config seconds
PROTOCOLS: tuple[str, ...] = get_args(AlertProtocol)
#: Defaults of the provisional manifest the gateway watcher builds from live OTLP tables
#: (core_api_spec §11). The dataset name is the live namespace; the scrub has not run yet
#: (Infralume scrubs when it materialises the case), so its counts are zero.
LIVE_DATASET = "live"
LIVE_ADAPTER = "otlp_live"
LIVE_ADAPTER_VERSION = "0"
LIVE_SCRUB_RULES = "unscrubbed"
#: (source flag in case_manifest.sources, TelemetryTables attribute, start column, end column).
_SPAN_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("metrics", "metrics", "t_ns", "t_ns"),
    ("logs", "logs", "t_ns", "t_ns"),
    ("traces", "spans", "start_ns", "end_ns"),
    ("events", "events", "t_ns", "t_ns"),
)
#: Telemetry whose `service` column names a service (events name entities, not services).
_SERVICE_TABLES: tuple[str, ...] = ("metrics", "logs", "spans")

#: A half-open [start_ns, end_ns) window.
Window = tuple[int, int]


def _section(core: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = core.get(key)
    if not isinstance(value, Mapping):
        msg = f"core.{key} must be a mapping"
        raise ConfigError(msg)
    return cast("Mapping[str, Any]", value)


def _int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{key} must be an integer number of seconds, got {value!r}"
        raise ConfigError(msg)
    return value


def _offsets(value: object, key: str) -> tuple[int, int]:
    """A [start_s, end_s] pair of integer second offsets with start <= end."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"{key} must be a [start_s, end_s] pair, got {value!r}"
        raise ConfigError(msg)
    pair = cast("Sequence[object]", value)
    if len(pair) != 2:
        msg = f"{key} must be a [start_s, end_s] pair, got {value!r}"
        raise ConfigError(msg)
    start, end = _int(pair[0], f"{key}[0]"), _int(pair[1], f"{key}[1]")
    if start > end:
        msg = f"{key} start {start} is after end {end}"
        raise ConfigError(msg)
    return start, end


def clamp_window(window: Window, data_start_ns: int, data_end_ns: int) -> tuple[Window, bool]:
    """Clamp a half-open window to [data_start_ns, data_end_ns + 1); return it and whether it moved.

    The upper bound is data_end_ns + 1 because the data span is inclusive (03 §2.1) while windows
    are half-open, so the last sample stays inside the incident window.
    """
    lo, hi = data_start_ns, data_end_ns + 1
    start = min(max(window[0], lo), hi)
    end = min(max(window[1], lo), hi)
    return (start, end), (start, end) != window


def _base_time(
    protocol: str,
    manifest: CaseManifest,
    alert_cfg: Mapping[str, Any],
    telemetry: TelemetryTables | None,
    detector: DetectAlert | None,
    detector_config: Any,
) -> tuple[int, AlertDetection | None]:
    if protocol == "detected":
        if detector is None:
            msg = "alert protocol 'detected' needs the veyltrace.alert_detectors:default plugin"
            raise ConfigError(msg)
        if telemetry is None:
            msg = "alert protocol 'detected' needs the case telemetry"
            raise ConfigError(msg)
        # The detector sees the descriptive manifest only, never the hint (02 §5.1).
        detection = detector(telemetry, redact_hint(manifest), detector_config)
        if detection is None:
            msg = "no sustained SLO breach on the entry services (detected protocol)"
            raise NoAlert(msg)
        if not isinstance(detection, AlertDetection):  # pyright: ignore[reportUnnecessaryIsInstance]  (plugin output)
            raise ContractValidationError("alert", f"detector returned {type(detection).__name__}")
        return detection.t_alert_ns, detection
    hint = manifest.t_alert_hint_ns
    if hint is None:
        raise CaseRejected("no_hint", f"protocol {protocol!r} needs case_manifest.t_alert_hint_ns")
    reject_outside = alert_cfg.get("reject_hint_outside_span")
    if not isinstance(reject_outside, bool):
        msg = f"core.alert.reject_hint_outside_span must be true or false, got {reject_outside!r}"
        raise ConfigError(msg)
    if reject_outside and not manifest.data_start_ns <= hint <= manifest.data_end_ns:
        detail = f"hint {hint} outside [{manifest.data_start_ns}, {manifest.data_end_ns}]"
        raise CaseRejected("hint_outside_span", detail)
    return hint, None


def compute_alert(
    manifest: CaseManifest,
    core: Mapping[str, Any],
    *,
    telemetry: TelemetryTables | None = None,
    detector: DetectAlert | None = None,
    detector_config: Any = None,
) -> Alert:
    """Compute alert.json from the manifest and the `core` config section (pure; no I/O).

    `detector` and `telemetry` are used only under the detected protocol, with `detector_config`
    (the run's Anomara EngineConfig) passed through to the detector.
    """
    alert_cfg = _section(core, "alert")
    windows_cfg = _section(core, "windows")
    protocol = alert_cfg.get("protocol")
    if protocol not in PROTOCOLS:
        msg = f"core.alert.protocol must be one of {PROTOCOLS}, got {protocol!r}"
        raise ConfigError(msg)
    protocol = cast("AlertProtocol", protocol)
    shift_ns = _int(alert_cfg.get("shift_s"), "core.alert.shift_s") * NS_PER_S
    baseline_s = _offsets(windows_cfg.get("baseline_s"), "core.windows.baseline_s")
    incident_s = _offsets(windows_cfg.get("incident_s"), "core.windows.incident_s")

    base, detection = _base_time(protocol, manifest, alert_cfg, telemetry, detector, detector_config)
    t_alert = base + shift_ns

    clamped = False
    bounds: dict[str, Window] = {}
    for name, (start_s, end_s) in (("baseline", baseline_s), ("incident", incident_s)):
        raw = (t_alert + start_s * NS_PER_S, t_alert + end_s * NS_PER_S)
        window, moved = clamp_window(raw, manifest.data_start_ns, manifest.data_end_ns)
        if window[0] >= window[1]:
            detail = f"{name} window {raw} is empty after clamping to the data span"
            raise CaseRejected("empty_window", detail)
        clamped = clamped or moved
        bounds[name] = window

    return Alert(
        schema_version=CONTRACTS["alert"].version,
        protocol=protocol,
        t_alert_ns=t_alert,
        shift_ns=shift_ns,
        detector=None
        if detection is None
        else AlertDetector(
            entry_services=list(detection.entry_services),
            signal=detection.signal,
            threshold=detection.threshold,
        ),
        windows=AlertWindows(baseline=bounds["baseline"], incident=bounds["incident"]),
        clamped=clamped,
    )


def run_alert_step(ctx: RunContext, *, detector: DetectAlert | None = None) -> EngineResult:
    """Pipeline step 1: read case_manifest (unredacted: this is the alert step), write alert.json.

    `detector` is the one the pipeline resolved in preflight; when it is None and the protocol is
    detected, it is loaded from `veyltrace.alert_detectors:default` (ConfigError if absent).
    """
    if ctx.step != ALERT_STEP:
        ctx = replace(ctx, step=ALERT_STEP)
    manifest = contract_io.read_unredacted("case_manifest", ctx.run_dir)  # D-15: the alert step
    if not isinstance(manifest, CaseManifest):  # pragma: no cover - io returns the model
        raise ContractValidationError("case_manifest", "did not read as a CaseManifest")
    core = ctx.config.core
    protocol = _section(core, "alert").get("protocol")

    telemetry: TelemetryTables | None = None
    detector_config: Any = None
    if protocol == "detected":
        if detector is None:
            from veyltrace_core import plugins  # lazy: importlib.metadata stays out of engines

            detector = cast(
                "DetectAlert",
                plugins.load_one(plugins.ALERT_DETECTORS, plugins.ALERT_DETECTOR_NAME),
            )
        if ctx.resolved is None:
            msg = "the detected alert protocol needs the run's ResolvedConfig (Anomara config)"
            raise ConfigError(msg)
        detector_config = ctx.resolved.engine("anomara")
        telemetry = TelemetryTables.from_run_dir(ctx.run_dir)

    alert = compute_alert(
        manifest, core, telemetry=telemetry, detector=detector, detector_config=detector_config
    )
    digest = ctx.write("alert", alert)
    notes = ("windows clamped to the data span",) if alert.clamped else ()
    return EngineResult(engine=CORE_ENGINE, status="ok", outputs=(("alert", digest),), notes=notes)


def _int_column(table: Any, column: str, source: str) -> list[int]:
    if column not in table.column_names:
        msg = f"provisional_manifest: {source} has no {column!r} column"
        raise ValueError(msg)
    return [int(v) for v in table.column(column).to_pylist() if v is not None]


def provisional_manifest(
    system: str,
    tables: TelemetryTables,
    adapter: str = LIVE_ADAPTER,
    *,
    dataset: str = LIVE_DATASET,
    adapter_version: str = LIVE_ADAPTER_VERSION,
) -> CaseManifest:
    """A case_manifest for live tables the gateway watcher holds before Infralume runs (§11).

    data_start/end span every non-empty table (span start/end included, 01 §3.8); services come
    from metrics, logs and spans; a source is present iff its table has rows. The hint is null
    (the watcher sets the live trigger later), inputs are empty and the scrub counts are zero.
    The case id hashes the adapter, dataset, system and span, so the same window gives the same
    id. Raises ValueError when every table is empty (no data span to describe).
    """
    bounds: list[tuple[int, int]] = []
    present: dict[str, bool] = {}
    for flag, attr, low, high in _SPAN_COLUMNS:
        table = getattr(tables, attr)
        present[flag] = table.num_rows > 0
        if table.num_rows:
            bounds.append((min(_int_column(table, low, attr)), max(_int_column(table, high, attr))))
    if not bounds:
        msg = "provisional_manifest: every telemetry table is empty"
        raise ValueError(msg)
    start, end = min(b[0] for b in bounds), max(b[1] for b in bounds)
    services: set[str] = set()
    for attr in _SERVICE_TABLES:
        table = getattr(tables, attr)
        if table.num_rows and "service" in table.column_names:
            services.update(str(v) for v in table.column("service").to_pylist() if v is not None)
    key = f"{adapter}:{dataset}:{system}:{start}:{end}"
    return CaseManifest.model_validate(
        {
            "schema_version": CONTRACTS["case_manifest"].version,
            "case_id": make_case_id(key),
            "dataset": dataset,
            "system": system,
            "t_alert_hint_ns": None,
            "hint_source": "none",
            "data_start_ns": start,
            "data_end_ns": end,
            "sources": present,
            "services": sorted(services),
            "inputs": [],
            "adapter": {"name": adapter, "version": adapter_version},
            "scrub": {"rules_version": LIVE_SCRUB_RULES, "dropped_attributes": 0, "dropped_rows": 0},
        }
    )
