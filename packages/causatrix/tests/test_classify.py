"""Tests of classify(): rules R1–R6, the indicator branches and the component (07 §3.5–§3.8)."""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any

import pytest

from veyltrace_causatrix.classify import Classification, classify
from veyltrace_causatrix.config import config_from
from veyltrace_causatrix.views import Atom, evidence_view, graph_view
from veyltrace_core.config import load_section_file

CFG = config_from(load_section_file("causatrix"), load_section_file("core"))
INC = {"window": "incident"}


_IDS = itertools.count(1)


def _a(kind: str, value: float, **args: Any) -> Atom:
    return Atom(f"E{next(_IDS):010x}", "s", None, kind, args, value)


def _z(kind: str, value: float, family: str, detector: str = "robust_z") -> Atom:
    return _a(kind, value, detector=detector, family=family, source="metrics", **INC)


def _gap(quantile: str, value: float, direction: str = "in") -> Atom:
    return _a("edge_gap", value, direction=direction, quantile=quantile, **INC)


def _change(value: float, event_kind: str) -> Atom:
    return _a("change_proximity", value, change_id=f"C{int(value * 1e9):010x}", event_kind=event_kind, **INC)


def _new_errors(count: float) -> Atom:
    return _a("log_new_template", count, error_level_only=True, min_count=3, **INC)


def _classify(*atoms: Atom, kind: str = "service", cfg: Any = CFG) -> tuple[str, str, str]:
    ev = evidence_view(atoms, ["s"])
    c = classify("s", ev, graph_view(["s"], [("s", kind)], [], include_external=False), cfg)
    return c.mode, c.fault_class, c.indicator


@pytest.mark.parametrize(
    ("family", "fault", "indicator"),
    [("cpu", "cpu", "cpu"), ("mem", "mem", "mem"), ("disk", "disk", "diskio"), ("net", "socket", "socket")],
)
def test_r2_resource(family: str, fault: str, indicator: str) -> None:
    assert _classify(_z("internal_anomaly", 6.0, family)) == ("resource", fault, indicator)


def test_r1_change_takes_config_or_the_next_rule_class() -> None:
    cpu = _z("internal_anomaly", 6.0, "cpu")
    assert _classify(cpu, _change(0.2, "deploy"), _change(0.9, "config")) == ("change", "config", "cpu")
    assert _classify(cpu, _change(0.5, "flag")) == ("change", "config", "cpu")
    assert _classify(cpu, _change(0.9, "deploy"), _change(0.4, "config")) == ("change", "cpu", "cpu")
    silent_only = (_a("silence", 1.0, **INC), _change(0.9, "deploy"))
    assert _classify(*silent_only) == ("change", "unknown", "unknown")
    # Below e^-1, or on a service that is neither anomalous nor silent, R1 does not fire.
    assert _classify(cpu, _change(0.36, "config")) == ("resource", "cpu", "cpu")
    assert _classify(_z("internal_anomaly", 2.0, "cpu"), _change(0.9, "config"))[0] == "unknown"


def test_r3_code_from_logs_or_new_error_templates() -> None:
    logs = _z("internal_anomaly", 5.0, "logs")
    assert _classify(logs) == ("code", "unknown", "logs")
    assert _classify(logs, _new_errors(2.0)) == ("code", "exception", "logs")  # 07 §11 Q9: logs
    assert _classify(logs, _z("external_anomaly", 4.0, "errors")) == ("code", "error", "logs")
    nsigma_errors = _z("external_anomaly", 40.0, "errors", detector="nsigma")
    assert _classify(logs, nsigma_errors)[1] == "unknown"  # R3's error test is robust_z only
    assert _classify(_z("internal_anomaly", 4.0, "self_time")) == ("code", "unknown", "latency")
    # A new ERROR template alone is enough, even with a quiet internal signal.
    assert _classify(_new_errors(1.0), _z("internal_anomaly", 1.0, "cpu")) == ("code", "exception", "unknown")
    not_error_only = _a("log_new_template", 5.0, error_level_only=False, min_count=3, **INC)
    assert _classify(not_error_only)[0] == "unknown"


@pytest.mark.parametrize("kind", ["db", "cache", "queue", "external"])
def test_r4_dependency(kind: str) -> None:
    assert _classify(_a("silence", 1.0, **INC), kind=kind)[:2] == ("dependency", "dependency")
    assert _classify(_z("external_anomaly", 3.0, "latency"), kind=kind) == (
        "dependency",
        "dependency",
        "latency",
    )
    assert _classify(_z("external_anomaly", 3.0, "latency"), kind="service")[0] == "network"


def test_r5_network_delay_or_loss() -> None:
    lat = _z("external_anomaly", 7.0, "latency")
    assert _classify(lat) == ("network", "delay", "latency")
    assert _classify(lat, _z("external_anomaly", 3.0, "errors", detector="nsigma"))[1] == "loss"
    # The edge gap alone triggers R5; a tail-only widening (p50/p99 <= 0.5) means loss.
    assert _classify(_gap("p50", 6.0), _gap("p99", 30.0)) == ("network", "loss", "latency")
    assert _classify(_gap("p50", 6.0), _gap("p99", 10.0)) == ("network", "delay", "latency")
    assert _classify(_gap("p50", 4.9))[0] == "unknown"
    assert _classify(_gap("p50", 6.0, direction="out"))[0] == "unknown"
    # 07 §3.8: p99 <= 0 or an absent atom makes the ratio test false.
    assert _classify(lat, _gap("p50", 1.0), _gap("p99", 0.0))[1] == "delay"
    assert _classify(lat, _gap("p50", 1.0))[1] == "delay"
    assert _classify(_z("internal_anomaly", 3.0, "latency"), lat)[0] == "unknown"  # I >= k_anom: not R5


def test_r6_and_indicator_fallbacks() -> None:
    assert _classify() == ("unknown", "unknown", "unknown")
    assert _classify(_z("external_anomaly", 2.0, "errors")) == ("unknown", "unknown", "error")  # E > 0
    assert _classify(_z("internal_anomaly", 2.0, "cpu")) == ("unknown", "unknown", "unknown")  # I < k, E = 0
    assert _classify(_z("internal_anomaly", 4.0, "traffic")) == ("unknown", "unknown", "workload")
    remapped = replace(CFG, indicator_map=tuple((f, "cpu") for f, _ in CFG.indicator_map))
    assert _classify(_z("external_anomaly", 7.0, "latency"), cfg=remapped)[2] == "cpu"


def test_worked_example_and_component() -> None:
    rows: list[Atom] = [
        Atom(
            "E0000000001",
            "checkout",
            "checkout-1",
            "internal_anomaly",
            {"detector": "robust_z", "family": "cpu"},
            9.0,
        ),
        Atom(
            "E0000000002",
            "checkout",
            None,
            "external_anomaly",
            {"detector": "robust_z", "family": "latency"},
            11.0,
        ),
        Atom(
            "E0000000003",
            "frontend",
            None,
            "internal_anomaly",
            {"detector": "robust_z", "family": "mem"},
            1.2,
        ),
        Atom(
            "E0000000004",
            "frontend",
            "frontend-0",
            "external_anomaly",
            {"detector": "robust_z", "family": "latency"},
            14.0,
        ),
    ]
    ev = evidence_view(rows, ["checkout", "frontend"])
    graph = graph_view(["checkout", "frontend"], [], [], include_external=False)
    assert classify("checkout", ev, graph, CFG) == Classification("resource", "cpu", "cpu", "checkout-1")
    # topI (mem, 1.2) has no component, so the component comes from topE only when topI is absent.
    assert classify("frontend", ev, graph, CFG) == Classification("network", "delay", "latency", None)
