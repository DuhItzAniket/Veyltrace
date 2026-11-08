"""Shared fixtures of FaultLoom's tests: fixture run dirs for each pass; hand-made input views."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core.testing import fixture_run_dir
from veyltrace_faultloom.inputs import AnomalyRow, EvidenceInputs, ServiceOnset

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
    def anomaly(
        series_id: str,
        klass: str,
        detector: str = "robust_z",
        score: float = 0.0,
        *,
        above: bool | None = None,
    ) -> AnomalyRow:
        """An anomalies row whose family is the series' signal; above_threshold defaults to score >= 3."""
        service, component, signal, source = series_id.split("|")
        hot = score >= 3.0 if above is None else above
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
