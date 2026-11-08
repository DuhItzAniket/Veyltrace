"""Unit and property tests of the onset of record, per-service onsets and t_onset (03-anomara §3.6–3.7)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_anomara.onsets import Scored, per_service, series_onsets, t_onset
from veyltrace_anomara.robust import Score
from veyltrace_anomara.series import Series
from veyltrace_anomara.settings import anomara_config
from veyltrace_core.config import load_section_file

CFG = anomara_config(load_section_file("anomara"))
NS = 1_000_000_000
T = 1_000 * NS  # t_alert of the examples
EMPTY = np.zeros(0, dtype=np.int64)


def _hit(onset_s: float | None, threshold: float = 3.0) -> Score:
    if onset_s is None:
        return Score.flat(threshold)
    return Score(threshold + 1.0, 1.0, "up", int(onset_s * NS), threshold)


def _scored(
    sid: str, klass: str, rz: float | None = None, bo: float | None = None, si: float | None = None
) -> Scored:
    service, component, signal, source = sid.split("|")
    series = Series(sid, service, component, signal, "other", klass, source, None, EMPTY, EMPTY.astype(float))
    return Scored(series, _hit(rz), _hit(bo, 0.5), _hit(si, 1.0))


@pytest.mark.parametrize(
    ("rz", "bo", "expected"),
    [(1000, 950, 950), (1000, 870, 1000), (1000, 1010, 1000), (1000, None, 1000), (None, 950, None)],
    ids=["bocpd-inside-lead", "bocpd-too-early", "bocpd-after", "no-bocpd", "no-robust-z"],
)
def test_onset_of_record_uses_bocpd_inside_the_lead_window(
    rz: float | None, bo: float | None, expected: float | None
) -> None:
    tau, _ = series_onsets(_scored("a|a|x|metrics", "external", rz, bo), CFG.onset)
    assert tau == (None if expected is None else int(expected * NS))


def test_external_internal_onsets_and_their_sources() -> None:
    items = [
        _scored("a|a|latency_p99|traces", "external", rz=1010),
        _scored("a|a|rps|traces", "context", si=1005),  # silence of a context series is external
        _scored("a|a|cpu|metrics", "internal", rz=990),
        _scored("a|a|mem|metrics", "internal", si=990),  # tie at 990: the smaller series_id wins
        _scored("b|b|latency|metrics", "external"),
    ]
    a, b, c = per_service(["c", "b", "a"], items, CFG.onset, CFG.silence)
    assert (a["external_onset_ns"], a["external_onset_source"]) == (1005 * NS, "traces")
    assert (a["internal_onset_ns"], a["internal_onset_source"]) == (990 * NS, "metrics")
    assert a["silent"] is True  # its rps series is silent
    for entry in (b, c):
        assert (entry["external_onset_ns"], entry["external_onset_source"], entry["silent"]) == (
            None,
            None,
            False,
        )
    assert [p["service"] for p in (a, b, c)] == ["a", "b", "c"]


def test_a_service_is_silent_when_half_its_metric_series_are() -> None:
    half = [_scored("s|s|cpu|metrics", "internal", si=1000), _scored("s|s|mem|metrics", "internal")]
    third = [*half, _scored("s|s|disk|metrics", "internal")]
    assert per_service(["s"], half, CFG.onset, CFG.silence)[0]["silent"] is True
    assert per_service(["s"], third, CFG.onset, CFG.silence)[0]["silent"] is False


@pytest.mark.parametrize(
    ("onsets", "expected", "method"),
    [
        ([], 1000, "t_alert_fallback"),
        ([1003], 1003, "single_external"),
        ([1012, 1003, 1010], 1010, "second_external"),  # 03-anomara §3.7 example
        ([None, 1003, 1003], 1003, "second_external"),
        ([900, 920], 940, "second_external"),  # clamped up to t_alert - 60 s
        ([1400, 1500], 1300, "second_external"),  # clamped down to t_alert + 300 s
    ],
)
def test_t_onset_method_and_clamp(onsets: list[int | None], expected: int, method: str) -> None:
    found = t_onset([None if o is None else o * NS for o in onsets], T, CFG.onset)
    assert (found.t_onset_ns, found.method) == (expected * NS, method)


@given(st.lists(st.one_of(st.none(), st.integers(0, 3000)), max_size=6))
def test_t_onset_always_inside_the_clamp(onsets: list[int | None]) -> None:
    found = t_onset([None if o is None else o * NS for o in onsets], T, CFG.onset)
    assert T - 60 * NS <= found.t_onset_ns <= T + 300 * NS
