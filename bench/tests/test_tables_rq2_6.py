"""RQ2–RQ6 tables (R-17d, #380): Tables 6, 6c, 6d, 7, 8, A1, 9 and the RQ4 grids 10–12, from
hand-made 1.1 fixtures and the committed experiment YAMLs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import generate

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
NO_ENTRY = "bench_summary 1.1 has no `{}` entry (03 §13.3); it needs a contract change"


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("rq26") / "results"
    shutil.copytree(FIXTURES / "results", root)
    return {k: v.decode() for k, v in generate.outputs(root, EXPERIMENTS).items() if k.endswith(".md")}


def test_every_rq2_to_rq6_table_is_generated(files: dict[str, str]) -> None:
    expected = {
        "t06-rq2-re2-oracle-rq2-v1", "t06-rq2-re2-detected-rq2-v1", "t06-rq2-re3-oracle-rq2-v1",
        "t06-rq2-nezha-oracle-brief-v1", "t06-rq2-re2-oracle-investigate-v1", "t06-rq2-veyllab-oracle-rq2-v1",
        "t06c-rq2-comparisons", "t06d-rq2-proposal-arms", "t07-rq3-calibration", "t08-rq5-cost",
        "a1-cost-all", "t09-rq6-replay", "t10-rq4-shift", "t11-rq4-ablation", "t12-rq4-rcaevalc",
    }  # fmt: skip
    assert expected <= {Path(k).stem for k in files}


def test_metrics_without_a_summary_entry_say_so(files: dict[str, str]) -> None:
    t7 = files["tables/t07-rq3-calibration.md"]
    assert "re2-oracle-rq3-v1" in t7 and "re2-oracle-loso-v1" in t7 and "re2-to-nezha-transfer-v1" in t7
    arms = files["tables/t06d-rq2-proposal-arms.md"]
    assert "| re2-oracle-planted-v1 | agent-only:brief | decoy_top1_change | not run<sup>" in arms
    assert "| re2-oracle-permute-v1 | veyltrace:brief | permutation_invariance | not run<sup>" in arms
    # every experiment here is missing from the fixtures, so its own reason wins over the gap
    assert NO_ENTRY.format("coverage") not in t7 and "no committed results in bench/results" in t7


def test_a_run_experiment_shows_the_gap_for_a_listed_metric(files: dict[str, str]) -> None:
    ablation = files["tables/t11-rq4-ablation.md"]  # point "none" is re2-oracle-rq1-v1, which ran
    assert "| none | ob | veyltrace:off | 0.500 [0.375, 0.625] |" in ablation
    assert "the experiment does not list the metric `selective_accuracy`" in ablation  # rq1 does not list it


def test_the_rq4_grids_take_their_coordinates_from_the_yamls(files: dict[str, str]) -> None:
    shift = files["tables/t10-rq4-shift.md"]
    points = [
        line.split(" | ")[0][2:]
        for line in shift.splitlines()
        if line.startswith("| ") and " s |" in line[:12]
    ]
    assert sorted(set(points), key=lambda p: int(p.split()[0])) == [
        "-120 s",
        "-60 s",
        "-30 s",
        "0 s",
        "+30 s",
        "+60 s",
        "+120 s",
    ]
    assert "| 0 s | ob | veyltrace:off | 0.500 [0.375, 0.625] |" in shift
    decoys = files["tables/t12-rq4-rcaevalc.md"]
    assert "| pi=0, rate=0/h | ob | veyltrace:off |" in decoys and "| pi=0.5, rate=2/h |" in decoys
    assert "drop events" in files["tables/t11-rq4-ablation.md"]


def test_cost_and_replay(files: dict[str, str]) -> None:
    cost = files["tables/t08-rq5-cost.md"]
    assert "| re2-oracle-rq1-v1 | ob | veyltrace:off | 25000 | 31000 | 1500 | 1600 | n/a<sup>" in cost
    replay = files["tables/t09-rq6-replay.md"]
    assert "| Tier 1, CI | not run<sup>1</sup> | not run<sup>1</sup> | no bench experiment |" in replay
    assert "none: every row has no bench experiment" in replay
