"""The cost metric of summary.json (03 §13.3, CCR #316): nearest-rank p50/p95 of the cost columns."""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench.metrics import CaseScore, MethodOutput, Truth, score_case
from veyltrace_bench.summary import METRIC_KEYS, nearest_rank, summarize
from veyltrace_core import io
from veyltrace_core.errors import ContractValidationError

REPO = Path(__file__).resolve().parents[2]
CHECKOUT = Truth("checkout", "cpu", "cpu", "resource")
R05_SUMMARY = REPO / "bench" / "results" / "re2-oracle-baselines-r05" / "summary.json"
COST_KEYS = METRIC_KEYS["cost"]


def _rows(walls: list[float | None], rss: list[float | None]) -> list[CaseScore]:
    base = score_case(CHECKOUT, MethodOutput(ranks=("checkout_cpu",)))
    return [replace(base, wall_ms=w, peak_rss_mb=r) for w, r in zip(walls, rss, strict=True)]


def test_nearest_rank_is_the_ceil_rank_value() -> None:
    values = [15.0, 20.0, 35.0, 40.0, 50.0]  # the textbook nearest-rank example
    assert (nearest_rank(values, 50), nearest_rank(values, 95)) == (35.0, 50.0)
    assert nearest_rank([7.0], 50) == nearest_rank([7.0], 95) == 7.0
    assert nearest_rank(list(map(float, range(1, 21))), 95) == 19.0  # ceil(0.95 * 20) = 19
    assert nearest_rank([], 50) is None


def test_cost_on_a_handmade_group() -> None:
    rows = _rows([400.0, 100.0, 300.0, 200.0, None], [900.0, None, 700.0, 800.0, None])  # None: killed run
    cost = {k: v for k, v in summarize(rows, ["cost"]).items() if k in COST_KEYS}
    assert cost == {
        "n_cost": 4,
        "wall_ms_p50": 200.0,  # ceil(0.5 * 4) = 2nd of 100, 200, 300, 400
        "wall_ms_p95": 400.0,
        "peak_rss_mb_p50": 800.0,  # ceil(0.5 * 3) = 2nd of 700, 800, 900
        "peak_rss_mb_p95": 900.0,
        "tokens_in_p50": None,  # AI off: no row has tokens
        "tokens_in_p95": None,
        "tokens_out_p50": None,
        "tokens_out_p95": None,
    }


def test_cost_is_all_null_when_no_row_has_a_value() -> None:
    summary = summarize(_rows([None, None], [None, None]), ["cost"])
    assert summary["n_cost"] == 0
    assert all(summary[k] is None for k in COST_KEYS if k != "n_cost")
    assert not set(COST_KEYS) & set(summarize(_rows([1.0], [1.0]), ["mrr"]))  # unlisted: not computed


PAIRS = st.lists(st.tuples(st.floats(0, 1e6), st.none() | st.floats(0, 1e5)), min_size=1, max_size=30)


@given(PAIRS, st.randoms())
def test_cost_never_depends_on_row_order(pairs: list[tuple[float, float | None]], rnd: random.Random) -> None:
    rows = _rows([w for w, _ in pairs], [r for _, r in pairs])
    shuffled = list(rows)
    rnd.shuffle(shuffled)
    assert summarize(rows, ["cost"]) == summarize(shuffled, ["cost"])


def test_committed_r05_results_are_a_0x_record_that_1_0_refuses() -> None:
    """R-05's summary.json and manifest.json stay as written (bench_summary/bench_manifest 0.1.0):
    ADR 20261116-ak-contracts-1-0-freeze, "0.x artifacts are unreadable by 1.0" (another major).
    No table reads them; R-11's re2-oracle-rq1-v1 re-runs the same baselines under 1.0 (#332)."""
    for name, path in (
        ("bench_summary", R05_SUMMARY),
        ("bench_manifest", R05_SUMMARY.with_name("manifest.json")),
    ):
        with pytest.raises(ContractValidationError, match=r"schema version '0\.1\.0' is not readable by"):
            io.read_path(name, path, validate=True)
