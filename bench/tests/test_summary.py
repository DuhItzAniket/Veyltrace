"""Unit and property tests of the summary.json aggregation (04 §7, §9), hand-computed."""

from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench.metrics import AC_KS, OK, RUN_OUTCOMES, MethodOutput, Truth, score_case
from veyltrace_bench.summary import METRIC_KEYS, summarize

SERVICES = ("cart", "catalog", "checkout", "frontend", "payment", "recommend")
CHECKOUT = Truth("checkout", "cpu", "cpu", "resource")


def ranked(*services: str) -> MethodOutput:
    """A ranking-only (baseline-like) output with indicator cpu."""
    return MethodOutput(ranks=tuple(f"{s}_cpu" for s in services))


def test_r00_unranked_slate_is_a_miss_in_every_rate() -> None:
    """The R-00 stub's slate (rankers_active == []) counts in n_unranked and misses; n_i still counts."""
    ranks = tuple(f"{s}_unknown" for s in SERVICES)
    out = MethodOutput(OK, ranks, (), SERVICES[:5], SERVICES[:5], SERVICES, True, "cpu", "resource", 5)
    summary = summarize([score_case(CHECKOUT, out, universe=SERVICES)])
    assert (summary["n_unranked"], summary["ac_at_5"], summary["retrieval_at_k"]) == (1, 0.0, 0.0)
    assert (summary["chance_at_1"], summary["retrieval_k"]) == (1 / 6, [5])


@pytest.mark.parametrize("outcome", sorted(RUN_OUTCOMES - {OK}))
def test_non_ok_outcomes_are_counted(outcome: str) -> None:
    root = ("checkout",)
    score = score_case(CHECKOUT, MethodOutput(outcome, ("checkout_cpu",), ("ns",), root, root, root, True))
    assert summarize([score])["outcomes"] == {outcome: 1}


def test_normal_windows_and_absent_channels_stay_out_of_the_rates() -> None:
    baseline = score_case(CHECKOUT, ranked("checkout"))
    normal = score_case(Truth(None), MethodOutput(ranks=("checkout_cpu",), slate=("checkout",)))
    summary = summarize([normal, baseline])
    assert (summary["n_fault"], summary["n_no_truth"], summary["ac_at_1"]) == (1, 1, 1.0)
    assert summary["retrieval_at_k"] is summary["pool_retrieval"] is summary["rerank_at_1"] is None
    no_indicator = score_case(Truth("cart"), ranked("catalog", "cart"))  # synth-05@silent (test_metrics)
    assert summarize([no_indicator])["n_fine"] == 0


def test_summary_hand_computed() -> None:
    four = ("cart", "catalog", "payment", "checkout")
    scores = [
        score_case(CHECKOUT, ranked("checkout"), universe=SERVICES),  # position 1
        score_case(CHECKOUT, ranked("cart", "checkout"), universe=SERVICES),  # position 2
        score_case(CHECKOUT, ranked(*four), universe=four),  # position 4, n = 4
        score_case(CHECKOUT, ranked("cart"), universe=("cart", "catalog")),  # root not in universe: chance 0
        score_case(CHECKOUT, MethodOutput(outcome="failed"), universe=SERVICES),  # a miss, n still known
        score_case(Truth(None), ranked("checkout"), universe=SERVICES),  # normal window: excluded
    ]
    summary = summarize(scores)
    assert summary["outcomes"] == {"failed": 1, "ok": 5}
    counts = ("n_rows", "n_fault", "n_no_truth", "n_chance", "n_outside_services")
    assert tuple(summary[c] for c in counts) == (6, 5, 1, 5, 1)
    assert [summary[f"ac_at_{k}"] for k in AC_KS] == [0.2, 0.4, 0.4, 0.6, 0.6]
    expected = {"avg_at_5": 11 / 25, "mrr": 1.75 / 5, "chance_at_1": 0.75 / 5, "chance_at_5": 3.5 / 5}
    expected |= {"lift_at_1": 0.2 / 0.15, "chance_diff_at_1": 0.2 - 0.15, "fine_ac_at_1": 0.2}
    assert {key: summary[key] for key in expected} == pytest.approx(expected)
    unknown_n = summarize([*scores, score_case(CHECKOUT, MethodOutput(outcome="rejected"))])
    assert (unknown_n["n_chance"], unknown_n["chance_at_1"], unknown_n["lift_at_1"]) == (5, None, None)
    only = summarize(scores, ["mrr"])
    assert "mrr" in only and "ac_at_1" not in only and only["n_fault"] == 5  # counts always written


names = st.sampled_from([*SERVICES, "carts-db", "ghost"])
rank_lists = st.lists(st.tuples(names, st.sampled_from(["cpu", "mem", "latency"])).map("_".join), max_size=8)
lists = st.none() | st.lists(names, max_size=5).map(tuple)
outputs = st.builds(
    MethodOutput,
    st.sampled_from(sorted(RUN_OUTCOMES)),
    rank_lists.map(tuple),
    st.sampled_from([None, (), ("nsigma",)]),
    *(lists,) * 3,
    st.booleans(),
)
truths = st.builds(Truth, st.none() | names, st.none() | st.just("cpu"), st.none() | st.just("cpu"))


def rate(summary: dict[str, object], key: str) -> float | None:
    value = summary[key]
    assert value is None or isinstance(value, float), key
    return value


@given(st.lists(st.tuples(truths, outputs, lists), max_size=12), st.randoms(use_true_random=False))
def test_metrics_are_bounded_monotone_consistent_and_order_free(
    data: list[tuple[Truth, MethodOutput, tuple[str, ...] | None]], shuffler: random.Random
) -> None:
    scores = [score_case(t, o, universe=u) for t, o, u in data]
    for s in scores:
        hits = [bool(s.hit_at(k)) for k in AC_KS]
        assert hits == sorted(hits) and (s.has_truth or all(s.hit_at(k) is None for k in AC_KS))
    summary = summarize(scores)
    keys = [key for name in ("ac_at_k", "fine_ac_at_k", "chance") for key in METRIC_KEYS[name]]
    values = [rate(summary, key) for key in [*keys, "avg_at_5", "mrr", "retrieval_at_k", "pool_retrieval"]]
    assert all(0.0 <= v <= 1.0 for v in values if v is not None)
    for metric in ("ac", "chance"):  # monotone in k
        curve = [rate(summary, f"{metric}_at_{k}") or 0.0 for k in AC_KS]
        assert curve == sorted(curve)
    if per_case := [sum(bool(s.hit_at(k)) for k in AC_KS) / len(AC_KS) for s in scores if s.has_truth]:
        assert rate(summary, "avg_at_5") == pytest.approx(sum(per_case) / len(per_case))
    shuffler.shuffle(scores)
    assert summarize(scores) == summary
