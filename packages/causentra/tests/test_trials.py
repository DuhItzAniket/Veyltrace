"""Tests of trials T1–T4 and the fact-fixed T5/T6/T8 results: every row of the 09 §3.4 table."""

from __future__ import annotations

import itertools
import math
from importlib.metadata import entry_points
from typing import Any

import pytest

from veyltrace_causatrix.views import Atom, evidence_view, graph_view
from veyltrace_causentra.trials import (
    EVALUATED,
    TrialInputs,
    origin,
    pending,
    precedence,
    propagation,
    run_trials,
    silence_check,
)
from veyltrace_contracts.models import Sources

_IDS = itertools.count(1)
ALL = Sources(metrics=True, logs=True, traces=True, events=True)


def _a(cand: str, kind: str, value: float, **args: Any) -> Atom:
    return Atom(f"E{next(_IDS):010x}", cand, None, kind, args, value)


def _i(cand: str, z: float) -> Atom:
    return _a(
        cand, "internal_anomaly", z, detector="robust_z", family="cpu", source="metrics", window="incident"
    )


def _onset(cand: str, ms: float, scope: str = "self") -> Atom:
    return _a(cand, "onset_precedence", ms, scope=scope, window="onset")


def _t(
    atoms: list[Atom], calls: list[tuple[str, str]], tol_ms: float = 0.0, sources: Sources = ALL
) -> TrialInputs:
    members = sorted({a.candidate for a in atoms} | {s for c in calls for s in c} | {"c"})
    edges = [{"src": s, "dst": d, "weight": 1.0, "provenance": ["traces"]} for s, d in calls]
    graph = graph_view(members, [], edges, include_external=False)
    return TrialInputs(evidence_view(atoms, members), graph, sources, tol_ms, 3.0, 1.0, 0.5)


def _r(result: Any) -> tuple[str, str | None]:
    return result.result, result.reason


def test_t1_origin() -> None:
    assert _r(origin("c", _t([], []))) == ("untestable", "no_internal_series")
    assert _r(origin("c", _t([_i("c", 2.9)], []))) == ("fail", "no_internal_anomaly")
    quiet = _a("c", "silence", 0.0, window="incident")  # 06 §3.4: present, not silent
    assert _r(origin("c", _t([quiet], []))) == ("fail", "no_internal_anomaly")  # testable, no origin signal
    hot = [_i("c", 8.0), _onset("c", 100.0)]
    assert _r(origin("c", _t(hot, [("c", "d")]))) == ("pass", None)
    # A callee as anomalous and not later explains c; later than onset + tolerance does not.
    assert _r(origin("c", _t([*hot, _i("d", 9.0), _onset("d", 150.0)], [("c", "d")], tol_ms=50.0))) == (
        "fail",
        "explained_by_callee:d",
    )
    assert (
        _r(origin("c", _t([*hot, _i("d", 9.0), _onset("d", 151.0)], [("c", "d")], tol_ms=50.0)))[0] == "pass"
    )
    assert (
        _r(origin("c", _t([*hot, _i("d", 9.0)], [("c", "d")])))[1] == "explained_by_callee:d"
    )  # no onset: not later
    assert _r(origin("c", _t([*hot, _i("d", 7.9)], [("c", "d")])))[0] == "pass"
    assert _r(origin("c", _t([*hot, _i("d", 9.0)], [("d", "c")])))[0] == "pass"  # a caller never explains
    silent = _a("c", "silence", 1.0, window="incident")
    assert _r(origin("c", _t([silent], []))) == ("pass", None)  # Sil = 1 counts as the origin signal
    # Literal 09 §3.4: I(c) = 0 when silent, so any callee "explains" it (decision for the lead).
    assert _r(origin("c", _t([silent], [("c", "d")])))[1] == "explained_by_callee:d"
    result = origin("c", _t([*hot, _i("d", 1.0), _i("e", 2.0)], [("c", "d"), ("c", "e")]))
    assert len(result.atoms) == 3 and list(result.atoms) == sorted(result.atoms)


def test_t2_precedence() -> None:
    assert _r(precedence("c", _t([], []))) == ("untestable", "no_onset")
    assert _r(precedence("c", _t([_onset("c", 0.0)], []))) == ("pass", None)  # no anomalous dependents
    assert _r(precedence("c", _t([_onset("c", 0.0), _onset("c", 1.0, "dependents")], []))) == ("pass", None)
    late = _t([_onset("c", 0.0), _onset("c", 0.5, "dependents")], [])
    assert _r(precedence("c", late)) == ("fail", "dependent_earlier")
    assert len(precedence("c", late).atoms) == 2


def _prop(scope: str, value: float) -> Atom:
    return _a("c", "propagation", value, scope=scope, window="incident")


def test_t3_propagation() -> None:
    assert _r(propagation("c", _t([_prop("entry", 1.0)], []))) == ("untestable", "no_graph_edges")
    assert _r(propagation("c", _t([], [("f", "c")]))) == ("untestable", "no_anomalous_entry")
    assert _r(propagation("c", _t([_prop("entry", 1.0)], [("f", "c")]))) == ("pass", None)  # path absent
    assert _r(propagation("c", _t([_prop("entry", 1.0), _prop("path", 0.5)], [("f", "c")]))) == ("pass", None)
    assert _r(propagation("c", _t([_prop("entry", 0.5)], [("f", "c")]))) == ("fail", "entry_unreachable")
    low = _t([_prop("entry", 1.0), _prop("path", 0.25)], [("f", "c")])
    assert _r(propagation("c", low)) == ("fail", "path_not_anomalous")


def test_t4_silence_check() -> None:
    quiet = _a("c", "silence", 0.0, window="incident")
    assert _r(silence_check("c", _t([], [("c", "d")]))) == ("untestable", "no_silence_status")
    assert _r(silence_check("c", _t([quiet], []))) == ("untestable", "no_graph_edges")
    assert _r(silence_check("c", _t([quiet], [("c", "d")]))) == ("pass", None)
    deep = [quiet, _a("e", "silence", 1.0, window="incident"), _a("b", "silence", 1.0, window="incident")]
    calls = [("c", "d"), ("d", "e"), ("b", "c")]  # e is a descendant; b is a caller and does not count
    result = silence_check("c", _t(deep, calls))
    assert _r(result) == ("fail", "silent_callee:e") and len(result.atoms) == 2
    looped = [quiet, _a("c", "silence", 1.0, window="incident")]
    assert (
        _r(silence_check("c", _t(looped, [("c", "d"), ("d", "c")])))[0] == "pass"
    )  # c itself is not a descendant


def test_pending_facts_and_order() -> None:
    none = Sources(metrics=True, logs=True, traces=False, events=False)
    assert [(r.id, r.reason) for r in pending("c", _t([], [], sources=none))] == [
        ("T6", "no_events"),
        ("T8", "intervention_unavailable"),
    ]
    assert [r.id for r in pending("c", _t([], []))] == ["T5", "T8"]
    with_share = _t([_a("c", "self_time_share", 0.4, quantile="p50", window="incident")], [])
    assert [r.id for r in pending("c", with_share)] == ["T8"]  # T5 with a share atom is R-12's
    ids = [r.id for r in run_trials("c", _t([], []))]
    assert ids == ["T1", "T2", "T3", "T4", "T5", "T8"]
    assert all(
        r.as_json()["reason"] is None for r in run_trials("c", _t([_i("c", 9.0)], [])) if r.result == "pass"
    )


def test_entry_points_are_the_evaluated_trials() -> None:
    declared = {ep.name: ep.load() for ep in entry_points(group="veyltrace.trials")}
    assert declared == {t.id: t for t in EVALUATED}


@pytest.mark.parametrize("onset", [0.0, math.inf])
def test_t1_ignores_callees_outside_the_graph(onset: float) -> None:
    atoms = [_i("c", 8.0), _i("x", 9.0)] + ([_onset("c", onset)] if math.isfinite(onset) else [])
    assert _r(origin("c", _t(atoms, []))) == ("pass", None)
