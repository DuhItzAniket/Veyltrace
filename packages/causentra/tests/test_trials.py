"""Tests of trials T1–T8: every row of the 09 §3.4 table, including non-applicability."""

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
    change_alignment,
    intervention,
    latency_accounting,
    leave_one_source_out,
    origin,
    peer_contrast,
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
    atoms: list[Atom],
    calls: list[tuple[str, str]],
    tol_ms: float = 0.0,
    sources: Sources = ALL,
    ablations: tuple[tuple[str, tuple[str, ...]], ...] = (),
    top_k: frozenset[str] = frozenset({"c"}),
) -> TrialInputs:
    members = sorted({a.candidate for a in atoms} | {s for c in calls for s in c} | {"c"})
    edges = [{"src": s, "dst": d, "weight": 1.0, "provenance": ["traces"]} for s, d in calls]
    graph = graph_view(members, [], edges, include_external=False)
    return TrialInputs(
        evidence_view(atoms, members),
        graph,
        sources,
        tol_ms,
        3.0,
        1.0,
        0.5,
        0.30,
        0.36787944,
        3.0,
        2,
        ablations,
        top_k,
    )


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


NO_TRACES = Sources(metrics=True, logs=True, traces=False, events=True)
NO_EVENTS = Sources(metrics=True, logs=True, traces=True, events=False)


def _share(value: float) -> Atom:
    return _a("c", "self_time_share", value, quantile="p50", window="incident")


def test_t5_latency_accounting() -> None:
    assert _r(latency_accounting("c", _t([], []))) == ("untestable", "no_latency_increase")
    assert _r(latency_accounting("c", _t([_share(0.30)], []))) == ("pass", None)  # 0.30 itself passes
    assert _r(latency_accounting("c", _t([_share(0.2999999996)], []))) == ("pass", None)  # read at 9 decimals
    low = latency_accounting("c", _t([_share(0.29), _share(0.1)], []))
    assert _r(low) == ("fail", "share_below_min") and len(low.atoms) == 2
    assert "T5" not in [r.id for r in run_trials("c", _t([_share(0.9)], [], sources=NO_TRACES))]


def _change(value: float) -> Atom:
    return _a("c", "change_proximity", value, change_id="ch1", event_kind="deploy", window="onset")


def test_t6_change_alignment() -> None:
    assert _r(change_alignment("c", _t([_change(0.9)], [], sources=NO_EVENTS))) == ("untestable", "no_events")
    assert _r(change_alignment("c", _t([], []))) == ("fail", "no_recent_change")  # events, no change on c
    assert _r(change_alignment("c", _t([_change(0.2)], []))) == ("fail", "no_recent_change")
    at_tau = math.exp(-1.0)  # Δt = τ_change exactly: proximity e⁻¹ passes (09 §3.4)
    assert _r(change_alignment("c", _t([_change(0.2), _change(at_tau)], []))) == ("pass", None)
    other = _a("d", "change_proximity", 0.9, change_id="ch2", event_kind="deploy", window="onset")
    assert _r(change_alignment("c", _t([other], []))) == ("fail", "no_recent_change")  # d's change is not c's


def _peer(value: float, source: str = "anomalies") -> Atom:
    return _a("c", "peer_contrast", value, source=source, window="incident")


def test_t7_peer_contrast() -> None:
    assert "T7" not in [r.id for r in run_trials("c", _t([], []))]  # no peer_contrast atom: not applicable
    assert _r(peer_contrast("c", _t([_peer(3.0)], []))) == ("pass", None)
    assert _r(peer_contrast("c", _t([_peer(1.0), _peer(4.0, "changes")], []))) == (
        "pass",
        None,
    )  # both sources
    assert _r(peer_contrast("c", _t([_peer(2.9)], []))) == ("fail", "peers_alike")
    assert [r.id for r in run_trials("c", _t([_peer(2.9)], []))].count("T7") == 1


def _ci(value: float) -> Atom:
    return _a(
        "c",
        "intervention",
        value,
        parents_hash="0123456789ab",
        series_id="c|c|cpu|metrics",
        window="incident",
    )


def test_t8_intervention() -> None:
    assert _r(intervention("c", _t([], []))) == ("untestable", "intervention_unavailable")
    assert _r(intervention("c", _t([_ci(3.0)], []))) == ("pass", None)  # stat_resid ≥ k_anom
    explained = intervention("c", _t([_ci(1.5)], []))
    assert _r(explained) == ("fail", "explained_by_parents") and len(explained.atoms) == 1


def test_t9_leave_one_source_out() -> None:
    # k = 2 in _t: c must stay in the first two places of every re-ranking.
    kept = (("logs", ("a", "c", "b")), ("metrics", ("c", "a", "b")))
    assert _r(leave_one_source_out("c", _t([], [], ablations=kept))) == ("pass", None)
    lost = (("events", ("c", "a")), ("logs", ("a", "b", "c")), ("traces", ("a", "b")))
    result = leave_one_source_out("c", _t([], [], ablations=lost))
    assert _r(result) == ("fail", "drops_out_without:logs") and result.atoms == ()  # first source, sorted
    assert "T9" not in [r.id for r in run_trials("c", _t([], []))]  # < 2 sources: no re-rankings
    assert [r.id for r in run_trials("c", _t([], [], ablations=kept))][-1] == "T9"
    # Outside the unablated top K (e.g. proposal origin): not applicable, so no T9 entry (#364 review).
    outside = _t([], [], ablations=kept, top_k=frozenset({"a", "b"}))
    assert "T9" not in [r.id for r in run_trials("c", outside)]


def test_applicability_and_order() -> None:
    assert [r.id for r in run_trials("c", _t([], []))] == ["T1", "T2", "T3", "T4", "T5", "T6", "T8"]
    bare = Sources(metrics=True, logs=False, traces=False, events=False)
    assert [(r.id, r.result) for r in run_trials("c", _t([_peer(5.0)], [], sources=bare))][4:] == [
        ("T6", "untestable"),
        ("T7", "pass"),
        ("T8", "untestable"),
    ]
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
