"""Unit and property tests of the anomaly atoms and their ids (06 §3.2, §3.4, §7)."""

from __future__ import annotations

import dataclasses
import math
import tempfile
from pathlib import Path
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_core import io
from veyltrace_core.canonical import JSONLike
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_faultloom import atoms
from veyltrace_faultloom.atoms import PRODUCER, anomaly_atoms
from veyltrace_faultloom.inputs import AnomalyRow

#: atoms.detectors default (config/faultloom.yaml, 06 §4).
DETECTORS = ("robust_z", "nsigma", "silence")
#: Signal -> (klass, family) of the generated series (03 §1 vocabularies).
SIGNALS = {"cpu": ("internal", "cpu"), "lat": ("external", "latency"), "req": ("context", "traffic")}


def _row(series_id: str, detector: str = "robust_z", score: float = 1.0) -> AnomalyRow:
    service, component, signal, source = series_id.split("|")
    klass, family = SIGNALS[signal]
    return AnomalyRow(series_id, service, component, family, klass, source, detector, score, score >= 3)


def test_atom_id_reproduces_the_06_3_8_worked_example() -> None:
    rows = [_row("checkoutservice|checkoutservice|cpu|metrics", score=9.1)]
    (cpu,) = anomaly_atoms(rows, ["checkoutservice"], DETECTORS)
    assert cpu["atom_id"] == "Eff7aaef775"
    assert cpu["args_json"] == '{"detector":"robust_z","family":"cpu","source":"metrics","window":"incident"}'
    assert (cpu["kind"], cpu["value"], cpu["unit"], cpu["component"]) == ("internal_anomaly", 9.1, "z", None)
    assert (cpu["refs"], cpu["producer"]) == ([rows[0].series_id], PRODUCER)


def test_klass_picks_the_kind_and_context_series_have_none() -> None:
    rows = [_row("a|a|cpu|metrics"), _row("a|a|lat|traces"), _row("a|a|req|metrics")]
    got = [(a["kind"], a["refs"]) for a in anomaly_atoms(rows, ["a"], DETECTORS)]
    assert got == [("external_anomaly", ["a|a|lat|traces"]), ("internal_anomaly", ["a|a|cpu|metrics"])]


def test_value_is_the_max_over_components_with_ties_a_to_z() -> None:
    rows = [_row("p|p-2|cpu|logs", score=3.3), _row("p|p-1|cpu|logs", score=3.3), _row("p|p|cpu|logs")]
    (atom,) = anomaly_atoms(rows, ["p"], DETECTORS)
    assert (atom["value"], atom["component"]) == (3.3, "p-1")
    assert atom["refs"] == ["p|p-1|cpu|logs", "p|p-2|cpu|logs"]


def test_only_universe_members_and_configured_detectors_get_atoms() -> None:
    rows = [_row("a|a|cpu|metrics", "bocpd"), _row("a|a|cpu|metrics", "nsigma"), _row("ext|ext|lat|traces")]
    assert [(a["candidate"], a["unit"]) for a in anomaly_atoms(rows, ["a"], DETECTORS)] == [("a", "sigma")]
    assert anomaly_atoms(rows, ["a"], ["robust_z"]) == []


def test_a_detector_without_an_atom_unit_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="bocpd"):
        anomaly_atoms([], ["a"], [*DETECTORS, "bocpd"])


def test_an_atom_id_collision_is_a_hard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atoms, "atom_id", lambda *_: "E0000000000")
    with pytest.raises(ContractValidationError, match="collides"):
        anomaly_atoms([_row("a|a|cpu|metrics"), _row("a|a|lat|traces")], ["a"], DETECTORS)


def test_a_non_finite_score_is_a_contract_error_in_any_row_order() -> None:
    # Regression: a NaN was dropped when not first in its group and crashed min() when first.
    for bad in (math.nan, -math.inf):
        rows = [_row("a|a-1|cpu|metrics"), _row("a|a-2|cpu|metrics", score=bad)]
        for order in (rows, rows[::-1]):
            with pytest.raises(ContractValidationError, match="not finite"):
                anomaly_atoms(order, ["a"], DETECTORS)


_SERVICES = ("a", "b", "cart", "cart-0")
_parts = (_SERVICES, ("x", "x-1", "x-2"), sorted(SIGNALS), ("logs", "metrics", "traces"))
_series = st.tuples(*(st.sampled_from(p) for p in _parts)).map("|".join)
_scores = st.one_of(st.sampled_from((0.0, 3.3, 9.1)), st.floats(min_value=0, max_value=1e6))
_rows = st.lists(
    st.builds(_row, _series, st.sampled_from((*DETECTORS, "bocpd")), _scores),
    max_size=12,
    unique_by=lambda r: (r.series_id, r.detector),
)


@settings(max_examples=50, deadline=None)
@given(rows=_rows, data=st.data())
def test_evidence_bytes_do_not_depend_on_input_order(rows: list[AnomalyRow], data: st.DataObject) -> None:
    # 06 §7: shuffling input rows (and U, atoms.detectors) gives identical evidence bytes.
    universe = _SERVICES[:3]
    first = anomaly_atoms(rows, universe, DETECTORS)
    second = anomaly_atoms(
        data.draw(st.permutations(rows)),
        data.draw(st.permutations(universe)),
        data.draw(st.permutations(DETECTORS)),
    )
    assert first == second
    with tempfile.TemporaryDirectory() as tmp:
        assert io.write("evidence", first, Path(tmp, "a")) == io.write("evidence", second, Path(tmp, "b"))


@given(rows=_rows.filter(bool), data=st.data(), bump=st.floats(min_value=0, max_value=1e6))
def test_raising_a_score_never_lowers_an_atom(
    rows: list[AnomalyRow], data: st.DataObject, bump: float
) -> None:
    i = data.draw(st.integers(0, len(rows) - 1))
    raised = [dataclasses.replace(r, score=r.score + bump) if j == i else r for j, r in enumerate(rows)]
    before, after = _values(rows), _values(raised)
    assert before.keys() == after.keys()
    assert all(after[k] >= before[k] for k in before)


def _values(rows: list[AnomalyRow]) -> dict[JSONLike, float]:
    return {a["atom_id"]: cast("float", a["value"]) for a in anomaly_atoms(rows, _SERVICES, DETECTORS)}
