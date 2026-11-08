"""Shared fixtures of FaultLoom's tests: fixture run dirs for each pass; hand-made input views."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.context import RunContext
from veyltrace_core.testing import fixture_run_dir, make_context
from veyltrace_faultloom.api import run
from veyltrace_faultloom.inputs import (
    AnomalyRow,
    CallEdge,
    ChangeRow,
    CriticalPathRow,
    EdgeStat,
    EvidenceInputs,
    GraphNode,
    PathRow,
    ServiceOnset,
    TemplateRow,
    load_inputs,
)
from veyltrace_faultloom.predicates import ClaimView

#: A t_onset and windows on a round grid (ns): baseline [0, 600 s), incident [600 s, 1200 s).
T0 = 900 * 10**9
S = 10**9
#: The default view: a, b, c in U, no rows, tol 15 s, k_anom 3 (core.thresholds.anomaly_z).
_BASE = EvidenceInputs(
    case_id="0" * 12,
    sources=models.Sources(metrics=True, logs=True, traces=True, events=True),
    services=("a", "b", "c"),
    nodes=(),
    universe=("a", "b", "c"),
    t_onset_ns=T0,
    tol_ns=15 * S,
    w_base=(0, 600 * S),
    w_inc=(600 * S, 1200 * S),
    w_score=(T0, 1200 * S),
    anomalies=(),
    rows={},
    absent=(),
    notes=(),
    k_anom=3.0,
    onsets=(),
    entry_services=(),
    edges=(),
    paths=(),
    components={},
    changes=(),
    templates=(),
    critical_path=(),
    edge_stats=(),
)


class HandMade:
    """Builders of hand-made input rows and views (times in seconds after T0, already aligned)."""

    @staticmethod
    def view(**fields: Any) -> EvidenceInputs:
        """The default view with some fields replaced."""
        return dataclasses.replace(_BASE, **fields)

    @staticmethod
    def onset(
        service: str, *, ext: int | None = None, internal: int | None = None, silent: bool = False
    ) -> ServiceOnset:
        ext_ns = None if ext is None else T0 + ext * S
        int_ns = None if internal is None else T0 + internal * S
        return ServiceOnset(service, ext_ns, int_ns, silent, f"onsets#{service}")

    @staticmethod
    def edge(src: str, dst: str, anomalous: bool | None = None) -> CallEdge:
        return CallEdge(src, dst, anomalous, f"graph.edges#{src}-{dst}")

    @staticmethod
    def node(name: str, kind: str = "service", *, is_entry: bool = False) -> GraphNode:
        return GraphNode(name, kind, is_entry)

    @staticmethod
    def path(candidate: str, rank: int, fraction: float) -> PathRow:
        return PathRow(candidate, rank, fraction, f"graph.paths#{candidate}-{rank}")

    @staticmethod
    def change(
        cid: str, entity: str, scope: str = "service", proximity: float = 0.5, peer: float | None = None
    ) -> ChangeRow:
        return ChangeRow(cid, entity, "deploy", scope, -60_000.0, proximity, peer)

    @staticmethod
    def template(service: str, tid: str, base: int, inc: int, *, error: bool = False) -> TemplateRow:
        return TemplateRow(service, tid, base, inc, error)

    @staticmethod
    def cp(
        window: str, service: str, total: int, mean: float, slow: int, sum_slow: float, **kw: Any
    ) -> CriticalPathRow:
        """A critical_path row; kw: traces, p50, p99 (self-time ms)."""
        p50, p99, traces = kw.get("p50", 0.0), kw.get("p99", 0.0), kw.get("traces", slow)
        return CriticalPathRow(
            window, service, traces, p50, p99, mean, total, slow, sum_slow, f"cp#{window}-{service}"
        )

    @staticmethod
    def edge_stat(
        caller: str, callee: str, window: str, calls: int, p50: float | None, p99: float | None
    ) -> EdgeStat:
        return EdgeStat(caller, callee, window, calls, 0.0, p50, p99, f"edges#{caller}-{callee}-{window}")

    @staticmethod
    def anomaly(
        series_id: str, klass: str, detector: str = "robust_z", score: float = 0.0, **kw: bool
    ) -> AnomalyRow:
        """An anomalies row whose family is the series' signal; above_threshold defaults to score >= 3."""
        service, component, signal, source = series_id.split("|")
        hot = kw.get("above", score >= 3.0)
        return AnomalyRow(series_id, service, component, signal, klass, source, detector, score, hot)


@pytest.fixture(scope="session")
def hm() -> HandMade:
    """Hand-made rows and views for per-kind unit tests (stateless, so one per session)."""
    return HandMade()


@pytest.fixture
def main_dir(tmp_path: Path) -> Path:
    """synth-01 run dir holding everything before FaultLoom's engine pass (through causalith)."""
    return fixture_run_dir("synth-01", tmp_path, through="causalith")


@pytest.fixture
def claim_dir(tmp_path: Path) -> Path:
    """synth-01 run dir holding everything before the claim pass (main evidence, slate; AI off)."""
    return fixture_run_dir("synth-01", tmp_path, through="relentra")


@pytest.fixture
def cpu_hog(tmp_path: Path) -> tuple[RunContext, ClaimView]:
    """The hand-made cpu-hog case after the engine pass: its context and the predicates' view."""
    inputs = json.loads(
        (Path(__file__).parents[1] / "fixtures/handmade/cpu-hog/inputs.json").read_text("utf-8")
    )
    for name in sorted(n for n in inputs if not n.startswith("_")):
        io.write(name, inputs[name], tmp_path)
    ctx = make_context("faultloom", tmp_path, dataset="handmade")
    assert run(ctx).status == "ok"
    return ctx, ClaimView(load_inputs(ctx), tuple(io.read_table("evidence", tmp_path).to_pylist()))
