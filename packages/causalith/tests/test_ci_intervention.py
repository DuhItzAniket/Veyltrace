"""Tests of intervention_test and partial_corr_test (05-causalith §3.7, §7)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_causalith.ci import CIConfig, intervention_test, partial_corr_test
from veyltrace_contracts.models import Alert
from veyltrace_core import io
from veyltrace_core.config import load_section_file

CFG = CIConfig.from_sections(load_section_file("causalith"), load_section_file("anomara"))
NS = 1_000_000_000
T0 = 1_767_225_600 * NS
STEP = 10 * NS
N_BASE, N_INC = 100, 50
ALERT = Alert.model_validate(
    {
        "schema_version": "0.1.0",
        "protocol": "oracle",
        "t_alert_ns": T0 + N_BASE * STEP,
        "shift_ns": 0,
        "detector": None,
        "windows": {
            "baseline": [T0, T0 + N_BASE * STEP],
            "incident": [T0 + N_BASE * STEP, T0 + (N_BASE + N_INC) * STEP],
        },
        "clamped": False,
    }
)
#: A fixed noise pattern (no RNG in tests either, so the expected answers cannot move).
NOISE = np.asarray([math.sin(1.7 * k) + 0.5 * math.cos(3.1 * k) for k in range(N_BASE + N_INC)])
#: The candidate's own noise, nearly uncorrelated with NOISE (|r| < 0.05 on the baseline).
OWN = np.asarray([math.cos(2.9 * k + 0.4) for k in range(N_BASE + N_INC)])


def _series(columns: dict[str, np.ndarray]) -> pa.Table:
    rows: list[dict[str, Any]] = []
    for sid, values in sorted(columns.items()):
        service, component, signal, source = sid.split("|")
        family = "latency" if signal.startswith("latency") else "traffic"
        for k, v in enumerate(values):
            rows.append(
                {
                    "series_id": sid,
                    "service": service,
                    "component": component,
                    "signal": signal,
                    "family": family,
                    "klass": "external",
                    "source": source,
                    "unit": "ms",
                    "t_ns": T0 + k * STEP,
                    "value": float(v),
                }
            )
    return io.conform_table(
        "signal_cube.series", pa.Table.from_pylist(rows, schema=io.arrow_schema("signal_cube.series"))
    )


def _edges(rows: list[tuple[str, str, bool | None, float]]) -> pa.Table:
    data = [
        {"src": s, "dst": d, "provenance": ["traces"], "calls_incident": 10, "weight": w, "anomalous": a}
        for s, d, a, w in rows
    ]
    return io.conform_table("graph.edges", pa.Table.from_pylist(data, schema=io.arrow_schema("graph.edges")))


SHIFT = np.where(np.arange(N_BASE + N_INC) >= N_BASE, 25.0, 0.0)
CHECKOUT = "checkout|checkout|latency_p99|traces"
PAYMENT = "payment|payment|latency_p99|traces"


def test_an_anomaly_inherited_from_the_callee_is_explained() -> None:
    payment = 50.0 + 3.0 * NOISE + SHIFT
    checkout = 20.0 + 1.0 * payment + 0.3 * OWN
    result = intervention_test(
        _series({CHECKOUT: checkout, PAYMENT: payment}),
        _edges([("checkout", "payment", True, 1.0)]),
        ALERT,
        "checkout",
        CFG,
    )
    assert (result.target_series_id, result.parents, result.reason) == (CHECKOUT, (PAYMENT,), None)
    assert result.independent_of_parents is False and result.explained_fraction > 0.8
    assert (result.n_baseline, result.n_incident) == (N_BASE, N_INC)


def test_an_own_anomaly_is_not_explained_by_parents() -> None:
    payment = 50.0 + 3.0 * NOISE
    checkout = 20.0 + 1.0 * payment + 0.3 * OWN + SHIFT
    result = intervention_test(
        _series({CHECKOUT: checkout, PAYMENT: payment}),
        _edges([("checkout", "payment", None, 1.0)]),
        ALERT,
        "checkout",
        CFG,
    )
    assert result.independent_of_parents is True and result.stat_resid >= CFG.threshold
    assert 0.0 < result.p_value <= 1.0


@pytest.mark.parametrize(
    ("columns", "edges", "reason"),
    [
        ({PAYMENT: NOISE}, [("checkout", "payment", True, 1.0)], "no_target"),
        ({CHECKOUT: NOISE}, [], "no_parents"),
        ({CHECKOUT: NOISE, PAYMENT: NOISE}, [("checkout", "payment", True, 1.0)], None),
    ],
)
def test_untestable_cases_name_their_reason(
    columns: dict[str, np.ndarray], edges: list[tuple[str, str, bool | None, float]], reason: str | None
) -> None:
    result = intervention_test(_series(columns), _edges(edges), ALERT, "checkout", CFG)
    assert result.reason == reason
    assert (result.independent_of_parents is None) == (reason is not None)


def test_a_short_baseline_is_untestable() -> None:
    short = Alert.model_validate(
        ALERT.model_dump()
        | {"windows": {"baseline": [T0, T0 + 15 * STEP], "incident": [T0 + 15 * STEP, T0 + 40 * STEP]}}
    )
    result = intervention_test(
        _series({CHECKOUT: NOISE, PAYMENT: NOISE}),
        _edges([("checkout", "payment", True, 1.0)]),
        short,
        "checkout",
        CFG,
    )
    assert result.reason == "short_baseline" and result.independent_of_parents is None


def test_no_incident_bucket_is_untestable_not_explained() -> None:
    # A crashed candidate: its latency stops at the incident start, so no bucket can be judged.
    result = intervention_test(
        _series({CHECKOUT: (20.0 + NOISE)[:N_BASE], PAYMENT: 50.0 + 3.0 * NOISE}),
        _edges([("checkout", "payment", True, 1.0)]),
        ALERT,
        "checkout",
        CFG,
    )
    assert (result.reason, result.independent_of_parents, result.n_incident) == ("no_incident", None, 0)


def test_a_tiny_shift_on_a_floored_scale_is_not_an_anomaly() -> None:
    # MAD ~ 0.01 ms, so the 03-anomara floor (max(eps 1 ms, 2% of 100 ms) = 2 ms) sets the scale:
    # +1 ms is z = 0.5, not the z ~ 90 that a second standardisation without the floor gives.
    checkout = 100.0 + 0.01 * OWN + np.where(np.arange(N_BASE + N_INC) >= N_BASE, 1.0, 0.0)
    result = intervention_test(
        _series({CHECKOUT: checkout, PAYMENT: 50.0 + 3.0 * NOISE}),
        _edges([("checkout", "payment", True, 1.0)]),
        ALERT,
        "checkout",
        CFG,
    )
    assert result.stat_raw == pytest.approx(0.5, abs=0.05)
    assert result.independent_of_parents is False


@settings(max_examples=25, deadline=None)
@given(st.floats(0.5, 2.0), st.floats(0.0, 0.3))
def test_an_inherited_anomaly_is_explained_even_without_own_noise(gain: float, own: float) -> None:
    # 05 §7 property: x = a·z + noise with a shift in z during the incident -> not independent.
    payment = 50.0 + 3.0 * NOISE + SHIFT
    result = intervention_test(
        _series({CHECKOUT: 20.0 + gain * payment + own * OWN, PAYMENT: payment}),
        _edges([("checkout", "payment", True, 1.0)]),
        ALERT,
        "checkout",
        CFG,
    )
    assert result.reason is None and result.independent_of_parents is False


@settings(max_examples=25, deadline=None)
@given(st.permutations(range(N_BASE + N_INC)))
def test_row_order_does_not_change_the_result(order: list[int]) -> None:
    payment = 50.0 + 3.0 * NOISE + SHIFT
    table = _series({CHECKOUT: 20.0 + payment + 0.3 * OWN, PAYMENT: payment})
    shuffled = table.take(pa.array([*order, *(i + N_BASE + N_INC for i in order)]))
    edges = _edges([("checkout", "payment", True, 1.0)])
    assert intervention_test(shuffled, edges, ALERT, "checkout", CFG) == intervention_test(
        table, edges, ALERT, "checkout", CFG
    )


def test_fisher_z_p_value_matches_the_textbook() -> None:
    # r = 0.5, n = 28, no conditioning set: z = atanh(0.5) * sqrt(25) = 2.7465, two-sided p = 0.00602.
    x = np.asarray([1.0, -1.0] * 14)
    y = 0.5 * x + math.sqrt(0.75) * np.asarray([1.0, 1.0, -1.0, -1.0] * 7)
    r, p = partial_corr_test(x, y, np.zeros((28, 0)))
    assert r == pytest.approx(0.5)
    assert p == pytest.approx(0.00602, abs=5e-5)
