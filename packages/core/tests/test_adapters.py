"""adapters: TelemetryTables, CanonicalCase and AlertDetection validation, adapter_for matching."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import plugins
from veyltrace_core.adapters import (
    AlertDetection,
    CanonicalCase,
    CaseRef,
    TelemetryTables,
    adapter_for,
    find_adapter,
)
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.plugins import Plugin


def _schema(name: str) -> pa.Schema:
    schema = CONTRACTS[name].arrow_schema
    assert schema is not None
    return schema


def test_from_tables_fills_absent_sources_with_typed_empty_tables() -> None:
    metrics = _schema("telemetry.metrics").empty_table()
    tables = TelemetryTables.from_tables(metrics=metrics)
    assert tables.metrics is metrics
    for attr, contract in (
        ("logs", "telemetry.logs"),
        ("spans", "telemetry.spans"),
        ("events", "telemetry.events"),
    ):
        table = getattr(tables, attr)
        assert table.num_rows == 0
        assert table.schema.equals(_schema(contract))
    assert [a for a, _ in tables.items()] == ["metrics", "logs", "spans", "events"]


def test_from_tables_checks_columns() -> None:
    schema = _schema("telemetry.metrics")
    projected = schema.empty_table().select([schema.names[0]])
    TelemetryTables.from_tables(metrics=projected)  # a column subset is fine
    with pytest.raises(ContractValidationError, match="not a projection"):
        TelemetryTables.from_tables(metrics=pa.table({"nope": pa.array([1])}))
    reordered = schema.empty_table().select([schema.names[1], schema.names[0]])
    with pytest.raises(ContractValidationError, match="not a projection"):
        TelemetryTables.from_tables(metrics=reordered)  # one class, the stricter io check
    with pytest.raises(ContractValidationError):
        TelemetryTables(metrics=reordered, logs=projected, spans=projected, events=projected)
    wrong = pa.table({schema.names[0]: pa.array([1.5])})
    if not schema.field(0).type.equals(pa.float64()):
        with pytest.raises(ContractValidationError):
            TelemetryTables.from_tables(metrics=wrong)
    with pytest.raises(ValueError, match="unknown telemetry"):
        TelemetryTables.from_tables(traces=projected)


def test_one_telemetry_tables_class() -> None:
    from veyltrace_core import io

    assert TelemetryTables is io.TelemetryTables


def test_from_run_dir_without_files_is_empty(tmp_path: Path) -> None:
    tables = TelemetryTables.from_run_dir(tmp_path)
    assert all(t.num_rows == 0 for _, t in tables.items())


def _case(**kw: Any) -> CanonicalCase:
    base: dict[str, Any] = {
        "system": "ob",
        "tables": TelemetryTables.from_tables(),
        "sources_present": {"metrics": True, "logs": False, "traces": True, "events": False},
        "inputs": (("metrics/a.csv", "a" * 64, 10), ("traces/b.json", "b" * 64, 0)),
        "adapter_name": "x",
        "adapter_version": "1",
        "scrub": ("1", 0, 0),
        "t_alert_hint_ns": 5,
        "hint_source": "oracle",
    }
    return CanonicalCase(**{**base, **kw})


def test_canonical_case_validation() -> None:
    _case()
    for bad in (
        {"system": "k8s"},
        {"sources_present": {"metrics": True}},
        {"inputs": (("traces/b", "b" * 64, 0), ("metrics/a", "a" * 64, 1))},
        {"inputs": (("metrics/a", "zz", 1),)},
        {"hint_source": "none"},
        {"t_alert_hint_ns": None},
    ):
        with pytest.raises(ValueError):
            _case(**bad)
    _case(t_alert_hint_ns=None, hint_source="none")


def test_alert_detection_normalises() -> None:
    d = AlertDetection(t_alert_ns=7, entry_services=("web", "api", "web"), signal="latency_p99", threshold=2)
    assert d.entry_services == ("api", "web")
    assert d.threshold == 2.0 and isinstance(d.threshold, float)
    with pytest.raises(TypeError):
        AlertDetection(t_alert_ns=True, entry_services=(), signal="s", threshold=1.0)
    with pytest.raises(ValueError):
        AlertDetection(t_alert_ns=1, entry_services=(), signal="s", threshold=float("inf"))


@dataclass
class FakeAdapter:
    name: str
    datasets: tuple[str, ...]
    version: str = "1"
    cacheable: bool = True

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        return CaseRef(dataset, case, case, None)

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        return []

    def convert(self, ref: CaseRef, cfg: Any) -> CanonicalCase:
        return _case()

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        return None, "none"


def _register(monkeypatch: pytest.MonkeyPatch, *adapters: object) -> None:
    g = plugins.ADAPTERS
    found = tuple(Plugin(g, f"a{i}", f"x:a{i}", "d", (lambda a=a: a)) for i, a in enumerate(adapters))
    monkeypatch.setattr(plugins, "discover", lambda group: found if group == g else ())


def test_adapter_for_exactly_one_case_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = FakeAdapter("rcaeval", ("re1-*", "re2-*"))
    synth = FakeAdapter("synth", ("synth",))
    _register(monkeypatch, rc, synth)
    assert adapter_for("re2-ob") is rc
    assert adapter_for("synth") is synth
    with pytest.raises(ConfigError, match="matched: none"):
        adapter_for("RE2-OB")  # fnmatchcase: no case folding on any OS
    _register(monkeypatch, rc, FakeAdapter("dup", ("re2-*",)))
    with pytest.raises(ConfigError, match="a0, a1"):
        adapter_for("re2-ob")
    _register(monkeypatch, object())
    with pytest.raises(ConfigError, match="not an Adapter"):
        adapter_for("re2-ob")


def test_find_adapter_none_or_one_never_several(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = FakeAdapter("rcaeval", ("re2-*",))
    _register(monkeypatch, rc)
    assert find_adapter("re2-ob") is rc
    assert find_adapter("synth") is None  # the bootstrap Infralume stub then writes a placeholder
    _register(monkeypatch, rc, FakeAdapter("dup", ("re2-*",)))
    with pytest.raises(ConfigError, match="a0, a1"):
        find_adapter("re2-ob")


def test_telemetry_tables_is_one_class() -> None:
    """adapters re-exports io's class: CanonicalCase, DetectAlert and engines share one type."""
    from veyltrace_core import io

    assert TelemetryTables is io.TelemetryTables
