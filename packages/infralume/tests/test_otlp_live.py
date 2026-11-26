"""The `otlp_live` adapter on a hand-written gateway snapshot (01 §3.3; layout agreed on #24).

The snapshot is what `veyltrace_gateway.snapshot.write_snapshot` leaves under the data root:
four canonical Parquet files, `snapshot.json` and an `index/live.json` entry. No captured data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_core import io, textio
from veyltrace_core.adapters import adapter_for
from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import EngineConfig, data_root
from veyltrace_core.errors import CaseRejected, UsageError
from veyltrace_core.ids import case_id
from veyltrace_infralume.adapters.otlp_live import OtlpLiveAdapter, reapply
from veyltrace_infralume.index import write_index
from veyltrace_infralume.names import NameRules
from veyltrace_infralume.scrub import Scrubber, ScrubRules

T = 1_764_000_000_000_000_000
SID = "0123456789abcdef0123456789abcdef"
ADAPTER = OtlpLiveAdapter()
CLEAN: dict[str, list[dict[str, Any]]] = {
    "metrics": [
        {"t_ns": T, "service": "cart", "component": "cart-0", "name": "cpu", "metric_type": "gauge",
         "attrs_json": None, "value": 0.5, "unit": "1", "source_system": "otlp"},
    ],
    "logs": [
        {"t_ns": T + 1, "service": "cart", "component": "cart", "severity": "INFO", "body": "ready",
         "trace_id": None, "span_id": None, "attrs_json": '{"thread":"main"}'},
    ],
    "spans": [
        {"trace_id": "aa", "span_id": "01", "parent_span_id": None, "service": "frontend", "component": None,
         "operation": "GET /", "kind": "server", "start_ns": T, "end_ns": T + 9, "status": "error",
         "status_code": 503, "attrs_json": '{"http.response.status_code":503}'},
    ],
    "events": [],
}  # fmt: skip


def _table(source: str, rows: list[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=io.arrow_schema(f"telemetry.{source}"))


def _snapshot(rows: dict[str, list[dict[str, Any]]] = CLEAN, sid: str = SID, **meta: Any) -> Path:
    """Write a snapshot folder and its index entry, as the gateway does; returns the folder."""
    folder = data_root() / "live" / sid
    for source, source_rows in rows.items():
        io.write_path(f"telemetry.{source}", _table(source, source_rows), folder / f"{source}.parquet")
    fields = {"snapshot_id": sid, "t_trigger_ns": T + 5, "trigger": "manual"} | meta
    textio.write_bytes(folder / "snapshot.json", canonical_json(fields) + b"\n")
    write_index(data_root(), "live", {case_id(sid): f"live/{sid}"})
    return folder


def test_snapshot_becomes_a_live_case(infralume_cfg: EngineConfig) -> None:
    _snapshot()
    assert isinstance(adapter_for("live"), OtlpLiveAdapter)
    ref = ADAPTER.resolve("live", case_id(SID), data_root())
    assert ref == ADAPTER.resolve("live", SID, data_root())  # the snapshot id is the canonical key
    assert (ref.case_id, ref.canonical_key) == (case_id(SID), SID)
    assert ADAPTER.list_cases("live", data_root()) == [case_id(SID)]
    assert ADAPTER.alert_hint(ref) == (T + 5, "live")

    case = ADAPTER.convert(ref, infralume_cfg)
    assert (case.t_alert_hint_ns, case.hint_source, case.system) == (T + 5, "live", "other")
    assert (case.adapter_name, case.scrub) == ("otlp_live", ("scrub-1", 0, 0))
    assert case.sources_present == {"metrics": True, "logs": True, "traces": True, "events": False}
    assert [name for name, _, _ in case.inputs] == ["logs/logs.parquet", "metrics/metrics.parquet",
                                                    "traces/spans.parquet"]  # fmt: skip
    for source, rows in CLEAN.items():  # an already canonical snapshot comes back unchanged
        assert getattr(case.tables, source).equals(_table(source, rows))


def test_rules_are_reapplied_and_idempotent(infralume_cfg: EngineConfig) -> None:
    log = CLEAN["logs"][0]
    rows = [
        log | {"service": "Cart_Service", "component": "Cart_Service", "body": f"open /{SID}/x",
               "attrs_json": '{"chaos.kind":"pod","thread":"main"}'},
        log | {"service": "flagd", "component": "flagd"},  # fault tool: scrub.drop_services
        log | {"service": "istio-proxy", "component": "istio-proxy"},  # sidecar: normalise.drop_containers
    ]  # fmt: skip

    def run(table: pa.Table) -> tuple[pa.Table, Scrubber]:
        scrub = Scrubber(ScrubRules.from_config(infralume_cfg), (SID,))
        return reapply(table, "logs", NameRules.from_config(infralume_cfg, "other"), scrub), scrub

    once, scrub = run(_table("logs", rows))
    (row,) = once.to_pylist()
    assert (row["service"], row["component"]) == ("cart-service", "cart-service")
    assert (row["body"], row["attrs_json"]) == ("open /<case>/x", '{"thread":"main"}')
    assert (scrub.dropped_attributes, scrub.dropped_rows) == (1, 2)
    twice, again = run(once)
    assert twice.equals(once) and (again.dropped_attributes, again.dropped_rows) == (0, 0)


def test_events_are_scrubbed(infralume_cfg: EngineConfig) -> None:
    event = {"t_ns": T, "entity": "Cart", "kind": "deploy", "source_system": "k8s", "detail_json": "{}",
             "actor": None}  # fmt: skip
    chaos = event | {"detail_json": '{"object":"PodChaos"}'}
    scrub = Scrubber(ScrubRules.from_config(infralume_cfg))
    table = _table("events", [event, chaos])
    out = reapply(table, "events", NameRules.from_config(infralume_cfg, "other"), scrub)
    assert out.to_pylist() == [event | {"entity": "cart"}]
    assert scrub.dropped_rows == 1


@pytest.mark.parametrize(
    ("meta", "reason"),
    [
        ({"snapshot_id": "f" * 32}, "invalid_capture"),  # another snapshot's file
        ({"t_trigger_ns": "soon"}, "invalid_capture"),
        ({"t_trigger_ns": True}, "invalid_capture"),
    ],
)
def test_bad_snapshot_is_rejected(infralume_cfg: EngineConfig, meta: dict[str, Any], reason: str) -> None:
    _snapshot(**meta)
    ref = ADAPTER.resolve("live", SID, data_root())
    with pytest.raises(CaseRejected) as caught:
        ADAPTER.convert(ref, infralume_cfg)
    assert caught.value.reason == reason


def test_missing_and_empty_snapshots(infralume_cfg: EngineConfig) -> None:
    folder = _snapshot({s: [] for s in CLEAN})
    ref = ADAPTER.resolve("live", SID, data_root())
    with pytest.raises(CaseRejected) as caught:
        ADAPTER.convert(ref, infralume_cfg)
    assert caught.value.reason == "no_telemetry"
    (folder / "snapshot.json").unlink()
    with pytest.raises(CaseRejected) as caught:
        ADAPTER.convert(ref, infralume_cfg)
    assert caught.value.reason == "invalid_capture"
    (folder / "spans.parquet").write_bytes(b"not parquet")
    textio.write_bytes(folder / "snapshot.json", canonical_json({"snapshot_id": SID, "t_trigger_ns": T}))
    with pytest.raises(CaseRejected) as caught:
        ADAPTER.convert(ref, infralume_cfg)
    assert caught.value.reason == "invalid_capture" and "spans.parquet" in caught.value.detail


def test_unknown_cases_are_usage_errors() -> None:
    _snapshot()
    for dataset, case in (("live", "0" * 12), ("live", "not-an-id"), ("re2-ob", case_id(SID))):
        with pytest.raises(UsageError):
            ADAPTER.resolve(dataset, case, data_root())
    write_index(data_root(), "live", {"0" * 12: f"live/{SID}"})  # an index entry for another case
    with pytest.raises(UsageError):
        ADAPTER.resolve("live", "0" * 12, data_root())
