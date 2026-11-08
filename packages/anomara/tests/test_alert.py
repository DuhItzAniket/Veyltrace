"""Tests of detect_alert on hand-built spans and on the synth telemetry fixtures (03-anomara §3.8, §7)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pytest

from veyltrace_anomara.alert import detect_alert
from veyltrace_anomara.slis import span_call_pairs
from veyltrace_contracts.models import CaseManifest
from veyltrace_core import io, textio
from veyltrace_core.adapters import TelemetryTables
from veyltrace_core.config import EngineConfig, resolve_config
from veyltrace_core.testing import SYNTH_CASES, fixture_dir

NS = 1_000_000_000
T0 = 1_767_225_600 * NS
BUCKET = 10 * NS
N_BUCKETS = 120  # 20 min of 10 s buckets
RECORD = Path(__file__).resolve().parents[1] / "fixtures" / "handmade" / "detect-alert-synth.json"
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"


def _config(**overrides: Any) -> EngineConfig:
    return resolve_config(overrides, dataset="synth", ai_mode="off").engine("anomara")


def _manifest(services: list[str], system: str = "other") -> CaseManifest:
    return CaseManifest.model_validate(
        {
            "schema_version": "0.1.0",
            "case_id": "b0b0b0b0b0b0",
            "dataset": "handmade",
            "system": system,
            "t_alert_hint_ns": None,
            "hint_source": "none",
            "data_start_ns": T0,
            "data_end_ns": T0 + N_BUCKETS * BUCKET,
            "sources": {"metrics": False, "logs": False, "traces": True, "events": False},
            "services": services,
            "inputs": [],
            "adapter": {"name": "handmade", "version": "1"},
            "scrub": {"rules_version": "none", "dropped_attributes": 0, "dropped_rows": 0},
        }
    )


def _spans(
    latency_ms: dict[int, float] | None = None, errors: dict[int, int] | None = None
) -> TelemetryTables:
    """Six frontend entry requests per bucket, each calling checkout; overrides per bucket index."""
    rows: list[dict[str, Any]] = []
    for b in range(N_BUCKETS):
        for i in range(6):
            start = T0 + b * BUCKET + i * NS
            ms = (latency_ms or {}).get(b, 20.0 + (i % 3))
            failed = i < (errors or {}).get(b, 0)
            trace = f"t{b:04d}-{i}"
            for span, parent, service, kind, length in (
                (f"{trace}-a", None, "frontend", "server", ms),
                (f"{trace}-b", f"{trace}-a", "frontend", "client", 5.0),
                (f"{trace}-c", f"{trace}-b", "checkout", "server", 4.0),
            ):
                rows.append(
                    {
                        "trace_id": trace,
                        "span_id": span,
                        "parent_span_id": parent,
                        "service": service,
                        "component": None,
                        "operation": "op",
                        "kind": kind,
                        "start_ns": start,
                        "end_ns": start + int(length * 1e6),
                        "status": "error" if failed and kind == "server" else "ok",
                        "status_code": None,
                        "attrs_json": None,
                    }
                )
    table = io.conform_table(
        "telemetry.spans", pa.Table.from_pylist(rows, schema=io.arrow_schema("telemetry.spans"))
    )
    return TelemetryTables.from_tables(spans=table)


def test_call_pairs_come_from_parent_child_spans_in_different_services() -> None:
    assert span_call_pairs(_spans().spans) == [("frontend", "checkout")]


def test_a_sustained_latency_step_breaches_at_its_first_bucket() -> None:
    found = detect_alert(
        _spans({b: 80.0 for b in range(70, N_BUCKETS)}), _manifest(["checkout", "frontend"]), _config()
    )
    assert found is not None
    assert (found.t_alert_ns, found.signal, found.entry_services, found.threshold) == (
        T0 + 70 * BUCKET,
        "latency_p99",
        ("frontend",),
        3.0,
    )


def test_a_two_bucket_blip_does_not_breach() -> None:
    assert detect_alert(_spans({70: 80.0, 71: 80.0}), _manifest(["checkout", "frontend"]), _config()) is None


def test_an_error_burst_breaches_on_error_rate() -> None:
    found = detect_alert(
        _spans(errors={b: 4 for b in range(80, 90)}), _manifest(["checkout", "frontend"]), _config()
    )
    assert found is not None and (found.t_alert_ns, found.signal) == (T0 + 80 * BUCKET, "error_rate")


def test_flat_telemetry_or_no_entry_returns_none() -> None:
    assert detect_alert(_spans(), _manifest(["checkout", "frontend"]), _config()) is None
    empty = TelemetryTables.from_tables()
    assert detect_alert(empty, _manifest(["checkout", "frontend"]), _config()) is None


def test_the_system_hint_names_the_entry_without_traces_of_its_own() -> None:
    # ob's hint is frontend: with the hint, a breach on frontend is found even if checkout called it.
    found = detect_alert(
        _spans({b: 80.0 for b in range(70, N_BUCKETS)}), _manifest(["checkout", "frontend"], "ob"), _config()
    )
    assert found is not None and found.entry_services == ("frontend",)


def _synth(case: str) -> dict[str, Any]:
    d = fixture_dir("infralume", case)
    manifest = cast("CaseManifest", io.read("case_manifest", d))
    found = detect_alert(TelemetryTables.from_run_dir(d), manifest, _config())
    if found is None:
        return {"breach": None}
    return {
        "t_alert_ns": found.t_alert_ns,
        "signal": found.signal,
        "entry_services": list(found.entry_services),
    }


def test_synth_breaches_are_recorded() -> None:
    # 03-anomara §7: synth-01..04 breach (time recorded here; its distance to the injection is a
    # bench metric), synth-05 (no fault) does not.
    actual = {case: _synth(case) for case in SYNTH_CASES}
    if os.environ.get(UPDATE_ENV) == "1":
        assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
        textio.write_bytes(RECORD, (json.dumps(actual, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    assert json.loads(RECORD.read_text(encoding="utf-8")) == actual
    assert all(actual[c].get("breach", 0) is not None for c in SYNTH_CASES[:4])
    assert actual["synth-05"] == {"breach": None}


@pytest.mark.parametrize("case", SYNTH_CASES)
def test_detect_alert_never_reads_the_hint(case: str) -> None:
    d = fixture_dir("infralume", case)
    manifest = cast("CaseManifest", io.read("case_manifest", d))
    # A hint at the data start would move any detector that read it; detect_alert must not.
    hinted = manifest.model_copy(update={"t_alert_hint_ns": manifest.data_start_ns, "hint_source": "oracle"})
    tel = TelemetryTables.from_run_dir(d)
    assert detect_alert(tel, hinted, _config()) == detect_alert(tel, manifest, _config())
