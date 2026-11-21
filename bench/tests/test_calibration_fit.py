"""The 09 §3.7-3.8 fits: q_hat and tau_nf by rank index, +inf handling, files core loads."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench import calibration as cal
from veyltrace_contracts import models
from veyltrace_core import cli, io, testing
from veyltrace_core.calibration import find_calibration, write_calibration
from veyltrace_core.canonical import canonical_json
from veyltrace_core.ids import case_id
from veyltrace_core.pipeline import run_case

COMMON: dict[str, Any] = {
    "family": "rcaeval-re2",
    "ai_arm": "off",
    "alert_protocol": "oracle",
    "fold": "foldA",
    "alpha": 0.10,
    "beta": 0.10,
    "default_tau": 1.386294361,
    "seed": 20261108,
    "config_sha256s": ["a" * 64],
    "code_commit": "abc",
    "experiment_id": "re2-oracle-rq3-v1",
}


def _fault(i: int, score: float) -> cal.CalibrationRun:
    return cal.CalibrationRun(f"{i:012x}", None, score=score)


def _window(i: int, m: float | None, source: str = cal.PRE_INJECTION) -> cal.CalibrationRun:
    return cal.CalibrationRun(f"{i:012x}", "shift-510", source=source, statistic=m)


@pytest.mark.parametrize(("n", "want"), [(135, 123), (8, 9), (9, 9), (19, 18), (29, 27), (0, 1)])
def test_rank_index_is_the_finite_sample_ceiling(n: int, want: int) -> None:
    assert cal.rank_index(n, 0.10) == want  # 04 §5.4 item 5: n = 135 gives 123


@given(st.lists(st.floats(0, 1) | st.just(math.inf), max_size=40), st.sampled_from([0.05, 0.1, 0.2]))
def test_q_hat_is_the_rank_index_th_score_or_null(scores: list[float], alpha: float) -> None:
    got = cal.fit([_fault(i, s) for i, s in enumerate(scores)], **{**COMMON, "alpha": alpha})
    k = cal.rank_index(len(scores), alpha)
    want = sorted(scores)[k - 1] if k <= len(scores) else None
    assert (got.n, got.rank_index) == (len(scores), k)
    assert got.q_hat == (None if want is None or math.isinf(want) else want)
    covered = sum(s <= (math.inf if got.q_hat is None else got.q_hat) for s in scores)
    assert covered >= min(k, len(scores))  # at least rank_index calibration roots are in their set


def test_tau_nf_is_fitted_from_nine_windows_and_defaults_below() -> None:
    eight = [_window(i, 0.1 * i) for i in range(8)]
    few = cal.fit(eight, **COMMON)
    assert few.no_fault.model_dump() == {
        "beta": 0.1, "m": 8, "rank_index": 9, "tau_nf": 1.386294361, "calibrated": False,
        "sources": ["rcaeval_pre_injection"],
    }  # fmt: skip
    nine = cal.fit([*eight, _window(8, 0.8, cal.SYNTH_05)], **COMMON)
    assert (nine.no_fault.m, nine.no_fault.rank_index, nine.no_fault.calibrated) == (9, 9, True)
    assert nine.no_fault.tau_nf == pytest.approx(0.8)  # the largest of 9
    assert nine.no_fault.sources == ["rcaeval_pre_injection", "synth-05"]
    assert nine.n == 0 and nine.q_hat is None  # no fault case: q_hat +inf, set = whole pool


def _never(i: int, reason: str) -> cal.CalibrationRun:
    return cal.CalibrationRun(
        f"{i:012x}", "shift-510", source=cal.PRE_INJECTION, statistic=math.inf, never=reason
    )


def test_windows_that_can_never_be_no_fault_score_inf_and_stay_in_m() -> None:
    """Failed, no-M and silent windows are false alarms at test time, so they count in m at +inf
    (ADR 20261121-ak-calibration-fit-conventions); an index landing on +inf has no finite tau."""
    nineteen = [_window(i, 0.01 * i) for i in range(19)]
    one = cal.fit([*nineteen, _never(19, cal.SILENT)], **COMMON)  # m 20, index 19: the 19th finite M
    assert (one.no_fault.m, one.no_fault.rank_index, one.no_fault.calibrated) == (20, 19, True)
    assert one.no_fault.tau_nf == pytest.approx(0.18)
    nine = [_window(i, 0.1 * i) for i in range(9)]
    landed = cal.fit([*nine, _never(9, cal.NO_M)], **COMMON)  # m 10, index 10: +inf
    assert (landed.no_fault.m, landed.no_fault.calibrated, landed.no_fault.tau_nf) == (10, False, 1.386294361)
    runs = [_never(1, cal.FAILED), _never(2, cal.NO_M), _never(3, cal.NO_M), _window(4, 0.1)]
    assert cal.never_counts(runs) == {"n_failed": 1, "n_no_m": 2, "n_silent": 0}
    assert cal.window("000000000009", None, cal.SYNTH_05, None) == cal.CalibrationRun(
        "000000000009", None, source=cal.SYNTH_05, statistic=math.inf, never=cal.FAILED
    )  # no run dir: the run failed or timed out


def test_file_has_no_case_ids_round_trips_through_core_and_hashes_order_free(tmp_path: Path) -> None:
    runs = [_fault(1, 0.2), _fault(2, math.inf), _window(3, 0.5)]
    content = cal.fit(runs, **COMMON)
    assert content.family == "rcaeval-re2.off.oracle.foldA" and content.split.fold == "foldA"
    assert not any(r.case_id in canonical_json(content).decode() for r in runs)  # 03 §12.1: no ids
    assert cal.fit(list(reversed(runs)), **COMMON) == content
    assert cal.fit([*runs[:1], _fault(2, 0.9), runs[2]], **COMMON).scores_sha256 != content.scores_sha256
    write_calibration(tmp_path, content)
    ref = find_calibration(tmp_path, content.family, ai_arm="off", alert_protocol="oracle")
    assert ref is not None and ref.content == content
    loso = cal.fit(runs, **{**COMMON, "fold": "loso-ob", "config_sha256s": ["b" * 64, "a" * 64]})
    assert loso.family == "rcaeval-re2.off.oracle.loso-ob" and loso.config_sha256 not in ("a" * 64, "b" * 64)


def test_root_score_reads_the_pool_with_the_coarse_transform() -> None:
    verdict = testing.golden("verdict", "synth-01")
    assert isinstance(verdict, models.Verdict)
    leader = verdict.ranked[0]
    assert cal.root_score(verdict, leader.service) == leader.nonconformity == 0.0
    assert cal.root_score(verdict, f"{leader.service}-db") == 0.0  # -db folded as RCAEval does
    assert cal.root_score(verdict, "not-a-service") == math.inf
    assert cal.root_score(None, leader.service) == math.inf  # no verdict: outside the pool
    assert cal.root_score(verdict, leader.service, unranked=True) == math.inf  # a miss (04 §7)


def test_run_statistic_is_causentras_m(tmp_path: Path) -> None:
    """On synth-05 (no fault) M decides the uncalibrated verdict exactly as Causentra did."""
    assert cli.main(["data", "fetch", "synth"]) == 0
    for case in ("synth-05", "synth-01"):
        s = run_case("synth", case, "off", runs_root=tmp_path / "runs")
        m, silent = cal.run_statistic(s.run_dir)
        status = io.read_model("verdict", s.run_dir, models.Verdict).status
        assert s.case_id == case_id(case) and m is not None
        assert (status == "NO_FAULT") == (not silent and round(m, 9) <= 1.386294361)  # default tau
        assert cal.window(s.case_id, None, cal.SYNTH_05, s.run_dir).statistic == (math.inf if silent else m)


def test_held_out_rates_per_fold_and_pooled() -> None:
    def row(fold: str | None, hit: int | None, in_set: bool | None, status: str) -> dict[str, object]:
        cells: dict[str, object] = {
            "method": "veyltrace:off",
            "seed": None,
            "fold": fold,
            "hit_at_1": hit,
            "in_set": in_set,
        }
        return cells | {"status": status}

    rows = [
        row("foldA", 1, True, "CONFIRMED"),
        row("foldA", 0, None, "INCONCLUSIVE"),  # a failed or unranked run: a miss
        row("foldA", None, None, "NO_FAULT"),
        row("foldB", 1, True, "LIKELY"),
        row("foldB", None, None, "LIKELY"),  # a normal window not declared NO_FAULT: a false alarm
        row(None, 1, True, "CONFIRMED"),  # not held out
    ]
    got = {str(r["fold"]): r for r in cal.held_out_rates(rows)}
    rates = [(got[f]["n_fault"], got[f]["coverage"], got[f]["false_alarm_rate"]) for f in sorted(got)]
    assert rates == [(2, 0.5, 0.0), (1, 1.0, 1.0), (3, 2 / 3, 0.5)]  # foldA, foldB, pooled
