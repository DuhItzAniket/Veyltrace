"""Unit and property tests of the 04 §7 case scoring, hand-computed (aggregation: test_summary.py, #64)."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench import metrics
from veyltrace_bench.metrics import AC_KS, OK, MethodOutput, Truth, score_case
from veyltrace_contracts.models import AnswerKeyRow, BenchResultRow
from veyltrace_core import io
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.rng import rng
from veyltrace_core.synth import layout as lay
from veyltrace_core.synth.truth import answer_key_rows

SERVICES = ("cart", "catalog", "checkout", "frontend", "payment", "recommend")
CHECKOUT = Truth("checkout", "cpu", "cpu", "resource")
CHANNELS = ("retrieval_hit", "pool_hit", "in_set")


def ranked(*services: str) -> MethodOutput:
    """A ranking-only (baseline-like) output with indicator cpu."""
    return MethodOutput(ranks=tuple(f"{s}_cpu" for s in services))


def test_coarse_and_fine_rankings_follow_rcaeval() -> None:
    """Coarse: -db folded, de-duplicated; fine: RCAEval indicator_ranks, raw and not de-duplicated."""
    ranks = ["carts-db_cpu", "carts_mem", "orders_latency-90_x", "carts_cpu", "user"]
    assert metrics.coarse_ranking(ranks) == ("carts", "orders", "user")
    fine = [("carts-db", "cpu"), ("carts", "mem"), ("orders", "latency-90"), ("carts", "cpu")]
    assert metrics.fine_ranking(ranks) == (*fine, ("user", "unknown"))
    for entries, expected in ((["carts-db_cpu", "orders_cpu"], None), (["o_cpu", "o_cpu", "carts_cpu"], 3)):
        assert metrics.position_of(metrics.fine_ranking(entries), ("carts", "cpu")) == expected


def test_hand_computed_pipeline_case_and_fault_types() -> None:
    ranks, slate = ("frontend_latency", "checkout_cpu", "cart_mem"), ("frontend", "checkout")
    out = MethodOutput(OK, ranks, ("nsigma",), slate, slate, ("frontend",), True, "delay", "code", 5)
    score = score_case(CHECKOUT, out, universe=SERVICES)
    assert (score.position, score.fine_position, score.unranked, score.n_candidates) == (2, 2, False, 6)
    assert (score.in_universe, score.slate_k) == (True, 5)  # summary.json inputs (#64)
    expected = dict.fromkeys(["hit_at_3", "hit_at_5", "retrieval_hit", "pool_hit"], True) | {"set_size": 1}
    expected |= {"onset_error_ms": None}  # oracle-style output: no onset passed (#215)
    assert score.columns() == expected | dict.fromkeys(["hit_at_1", "in_set", "fault_class_hit"], False) | {
        "ranks": list(ranks)
    }
    fault_types = [(None, "code", True), ("exception", "code", False), (None, "resource", None)]  # RE3: mode
    for fault_class, mode, hit in fault_types:
        assert score_case(Truth("checkout", None, fault_class, mode), out).fault_class_hit is hit
    assert score_case(Truth("checkout", mode="code"), ranked("checkout")).fault_class_hit is None  # baseline


def test_r00_slate_without_rankers_is_unranked() -> None:
    """The R-00 stub lists U A→Z; checkout is third, but that order is not a ranking."""
    ranks = tuple(f"{s}_unknown" for s in SERVICES)
    out = MethodOutput(OK, ranks, (), SERVICES[:5], SERVICES[:5], SERVICES, True, "cpu", "resource", 5)
    score = score_case(CHECKOUT, out, universe=SERVICES)
    assert score.unranked and score.ranks == () and score.set_size is None  # the set is not scored
    assert [score.hit_at(k) for k in AC_KS] == [False] * 5
    assert (score.retrieval_hit, score.pool_hit, score.in_set, score.fault_class_hit) == (False,) * 4


@pytest.mark.parametrize("outcome", sorted(metrics.RUN_OUTCOMES - {OK}))
def test_non_ok_outcomes_are_misses(outcome: str) -> None:
    root = ("checkout",)
    score = score_case(CHECKOUT, MethodOutput(outcome, ("checkout_cpu",), ("ns",), root, root, root, True))
    misses = dict.fromkeys(["hit_at_1", "hit_at_3", "hit_at_5", *CHANNELS], False)
    nulls = {"ranks": [], "set_size": None, "fault_class_hit": False, "onset_error_ms": None}
    assert score.columns() == nulls | misses


def test_baseline_and_normal_window_columns_are_null() -> None:
    baseline = score_case(CHECKOUT, ranked("checkout"))
    assert (baseline.retrieval_hit, baseline.pool_hit, baseline.in_set, baseline.set_size) == (None,) * 4
    assert baseline.fault_class_hit is None and baseline.hit_at(1) is True
    normal = score_case(Truth(None), MethodOutput(ranks=("checkout_cpu",), slate=("checkout",)))
    assert normal.columns()["hit_at_1"] is None and normal.retrieval_hit is None
    with pytest.raises(ValueError, match="run outcome"):
        score_case(CHECKOUT, MethodOutput(outcome="crashed"))


def test_answer_keys_map_to_truth_and_fit_the_bench_result_contract(tmp_path: Path) -> None:
    truths = {r["case_id"]: Truth.from_answer_key(AnswerKeyRow.model_validate(r)) for r in answer_key_rows()}
    injected = lay.T_INJECT_NS  # the onset-error reference (#215)
    assert truths["59e0d31bcc42"] == replace(CHECKOUT, t_inject_ns=injected)  # synth-01
    assert truths["3263e227fcbe"] == Truth(None)  # synth-05, no fault: no injection time either
    assert truths["9dfa7a46d130"] == Truth("cart", t_inject_ns=injected)  # synth-05@silent: root only
    with pytest.raises(ContractValidationError, match="no root_service"):
        Truth.from_answer_key(AnswerKeyRow.model_validate({**answer_key_rows()[0], "root_service": None}))
    score = score_case(truths["9dfa7a46d130"], ranked("catalog", "cart"))
    assert score.fine_hit_at(1) is None  # no indicator: outside the fine-grained metric
    row: dict[str, object] = {c: None for c in BenchResultRow.model_fields}  # other columns null
    row |= {"case_id": "59e0d31bcc42", "dataset": "synth", "system": "other", "method": "rcaeval:baro"}
    row |= {"protocol": "oracle", "run_outcome": score.outcome, "shift_s": 0, "sources_dropped": []}
    io.write_path("bench_result", [row | score.columns()], tmp_path / "per_case.csv")
    table = io.read_path("bench_result", tmp_path / "per_case.csv")
    assert isinstance(table, pa.Table)
    assert {k: table.to_pylist()[0][k] for k in score.columns()} == score.columns()


def test_chance_formula_matches_a_seeded_simulation() -> None:
    draws = 4000
    for n in (1, 2, 5, 6, 11):
        keys = rng("59e0d31bcc42", f"bench.test.chance/{n}").random((draws, n))  # sort keys: a uniform order
        positions = (keys < keys[:, :1]).sum(axis=1)  # 0-based position of the root (item 0)
        for k, p in ((k, metrics.chance_at(k, n)) for k in AC_KS):
            assert abs(float(np.mean(positions < k)) - p) <= 4 * math.sqrt(p * (1 - p) / draws) + 1e-12
    assert metrics.chance_at(3, 0) == 0.0  # an empty universe (RCAEval)
    for k, n in ((0, 3), (1, -1)):
        with pytest.raises(ValueError, match="chance_at"):
            metrics.chance_at(k, n)


names = st.sampled_from([*SERVICES, "carts-db", "ghost"])
rank_lists = st.lists(st.tuples(names, st.sampled_from(["cpu", "mem", "latency"])).map("_".join), max_size=8)
lists = st.none() | st.lists(names, max_size=5).map(tuple)
outputs = st.builds(
    MethodOutput,
    st.sampled_from(sorted(metrics.RUN_OUTCOMES)),
    rank_lists.map(tuple),
    st.sampled_from([None, (), ("nsigma",)]),
    *(lists,) * 3,
    st.booleans(),
)
truths = st.builds(Truth, st.none() | names, st.none() | st.just("cpu"), st.none() | st.just("cpu"))


@given(truths, outputs, lists)
def test_hits_are_monotone_in_k_and_null_without_truth(
    truth: Truth, out: MethodOutput, universe: tuple[str, ...] | None
) -> None:
    s = score_case(truth, out, universe=universe)
    hits = [bool(s.hit_at(k)) for k in AC_KS]
    assert hits == sorted(hits) and (s.has_truth or all(s.hit_at(k) is None for k in AC_KS))


@given(truths, outputs)
def test_an_unranked_slate_scores_nothing_whatever_it_ranks(truth: Truth, out: MethodOutput) -> None:
    """rankers_active == []: every hit is a miss (null without truth), however good the order is."""
    fields = (out.ranks, (), out.slate, out.pool, out.candidate_set, out.has_verdict, "cpu", "code")
    score = score_case(truth, MethodOutput(OK, *fields))
    assert score.unranked and score.ranks == () and score.set_size is None
    hits = [score.hit_at(k) for k in AC_KS] + [score.fine_hit_at(1), score.fault_class_hit]
    assert not any([*hits, *(getattr(score, c) for c in CHANNELS)])
