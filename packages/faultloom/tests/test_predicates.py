"""Predicate library (06 §3.5, 03 §7): shape, entry points, every predicate on the cpu-hog case."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_contracts.predicates import PREDICATES
from veyltrace_core import plugins
from veyltrace_faultloom.predicates import (
    LIBRARY,
    ClaimView,
)

#: 03 §7 "Polarity" column, copied from the table (supports = +1, refutes = -1).
POLARITY_03 = {
    "zscore_above": 1,
    "onset_before": 1,
    "edge_anomalous": -1,
    "self_time_share_above": 1,
    "change_before_onset": 1,
    "template_new_in_incident": 1,
    "error_rate_above": 1,
    "silent": 1,
    "on_critical_path": 1,
    "peer_gap_above": 1,
}


# --- library shape ------------------------------------------------------------------------------
def test_library_matches_03_and_predicates_json() -> None:
    assert {n: p.polarity for n, p in LIBRARY.items()} == POLARITY_03
    assert list(LIBRARY) == sorted(POLARITY_03)
    for spec in PREDICATES:
        code = LIBRARY[spec.name]
        assert [(p.name, p.type) for p in code.params] == [(p.name, p.type) for p in spec.params]
        assert code.polarity == (1 if spec.polarity == "supports" else -1)
        assert code.window == spec.window
    assert len(PREDICATES) == len(LIBRARY)


def test_entry_points_register_the_same_objects() -> None:
    assert plugins.load(plugins.PREDICATES) == dict(LIBRARY)


# --- every predicate on cpu-hog -----------------------------------------------------------------
CASES = [
    # (predicate, args, subject, value, holds)
    ("zscore_above", {"signal": "cpu", "k": 4.0}, "checkout", 9.1, True),
    ("zscore_above", {"signal": "cpu", "k": 10.0}, "checkout", 9.1, False),
    ("zscore_above", {"signal": "cpu", "k": 4.0}, "frontend", 0.0, None),  # no cpu series
    ("onset_before", {"other_service": "payment"}, "checkout", 42_000.0, True),
    ("onset_before", {"other_service": "frontend"}, "checkout", 14_000.0, False),  # within tol (15 s)
    ("onset_before", {"other_service": "checkout"}, "checkout", 0.0, None),  # subject = other
    ("onset_before", {"other_service": "checkout"}, "redis", 0.0, None),  # no onset
    ("edge_anomalous", {"callee": "checkout"}, "frontend", 1.0, True),
    ("edge_anomalous", {"callee": "payment"}, "checkout", 0.0, False),
    ("edge_anomalous", {"callee": "checkout"}, "payment", 0.0, False),  # no such edge
    ("edge_anomalous", {"callee": "redis"}, "checkout", 0.0, None),  # no trace data on the edge
    ("edge_anomalous", {"callee": "checkout"}, "checkout", 0.0, None),
    ("self_time_share_above", {"x": 0.3}, "checkout", 75 / 77.5, True),
    ("self_time_share_above", {"x": 0.3}, "frontend", 1 / 77.5, False),
    ("self_time_share_above", {"x": 0.3}, "card-gateway.example", 0.0, None),  # outside U: no atom
    ("change_before_onset", {"max_ms": 120_000.0}, "checkout", 60_000.0, True),
    ("change_before_onset", {"max_ms": 1_000.0}, "checkout", 60_000.0, False),
    ("change_before_onset", {"max_ms": 120_000.0}, "frontend", 0.0, False),  # no change
    ("template_new_in_incident", {"min_count": 3}, "checkout", 1.0, True),
    ("template_new_in_incident", {"min_count": 3}, "payment", 0.0, False),
    ("template_new_in_incident", {"min_count": 3}, "frontend", 0.0, None),  # no templates
    ("error_rate_above", {"x": 0.04}, "checkout", 0.05, True),
    ("error_rate_above", {"x": 0.04}, "payment", 0.02, False),
    ("error_rate_above", {"x": 0.04}, "frontend", 0.0, None),  # no incident edge into it
    ("silent", {}, "checkout", 0.0, False),
    ("silent", {}, "card-gateway.example", 0.0, None),
    ("on_critical_path", {"min_share": 0.5}, "checkout", 0.7, True),
    ("on_critical_path", {"min_share": 0.5}, "payment", 0.1, False),
    ("on_critical_path", {"min_share": 0.5}, "card-gateway.example", 0.0, None),
    ("peer_gap_above", {"x": 3.0}, "checkout", 7.6, True),
    ("peer_gap_above", {"x": 3.0}, "payment", 0.0, False),
    ("peer_gap_above", {"x": 3.0}, "frontend", 0.0, None),  # one component: no peer atom
]


@pytest.mark.parametrize(("name", "args", "subject", "value", "holds"), CASES)
def test_predicate_on_cpu_hog(
    cpu_hog: tuple[Any, ClaimView],
    name: str,
    args: dict[str, Any],
    subject: str,
    value: float,
    holds: bool | None,
) -> None:
    got = LIBRARY[name].evaluate(cpu_hog[1], subject, args)
    assert (got.value, got.holds) == (pytest.approx(value), holds)
    assert list(got.refs) == sorted(set(got.refs)) and (
        holds is not None or not got.refs or name == "edge_anomalous"
    )


def test_every_predicate_has_true_false_and_null_cases() -> None:
    seen = {(name, holds) for name, _, _, _, holds in CASES}
    missing = {(n, h) for n in LIBRARY for h in (True, False, None)} - seen
    # covered below: silent = 1.0 needs a silent service, change_before_onset is null only without events.
    assert missing == {("silent", True), ("change_before_onset", None)}


def test_silent_holds_for_a_silent_service(cpu_hog: tuple[Any, ClaimView]) -> None:
    view = cpu_hog[1]
    hushed = tuple(
        {**a, "value": 1.0} if (a["kind"], a["candidate"]) == ("silence", "payment") else a
        for a in view.atoms
    )
    got = LIBRARY["silent"].evaluate(dataclasses.replace(view, atoms=hushed), "payment", {})
    assert (got.value, got.holds) == (1.0, True)


@pytest.mark.parametrize("source", ["events", "logs", "traces"])
def test_a_missing_source_makes_its_predicates_null(cpu_hog: tuple[Any, ClaimView], source: str) -> None:
    view = cpu_hog[1]
    sources = models.Sources(**{s: s != source for s in ("metrics", "logs", "traces", "events")})
    blind = dataclasses.replace(view, inputs=dataclasses.replace(view.inputs, sources=sources))
    affected = {
        "events": [("change_before_onset", {"max_ms": 120_000.0})],
        "logs": [("template_new_in_incident", {"min_count": 3})],
        "traces": [("error_rate_above", {"x": 0.04}), ("on_critical_path", {"min_share": 0.5})],
    }[source]
    for name, args in affected:
        assert LIBRARY[name].evaluate(blind, "checkout", args).holds is None  # 06 §6
