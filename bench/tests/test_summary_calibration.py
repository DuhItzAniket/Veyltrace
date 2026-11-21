"""The bench_summary 1.2 entries (CCR #404, #405) on hand-made rows with known answers: coverage, set
size, NO_FAULT rates, risk-coverage, selective accuracy, top-1 change and permutation invariance,
each with its null and zero-denominator cases."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from veyltrace_bench.metrics import CaseScore, MethodOutput, Truth, score_case
from veyltrace_bench.summary import METRIC_KEYS, ROW_ENTRIES, aurc, entries, summarize, with_rows

H1, H2 = "a" * 64, "b" * 64


def _row(
    *,
    truth: bool = True,
    hit: bool = False,
    in_set: bool | None = None,
    pool: bool | None = None,
    size: int | None = None,
    status: str | None = None,
    verdict: bool = True,
    margin: float | None = None,
    fused: float | None = None,
    case: str = "c1",
    seed: int | None = None,
    variant: str | None = None,
    fold: str | None = None,
    top: str | None = None,
    vhash: str | None = None,
) -> CaseScore:
    """One scored row with its per_case columns, as summary.with_rows leaves it."""
    return CaseScore(
        outcome="ok", has_truth=truth, unranked=False, ranks=(f"{top}_cpu",) if top else (),
        position=1 if hit and truth else None, fine_position=None, fine_applicable=False,
        retrieval_hit=None, pool_hit=pool, in_set=in_set, set_size=size, fault_class_hit=None,
        n_candidates=None, in_universe=None, slate_k=None, has_verdict=verdict, margin=margin,
        leader_fused_score=fused, case_id=case, seed=seed, variant=variant, fold=fold, status=status,
        verdict_hash=vhash,
    )  # fmt: skip


def _entry(name: str, rows: list[CaseScore], alpha: float = 0.1) -> dict[str, object]:
    got = entries(rows, [name], alpha=alpha)[name]
    assert isinstance(got, dict) and sorted(got) == sorted(METRIC_KEYS[name])  # exactly its keys
    shuffled = rows[:]
    random.Random(0).shuffle(shuffled)
    assert entries(shuffled, [name], alpha=alpha)[name] == got  # row order never matters
    return got


def test_coverage_its_gap_pool_coverage_and_folds() -> None:
    rows = [
        _row(in_set=True, pool=True, fold="foldA"),
        _row(in_set=False, pool=True, fold="foldA"),
        _row(in_set=True, pool=False, fold="foldB"),
        _row(in_set=False, pool=False),  # no fold: pooled only, never in by_fold
        _row(truth=False, fold="foldC"),  # a normal row: in no coverage denominator
    ]
    got = _entry("coverage", rows)
    assert (got["coverage"], got["pool_coverage"], got["n_fault"]) == (0.5, 0.5, 4)
    assert got["coverage_gap"] == pytest.approx(0.5 - 0.9)
    assert got["by_fold"] == [
        {"fold": "foldA", "coverage": 0.5, "n_fault": 2},
        {"fold": "foldB", "coverage": 1.0, "n_fault": 1},
        {"fold": "foldC", "coverage": None, "n_fault": 0},
    ]
    none = {"coverage": None, "coverage_gap": None, "pool_coverage": None}
    assert _entry("coverage", []) == none | {"n_fault": 0, "by_fold": []}
    baseline = [_row(verdict=False), _row(verdict=False)]  # no set channel: null, not 0
    assert _entry("coverage", baseline) == none | {"n_fault": 2, "by_fold": []}


def test_set_size_over_fault_rows() -> None:
    rows = [_row(size=1), _row(size=1), _row(size=3), _row(size=None), _row(truth=False, size=0)]
    got = _entry("set_size", rows)
    assert got == {"set_size_mean": 5 / 3, "set_size_median": 1, "singleton_share": 2 / 3, "n_set": 3}
    assert _entry("set_size", [_row(truth=False, size=0)]) == {
        "set_size_mean": None, "set_size_median": None, "singleton_share": None, "n_set": 0,
    }  # fmt: skip


def test_no_fault_rates() -> None:
    rows = [
        _row(truth=False, status="NO_FAULT", fold="foldA"),
        _row(truth=False, status="INCONCLUSIVE", fold="foldA"),
        _row(truth=False, status=None, fold="foldB"),  # a failed run is a false alarm
        _row(status="NO_FAULT"),
        _row(status="CONFIRMED"),
    ]
    got = _entry("no_fault_rates", rows)
    assert got == {
        "false_alarm_rate": 2 / 3, "n_normal": 3, "wrong_no_fault_rate": 0.5, "n_fault": 2,
        "no_fault_precision": 0.5, "no_fault_recall": 1 / 3,
        "by_fold": [
            {"fold": "foldA", "false_alarm_rate": 0.5, "n_normal": 2},
            {"fold": "foldB", "false_alarm_rate": 1.0, "n_normal": 1},
        ],
    }  # fmt: skip
    faults_only = _entry("no_fault_rates", [_row(status="CONFIRMED")])  # no normal row, no NO_FAULT
    assert (faults_only["false_alarm_rate"], faults_only["no_fault_recall"]) == (None, None)
    assert (faults_only["no_fault_precision"], faults_only["wrong_no_fault_rate"]) == (None, 0.0)
    baseline = _entry("no_fault_rates", [replace(r, has_verdict=False) for r in rows])  # no verdicts
    rates = ("false_alarm_rate", "wrong_no_fault_rate", "no_fault_precision", "no_fault_recall")
    assert [baseline[k] for k in rates] == [None] * 4
    assert (baseline["n_normal"], baseline["n_fault"]) == (3, 2)
    assert baseline["by_fold"] == [
        {"fold": "foldA", "false_alarm_rate": None, "n_normal": 2},
        {"fold": "foldB", "false_alarm_rate": None, "n_normal": 1},
    ]


def test_risk_coverage_orders_by_verified_and_fused_scores() -> None:
    rows = [
        _row(hit=True, status="CONFIRMED", margin=0.5, fused=0.3),
        _row(hit=False, status="LIKELY", margin=0.2, fused=0.8),
        _row(hit=True, status="INCONCLUSIVE", margin=0.9, fused=0.1),
        _row(truth=False, status="NO_FAULT", margin=1.0, fused=0.9),  # normal rows are not scored
    ]
    # V: hit, miss, hit -> risks 0, 1/2, 1/3; F (fused desc): miss, hit, hit -> 1, 1/2, 1/3
    assert _entry("risk_coverage", rows) == pytest.approx(
        {"aurc_verdict": 5 / 18, "aurc_fused": 11 / 18, "n_fault": 3}
    )
    failed = _entry("risk_coverage", [*rows, _row(hit=False)])  # no status, margin or fused: last
    assert failed["aurc_verdict"] == pytest.approx((0 + 1 / 2 + 1 / 3 + 2 / 4) / 4)
    assert _entry("risk_coverage", rows[3:]) == {"aurc_verdict": None, "aurc_fused": None, "n_fault": 0}
    baseline = [replace(r, has_verdict=False) for r in rows]
    assert _entry("risk_coverage", baseline) == {"aurc_verdict": None, "aurc_fused": None, "n_fault": 3}


def test_aurc_scores_ties_at_their_expectation() -> None:
    tied, last = (0.0, -0.5), (1.0, -0.5)
    # the tie block (one miss of two) counts 1/2 then 1 errors; the miss after it 2 of 3
    assert aurc([(tied, True), (tied, False), (last, True)]) == pytest.approx((0.5 + 0.5 + 2 / 3) / 3)
    swapped = [(tied, False), (tied, True), (last, True)]
    assert aurc(swapped) == aurc([(tied, True), (tied, False), (last, True)])  # order inside a tie is free
    assert aurc([]) is None


def test_selective_accuracy() -> None:
    rows = [
        _row(hit=True, status="CONFIRMED"),
        _row(hit=False, status="CONFIRMED"),
        _row(hit=True, status="LIKELY"),
        _row(hit=True, status="INCONCLUSIVE"),
        _row(truth=False, status="CONFIRMED"),  # a false alarm has no AC@1
    ]
    assert _entry("selective_accuracy", rows) == {
        "ac_at_1_confirmed": 0.5, "answer_rate_confirmed": 0.5,
        "ac_at_1_likely_or_better": 2 / 3, "answer_rate_likely_or_better": 0.75, "n_fault": 4,
    }  # fmt: skip
    unanswered = _entry("selective_accuracy", [_row(hit=True, status="INCONCLUSIVE")])
    assert (unanswered["ac_at_1_confirmed"], unanswered["answer_rate_confirmed"]) == (None, 0.0)
    baseline = _entry("selective_accuracy", [replace(r, has_verdict=False) for r in rows])
    assert baseline == dict.fromkeys(METRIC_KEYS["selective_accuracy"]) | {"n_fault": 4}


def test_decoy_top1_change_compares_each_case_and_seed_with_its_unplanted_run() -> None:
    rows = [
        _row(case="a", top="x"), _row(case="a", variant="plant-1", top="x"),  # unchanged
        _row(case="b", top="x"), _row(case="b", variant="plant-1", top="y"),  # changed
        _row(case="c", top="x"),  # no planted run: not a pair
        _row(case="d", top="x"), _row(case="d", variant="plant-1"),  # no ranks: changed
        _row(case="e", variant="plant-1", top="x"),  # no unplanted run: not a pair
        _row(case="a", seed=2, top="x"), _row(case="a", seed=2, variant="plant-1", top="y"),
        _row(case="a", variant="perm-1", top="z"),  # a permutation is not a planted proposal
    ]  # fmt: skip
    assert _entry("decoy_top1_change", rows) == {"decoy_top1_change": 0.75, "n_pairs": 4}
    assert _entry("decoy_top1_change", rows[:1]) == {"decoy_top1_change": None, "n_pairs": 0}


def test_permutation_invariance_needs_one_hash_across_every_permutation() -> None:
    rows = [
        _row(case="a", vhash=H1), _row(case="a", variant="perm-1", vhash=H1),
        _row(case="a", variant="perm-2", vhash=H1),  # invariant
        _row(case="b", vhash=H1), _row(case="b", variant="perm-1", vhash=H2),  # not
        _row(case="c"), _row(case="c", variant="perm-1"),  # no verdict: not invariant
        _row(case="d", vhash=H1),  # no permutation: not counted
        _row(case="e", vhash=H1), _row(case="e", variant="plant-1", vhash=H2),  # not a permutation
    ]  # fmt: skip
    assert _entry("permutation_invariance", rows) == {"permutation_invariance": 1 / 3, "n_cases": 3}
    assert _entry("permutation_invariance", []) == {"permutation_invariance": None, "n_cases": 0}


def test_entries_are_null_unless_listed_and_keep_the_flat_metrics() -> None:
    rows = [_row(hit=True, in_set=True, status="CONFIRMED", margin=0.4, fused=0.7)]
    got = entries(rows, ["mrr", *ROW_ENTRIES], alpha=0.1)
    assert sorted(got) == sorted(METRIC_KEYS)
    assert got["mrr"] == {"mrr": summarize(rows, ["mrr"])["mrr"]} and got["ac_at_k"] is None
    assert all(isinstance(got[name], dict) for name in ROW_ENTRIES)
    assert entries(rows, ["mrr"], alpha=0.1)["coverage"] is None


def test_scores_take_their_rows_columns_and_a_misaligned_row_is_refused() -> None:
    out = MethodOutput(
        ranks=("cart_cpu",), slate=("cart",), pool=("cart",), candidate_set=("cart",), has_verdict=True,
        margin=0.4, leader_fused_score=0.7,
    )  # fmt: skip
    score = score_case(Truth("cart"), out)
    assert (score.has_verdict, score.margin, score.leader_fused_score) == (True, 0.4, 0.7)
    row = score.columns() | {
        "case_id": "c1",
        "seed": 3,
        "variant": "perm-1",
        "fold": "foldA",
        "run_outcome": "ok",
    }
    row |= {"status": "CONFIRMED", "verdict_hash": H1}
    (keyed,) = with_rows([score], [row])
    assert (keyed.case_id, keyed.seed, keyed.variant, keyed.fold) == ("c1", 3, "perm-1", "foldA")
    assert (keyed.status, keyed.verdict_hash) == ("CONFIRMED", H1)
    with pytest.raises(ValueError, match="not its score's row"):
        with_rows([score], [row | {"hit_at_1": False}])
    with pytest.raises(ValueError, match="per_case rows"):
        with_rows([score, score], [row])
    with pytest.raises(ValueError, match="not its score's row"):
        with_rows([score], [row | {"run_outcome": "timeout"}])  # same columns, another run
    failed = score_case(Truth("cart"), replace(out, outcome="failed"))
    assert (failed.has_verdict, failed.margin, failed.leader_fused_score) == (True, None, None)
    # a run demoted to failed after writing its verdict keeps the row's status column, not here
    failed_row = failed.columns() | row | {"run_outcome": "failed", **failed.columns()}
    (demoted,) = with_rows([failed], [failed_row])
    assert (demoted.status, demoted.verdict_hash, demoted.fold) == (None, None, "foldA")
