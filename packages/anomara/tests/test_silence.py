"""Unit and property tests of the silence detector (03-anomara §3.5, §7; FR-7)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_anomara.series import Series
from veyltrace_anomara.settings import anomara_config
from veyltrace_anomara.silence import silence
from veyltrace_core.config import load_section_file

CFG = anomara_config(load_section_file("anomara")).silence
NS = 1_000_000_000
G = 10 * NS
T0 = 1_767_225_600 * NS
BASE: tuple[int, int] = (T0, T0 + 600 * NS)
INC: tuple[int, int] = (T0 + 600 * NS, T0 + 1200 * NS)
END = INC[1] - G  # last bucket of the case for this source


def _series(signal: str, values: Sequence[float | None], source: str = "traces") -> Series:
    """One point per 10 s bucket from T0; None leaves the bucket without a point."""
    pairs = [(T0 + k * G, v) for k, v in enumerate(values) if v is not None]
    t = np.asarray([p[0] for p in pairs], dtype=np.int64)
    x = np.asarray([p[1] for p in pairs], dtype=np.float64)
    return Series(f"a|a|{signal}|{source}", "a", "a", signal, "traffic", "context", source, "1/s", t, x)


def _case(baseline: Sequence[float | None], incident: Sequence[float | None]) -> list[float | None]:
    pad_b, pad_i = [baseline[-1]] * (60 - len(baseline)), [incident[-1]] * (60 - len(incident))
    return [*baseline, *pad_b, *incident, *pad_i]


def test_zero_silence_scores_the_run_in_units_of_l() -> None:
    # rps drops to 0 for 120 s at the incident start: L = max(60 s, 3 * 10 s) = 60 s -> score 2.
    values = _case([5.0], [0.0] * 12 + [5.0])
    score = silence(_series("rps", values), G, BASE, INC, END, CFG)
    assert (score.score, score.onset_ns, score.direction, score.above_threshold) == (
        2.0,
        INC[0],
        "down",
        True,
    )


def test_zero_counts_only_for_zero_signals_and_non_zero_baselines() -> None:
    drop = _case([5.0], [0.0] * 12 + [5.0])
    assert silence(_series("latency_p99", drop), G, BASE, INC, END, CFG).score == 0.0
    mostly_zero = _case([0.0, 0.0, 5.0] * 20, [0.0] * 12 + [5.0])  # 2/3 zero baseline > 0.2
    assert silence(_series("rps", mostly_zero), G, BASE, INC, END, CFG).score == 0.0


def test_absence_silence_for_any_series_with_a_covered_baseline() -> None:
    gap = _case([1.0], [None] * 9 + [1.0])  # 90 s without a point
    score = silence(_series("latency_p99", gap), G, BASE, INC, END, CFG)
    assert (score.score, score.onset_ns) == (1.5, INC[0])
    sparse = _case([1.0, None] * 30, [None] * 9 + [1.0])  # baseline coverage 0.5 < 0.8
    assert silence(_series("latency_p99", sparse), G, BASE, INC, END, CFG).score == 0.0


def test_a_truncated_case_is_not_silent() -> None:
    # The whole source ends at the incident start: buckets after its last point do not count.
    stops = _case([1.0], [None])
    assert silence(_series("rps", stops), G, BASE, INC, INC[0] - G, CFG).score == 0.0
    assert silence(_series("rps", stops), G, BASE, INC, None, CFG).score == 0.0
    # The same series in a case whose other series keep going is silent.
    assert silence(_series("rps", stops), G, BASE, INC, END, CFG).above_threshold


def test_a_gap_shorter_than_l_is_not_silent() -> None:
    blip = _case([5.0], [0.0] * 5 + [5.0])  # 50 s < L = 60 s
    score = silence(_series("rps", blip), G, BASE, INC, END, CFG)
    assert (score.score, score.score_norm, score.onset_ns, score.above_threshold) == (0.0, 0.0, None, False)


def test_onset_is_the_first_qualifying_run_and_score_the_longest() -> None:
    values = _case([5.0], [5.0] * 3 + [0.0] * 6 + [5.0] * 3 + [0.0] * 18 + [5.0])
    score = silence(_series("rps", values), G, BASE, INC, END, CFG)
    assert (score.onset_ns, score.score) == (INC[0] + 3 * G, 3.0)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.floats(0.5, 1e6, allow_nan=False), min_size=60, max_size=60),
    st.integers(6, 60),
    st.integers(0, 30),
)
def test_fr7_a_drop_to_zero_for_at_least_l_is_silent(baseline: list[float], steps: int, start: int) -> None:
    incident: list[float | None] = [*([1.0] * start), *([0.0] * steps)]
    values: list[float | None] = [*baseline, *(incident + [1.0] * 60)[:60]]
    score = silence(_series("rps", values), G, BASE, INC, END, CFG)
    run = min(steps, 60 - start)
    assert score.above_threshold == (run * G >= 60 * NS)
