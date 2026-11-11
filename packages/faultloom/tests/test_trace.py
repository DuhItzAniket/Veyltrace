"""Unit tests of the trace atoms and `atom_sources` on hand-built views (06 §3.3, §3.4, §3.8, §3.9)."""

from __future__ import annotations

import math
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_faultloom.sources import atom_sources
from veyltrace_faultloom.trace import critical_path_atoms, edge_gap_atoms, self_time_atoms, spectrum_atoms

U = ("checkout", "frontend", "payment")
NO_TRACES = models.Sources(metrics=True, logs=True, traces=False, events=True)


def _vals(atoms: list[dict[str, Any]]) -> dict[str, float]:
    return {a["candidate"]: a["value"] for a in atoms}


def _worked(hm: Any, **fields: Any) -> Any:
    """06 §3.8: incident critical path of frontend / checkout / payment; self-time p50 base -> inc."""
    rows = (
        hm.cp("incident", "frontend", 800, 0.20, 500, 60.0, p50=13.0),
        hm.cp("incident", "checkout", 800, 0.70, 500, 400.0, p50=95.0),
        hm.cp("incident", "payment", 800, 0.10, 300, 40.0, p50=9.5),
        hm.cp("baseline", "frontend", 1000, 0.30, 50, 15.0, p50=12.0),
        hm.cp("baseline", "checkout", 1000, 0.50, 50, 25.0, p50=20.0),
        hm.cp("baseline", "payment", 1000, 0.20, 30, 6.0, p50=8.0),
    )
    return hm.view(**{"universe": U, "critical_path": rows, **fields})


# --- spectrum ---------------------------------------------------------------------------------
def test_spectrum_reproduces_the_worked_example(hm: Any) -> None:
    got = _vals(spectrum_atoms(_worked(hm), "ochiai", "critical_path"))
    assert got == pytest.approx({"checkout": 0.7559289, "frontend": 0.2121320, "payment": 0.2})


def test_spectrum_without_weighting_uses_trace_counts(hm: Any) -> None:
    got = _vals(spectrum_atoms(_worked(hm), "ochiai", "none"))
    # e_f = traces_slow, cov = traces (= traces_slow here), F = 500: sqrt(e_f / 500).
    assert got == pytest.approx({"checkout": 1.0, "frontend": 1.0, "payment": (300 / 500) ** 0.5})


def test_spectrum_edge_cases(hm: Any) -> None:
    absent = _vals(spectrum_atoms(_worked(hm, universe=(*U, "redis")), "ochiai", "critical_path"))
    assert absent["redis"] == 0.0  # not on any slow path (06 §3.9)
    no_slow = hm.view(universe=U, critical_path=(hm.cp("incident", "checkout", 800, 0.7, 0, 0.0),))
    assert set(_vals(spectrum_atoms(no_slow, "ochiai", "critical_path")).values()) == {0.0}  # F = 0
    empty = hm.view(universe=U, critical_path=(hm.cp("incident", "checkout", 0, 0.0, 0, 0.0),))
    assert spectrum_atoms(empty, "ochiai", "critical_path") == []  # traces_total = 0
    assert spectrum_atoms(_worked(hm, sources=NO_TRACES), "ochiai", "critical_path") == []
    with pytest.raises(ConfigError, match="dstar2"):
        spectrum_atoms(_worked(hm), "dstar2", "critical_path")  # no formula in 06 §3.4 yet


# --- critical_path_share and self_time_share ----------------------------------------------------
def test_critical_path_share_per_window_and_zero_when_absent(hm: Any) -> None:
    atoms = critical_path_atoms(_worked(hm, universe=(*U, "redis")))
    got = {(a["candidate"], a["window"]): a["value"] for a in atoms}
    assert got[("checkout", "incident")] == 0.70 and got[("checkout", "baseline")] == 0.50
    assert got[("redis", "incident")] == 0.0  # absent from the window (06 §3.9)
    only_base = _worked(
        hm, critical_path=tuple(r for r in _worked(hm).critical_path if r.window == "baseline")
    )
    assert {str(a["window"]) for a in critical_path_atoms(only_base)} == {"baseline"}


def test_self_time_share_reproduces_the_worked_example(hm: Any) -> None:
    got = _vals(self_time_atoms(_worked(hm), "p50", 5.0))
    # positive increases 1 + 75 + 1.5 = 77.5 ms (06 §3.8)
    assert got == pytest.approx({"checkout": 75 / 77.5, "frontend": 1 / 77.5, "payment": 1.5 / 77.5})
    assert self_time_atoms(_worked(hm), "p50", 100.0) == []  # below self_time.min_total_increase_ms
    assert self_time_atoms(_worked(hm), "p99", 5.0) == []  # p99 not set in these rows: no increase
    assert self_time_atoms(_worked(hm, sources=NO_TRACES), "p50", 5.0) == []  # 06 §6
    with pytest.raises(ConfigError):
        self_time_atoms(_worked(hm), "p75", 5.0)


# --- edge_gap ---------------------------------------------------------------------------------
def test_edge_gap_is_the_median_delta_over_qualifying_edges(hm: Any) -> None:
    rows = (
        hm.edge_stat("frontend", "checkout", "baseline", 100, 2.0, 5.0),
        hm.edge_stat("frontend", "checkout", "incident", 100, 12.0, 25.0),
        hm.edge_stat("payment", "checkout", "baseline", 100, 1.0, None),
        hm.edge_stat("payment", "checkout", "incident", 100, 5.0, 9.0),  # p99 null in baseline
        hm.edge_stat("redis", "checkout", "baseline", 100, 1.0, 1.0),
        hm.edge_stat("redis", "checkout", "incident", 9, 50.0, 50.0),  # below min_calls 10
        hm.edge_stat("checkout", "payment", "incident", 100, 3.0, 3.0),  # no baseline row
    )
    atoms = edge_gap_atoms(hm.view(universe=U, edge_stats=rows), 10)
    got = {(a["candidate"], a["args_json"]): a["value"] for a in atoms}
    p50_in = ("checkout", '{"direction":"in","quantile":"p50","window":"incident"}')
    p99_in = ("checkout", '{"direction":"in","quantile":"p99","window":"incident"}')
    out = '{{"direction":"out","quantile":"{}","window":"incident"}}'.format
    assert got == {
        p50_in: 7.0,  # median(10, 4): even count, mean of the middle two
        p99_in: 20.0,  # payment's p99 gap is null in the baseline: frontend only
        ("frontend", out("p50")): 10.0,
        ("frontend", out("p99")): 20.0,
        ("payment", out("p50")): 4.0,
    }  # redis -> checkout has 9 incident calls; checkout -> payment has no baseline row
    assert atoms[0]["unit"] == "ms" and isinstance(refs := atoms[0]["refs"], list) and len(refs) == 4
    assert edge_gap_atoms(hm.view(universe=U, edge_stats=rows, sources=NO_TRACES), 10) == []  # 06 §6


_MS = st.none() | st.floats(0, 1e4)


@settings(max_examples=50)
@given(data=st.data())
def test_trace_atoms_are_finite_fractions_in_any_row_order(hm: Any, data: st.DataObject) -> None:
    # 06 §7: rows as Signalyth writes them (one per window and service or edge; e_f <= min(slow, cov)).
    d, cp, edges = data.draw, [], []
    for w in ("baseline", "incident"):
        total = d(st.integers(0, 1000))
        for s in U:
            slow, mean, e_f = d(st.integers(0, total)), d(st.floats(0, 1)), d(st.floats(0, 1))
            if d(st.booleans()):
                cp.append(
                    hm.cp(w, s, total, mean, slow, e_f * min(slow, total * mean), p50=d(st.floats(0, 1e4)))
                )
        for a, b in (("frontend", "checkout"), ("checkout", "payment")):
            if d(st.booleans()):
                edges.append(hm.edge_stat(a, b, w, d(st.integers(0, 100)), d(_MS), d(_MS)))

    def atoms(cp_rows: list[Any], edge_rows: list[Any]) -> list[dict[str, Any]]:
        v = hm.view(universe=U, critical_path=tuple(cp_rows), edge_stats=tuple(edge_rows))
        spectrum = spectrum_atoms(v, "ochiai", "critical_path")
        return [*spectrum, *critical_path_atoms(v), *self_time_atoms(v, "p50", 0.0), *edge_gap_atoms(v, 10)]

    got = atoms(cp, edges)
    assert got == atoms(d(st.permutations(cp)), d(st.permutations(edges)))
    values = [(a["kind"], cast(float, a["value"])) for a in got]
    assert all(math.isfinite(x) for _, x in values)
    assert all(0 <= x <= 1 + 1e-12 for k, x in values if k != "edge_gap")  # 1e-12: sqrt rounding


# --- atom_sources -----------------------------------------------------------------------------
def test_atom_sources_are_series_sources_plus_the_kind_tag() -> None:
    def atom(kind: str, refs: list[str], args: str = "{}") -> dict[str, Any]:
        return {"kind": kind, "refs": refs, "args_json": args}

    assert atom_sources(atom("internal_anomaly", ["a|a|cpu|metrics", "a|a|lat|traces"])) == {
        "metrics",
        "traces",
    }
    assert atom_sources(atom("spectrum", ["signal_cube.critical_path#0123456789ab"])) == {"traces"}
    assert atom_sources(atom("change_proximity", ["C0123456789"])) == {"events"}
    assert atom_sources(atom("log_new_template", ["T01234567"])) == {"logs"}
    assert atom_sources(atom("onset_precedence", ["onsets#0123456789ab"])) == frozenset()
    peer = '{"source":"changes","window":"onset"}'
    assert atom_sources(atom("peer_contrast", ["C0123456789"], peer)) == {"events"}
    assert atom_sources(atom("silence", ["a|a-1|errors|logs", "onsets#0123456789ab"])) == {"logs"}
    with pytest.raises(ContractValidationError, match="refs must be a list"):
        atom_sources(
            {"kind": "spectrum", "refs": "signal_cube.critical_path#0123456789ab", "args_json": "{}"}
        )
