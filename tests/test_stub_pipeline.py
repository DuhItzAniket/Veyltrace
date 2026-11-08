"""End-to-end proof that the R-02 bootstrap pipeline runs: an in-memory case, the real stub engines.

A minimal fake dataset adapter (registered in the test by patching `plugins.discover`, next to the
real installed entry points) hands Infralume's stub a tiny `CanonicalCase` through the adapter
protocol (core_api_spec §8). `pipeline.execute` then runs all 14 sub-steps (`steps.STEPS`) with the
real `veyltrace.engines` stubs, and every run-directory artefact of 02 §4.1 must exist and validate
against its contract. No synth generator is involved (that is R-03).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io, plugins
from veyltrace_core.adapters import ADAPTERS_GROUP, CanonicalCase, CaseRef, TelemetryTables, adapter_for
from veyltrace_core.config import EngineConfig
from veyltrace_core.context import RunPlan
from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.ids import is_case_id
from veyltrace_core.pipeline import RunSummary, execute
from veyltrace_core.steps import STEPS

DATASET = "stubtest"
CASE_NAME = "case-01"
CANONICAL_KEY = f"{DATASET}/{CASE_NAME}"
CASE_ID = make_case_id(CANONICAL_KEY)

_NS = 1_000_000_000
T0_NS = 1_767_225_600 * _NS  # 2026-01-01T00:00:00Z, the synth layout (a priori)
SPAN_S = 1920  # 32 min of data, so the default baseline and incident windows are non-empty
HINT_NS = T0_NS + 1320 * _NS  # oracle hint 22 min in

#: The run directory of 02 §4.1, as published paths. AI-on-only entries are listed separately.
RUN_DIR_LAYOUT: tuple[str, ...] = (
    "case_manifest.json",
    "telemetry/metrics.parquet",
    "telemetry/logs.parquet",
    "telemetry/spans.parquet",
    "telemetry/events.parquet",
    "alert.json",
    "signal_cube/series.parquet",
    "signal_cube/edges.parquet",
    "signal_cube/templates.parquet",
    "signal_cube/critical_path.parquet",
    "anomalies.parquet",
    "onsets.json",
    "alignment.json",
    "changes.parquet",
    "graph/nodes.parquet",
    "graph/edges.parquet",
    "graph/paths.parquet",
    "evidence.parquet",
    "slate.json",
    "verdict.json",
    "card.json",
    "card.md",
    "config.lock.json",
    "run_manifest.json",
    "receipt.json",
)
AI_ONLY_LAYOUT: tuple[str, ...] = ("proposals.json", "agent_trace.jsonl")

_PATH_TO_CONTRACT = {c.path: name for name, c in CONTRACTS.items()}


def _table(contract: str, rows: list[dict[str, Any]]) -> pa.Table:
    """A table holding only the given columns (a subset, as adapters may produce), contract-typed."""
    schema = io.arrow_schema(contract)
    names = list(rows[0])
    return pa.Table.from_pylist(rows, schema=pa.schema([schema.field(n) for n in names]))


def _tables() -> TelemetryTables:
    t = T0_NS
    metrics = _table(
        "telemetry.metrics",
        [  # nullable metric_type, attrs_json and unit are omitted: Infralume pads them with nulls
            {"t_ns": t, "service": "frontend", "component": "frontend", "name": "latency_p99",
             "value": 0.12, "source_system": "prom"},
            {"t_ns": t + SPAN_S * _NS, "service": "cart", "component": "cart", "name": "latency_p99",
             "value": 0.5, "source_system": "prom"},
        ],
    )  # fmt: skip
    spans = _table(
        "telemetry.spans",
        [
            {"trace_id": "t1", "span_id": "s1", "parent_span_id": None, "service": "frontend",
             "component": None, "operation": "GET /", "kind": "server", "start_ns": t + 60 * _NS,
             "end_ns": t + 61 * _NS, "status": "ok", "status_code": 200, "attrs_json": None},
            {"trace_id": "t1", "span_id": "s2", "parent_span_id": "s1", "service": "cart",
             "component": None, "operation": "GetCart", "kind": "client", "start_ns": t + 60 * _NS,
             "end_ns": t + 61 * _NS, "status": "error", "status_code": None, "attrs_json": None},
        ],
    )  # fmt: skip
    logs = _table(
        "telemetry.logs",
        [{"t_ns": t + 1400 * _NS, "service": "cart", "component": "cart", "body": "timeout"}],
    )
    events = _table(
        "telemetry.events",
        [{"t_ns": t + 1300 * _NS, "entity": "cart-db", "kind": "restart", "source_system": "k8s",
          "detail_json": "{}"}],
    )  # fmt: skip
    return TelemetryTables.from_tables(metrics=metrics, logs=logs, spans=spans, events=events)


@dataclass(frozen=True)
class FakeAdapter:
    """The smallest adapter that satisfies the protocol: one generated case, no files on disk."""

    name: str = "stubtest"
    version: str = "1"
    datasets: tuple[str, ...] = (DATASET,)
    cacheable: bool = False

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        if case not in (CASE_NAME, CASE_ID):
            msg = f"unknown {dataset} case {case!r}"
            raise UsageError(msg)
        return CaseRef(dataset=dataset, case_id=CASE_ID, canonical_key=CANONICAL_KEY, location=None)

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        return [CASE_ID]

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        hint, source = self.alert_hint(ref)
        return CanonicalCase(
            system="other",
            tables=_tables(),
            sources_present={"metrics": True, "logs": True, "traces": True, "events": True},
            inputs=(),
            adapter_name=self.name,
            adapter_version=self.version,
            scrub=("scrub-0", 0, 0),
            t_alert_hint_ns=hint,
            hint_source=source,  # pyright: ignore[reportArgumentType] - "oracle" is a HintSource
        )

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        return HINT_NS, "oracle"


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAdapter]:
    """Register FakeAdapter in `veyltrace.adapters`, keeping every real installed entry point."""
    adapter = FakeAdapter()
    real_discover = plugins.discover

    def discover(group: str) -> tuple[plugins.Plugin, ...]:
        found = real_discover(group)
        if group != ADAPTERS_GROUP:
            return found
        fake = plugins.Plugin(
            group=group, name="stubtest", value="tests.test_stub_pipeline:FakeAdapter",
            distribution=None, loader=lambda: adapter,
        )  # fmt: skip
        return tuple(sorted((*found, fake), key=lambda p: (p.name, p.value, p.distribution or "")))

    monkeypatch.setattr(plugins, "discover", discover)
    yield adapter


def _run(tmp_path: Path, **plan: Any) -> RunSummary:
    return execute(
        RunPlan(dataset=DATASET, case=CASE_NAME, runs_root=tmp_path / "runs", code_commit="fixture", **plan)
    )


def test_fake_adapter_resolves(fake_adapter: FakeAdapter) -> None:
    assert adapter_for(DATASET) is fake_adapter
    assert is_case_id(CASE_ID)


def test_layout_names_real_contracts() -> None:
    # Every 02 §4.1 path except card.md is a run-dir contract path in the registry, and vice versa.
    listed = {p for p in (*RUN_DIR_LAYOUT, *AI_ONLY_LAYOUT) if p != "card.md"}
    registry = {c.path for name, c in CONTRACTS.items() if io.is_run_dir_contract(name)}
    assert listed == registry


@pytest.mark.parametrize("ai_mode", ["off", "record"])
def test_stub_pipeline_end_to_end(tmp_path: Path, fake_adapter: FakeAdapter, ai_mode: str) -> None:
    overrides = {"llm.provider": "fake"} if ai_mode == "record" else {}
    summary = _run(tmp_path, ai_mode=ai_mode, overrides=overrides)

    assert summary.outcome == "ok", (summary.failed_step, summary.reason, summary.error)
    assert summary.exit_code == 0
    assert summary.case_id == CASE_ID
    assert [r.name for r in summary.steps] == [s.name for s in STEPS]  # all 14 sub-steps ran
    assert len(STEPS) == 14
    relentra = {r.name: r.status for r in summary.steps}["relentra"]
    assert relentra == ("skipped" if ai_mode == "off" else "ok")

    run_dir = summary.run_dir
    expected = RUN_DIR_LAYOUT + (AI_ONLY_LAYOUT if ai_mode != "off" else ())
    missing = [p for p in expected if not (run_dir / p).is_file()]
    assert missing == []
    if ai_mode == "off":
        assert not any((run_dir / p).exists() for p in AI_ONLY_LAYOUT)

    for rel in expected:
        if rel == "card.md":
            assert (run_dir / rel).read_bytes().startswith(b"#")
            continue
        io.read_path(_PATH_TO_CONTRACT[rel], run_dir / rel, validate=True)  # raises if invalid

    # The case came through the adapter protocol, not the placeholder stub case.
    manifest = io.read_unredacted("case_manifest", run_dir, validate=True)
    assert isinstance(manifest, models.CaseManifest)
    assert manifest.adapter.name == "stubtest"
    assert manifest.services == ["cart", "frontend"]  # event-only entity cart-db is excluded
    assert (manifest.data_start_ns, manifest.data_end_ns) == (T0_NS, T0_NS + SPAN_S * _NS)
    assert manifest.t_alert_hint_ns == HINT_NS
    metrics = io.read_table("telemetry.metrics", run_dir, validate=True)
    assert metrics.num_rows == 2
    assert metrics.column("unit").null_count == 2  # padded nullable column
    alert = io.read_model("alert", run_dir, models.Alert, validate=True)
    assert alert.t_alert_ns == HINT_NS

    # run_manifest lists exactly the files on disk (minus itself and the receipt).
    run_manifest = io.read_model("run_manifest", run_dir, models.RunManifest, validate=True)
    listed = {o.name for o in run_manifest.outputs}
    on_disk = {
        p.relative_to(run_dir).as_posix()
        for p in sorted(run_dir.rglob("*"))
        if p.is_file() and not p.relative_to(run_dir).as_posix().startswith(".duck-tmp/")
    }
    assert listed == on_disk - {"run_manifest.json", "receipt.json"}


def test_stub_pipeline_is_deterministic(tmp_path: Path, fake_adapter: FakeAdapter) -> None:
    first = _run(tmp_path / "a")
    second = _run(tmp_path / "b")
    assert first.run_id == second.run_id
    assert first.outputs == second.outputs
    for rel in RUN_DIR_LAYOUT:
        assert (first.run_dir / rel).read_bytes() == (second.run_dir / rel).read_bytes(), rel


def test_detected_protocol_needs_a_detector(tmp_path: Path, fake_adapter: FakeAdapter) -> None:
    # No alert detector is installed before O-04, so preflight refuses the run before any step.
    with pytest.raises(ConfigError, match="alert_detectors"):
        _run(tmp_path, overrides={"core.alert.protocol": "detected"})
    assert not (tmp_path / "runs").exists()
