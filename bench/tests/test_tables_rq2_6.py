"""RQ2–RQ6 tables (R-17d, #380): Tables 6, 6c, 6d, 7, 8, A1, 9 and the RQ4 grids 10–12, from
hand-made 1.1 fixtures and the committed experiment YAMLs.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import generate
from veyltrace_core import io, textio

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
NO_ENTRY = "bench_summary 1.1 has no `{}` entry (03 §13.3); it needs a contract change"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


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


def test_the_1_2_entries_render_with_their_reasons(files: dict[str, str], results: Path) -> None:
    t7 = files["tables/t07-rq3-calibration.md"]
    assert "re2-oracle-rq3-v1" in t7 and "re2-oracle-loso-v1" in t7 and "re2-to-nezha-transfer-v1" in t7
    row = next(
        line
        for line in t7.splitlines()
        if line.startswith("| re2-oracle-rq3-v1 | crossfit2 (rcaeval-re2) | 0.1 | ob | veyltrace:off |")
    )
    assert (
        "| 0.875 | -0.025 | 1.000 | 1.500 | 0.500 | 0.250 | 0.375 | 0.250 | 0.000 |" in row
    )  # coverage … wrong NO_FAULT
    assert "no committed results in bench/results" in t7  # loso did not run: its own reason wins
    assert "alpha 0.1 (each experiment's calibration.alpha" in t7 and NO_ENTRY.format("coverage") not in t7
    arms = files["tables/t06d-rq2-proposal-arms.md"]
    h2c = "| re2-oracle-permute-v1 | ob | veyltrace:brief | permutation_invariance | "
    h2c += "0.875 [0.473, 0.997]<sup>1</sup> | 8 |"
    assert h2c in arms
    assert (
        "| re2-oracle-planted-v1 | ob | agent-only:brief | decoy_top1_change | not run<sup>" in arms
    )  # no results
    path = results / "re2-oracle-permute-v1" / "summary.json"  # the same file as written by bench 1.1
    doc = json.loads(textio.read_text(path))
    doc["schema_version"] = "1.1.0"
    for group in doc["groups"]:
        for entry in ("coverage", "set_size", "no_fault_rates", "risk_coverage", "selective_accuracy",
                      "decoy_top1_change", "permutation_invariance"):  # fmt: skip
            del group["metrics"][entry]
    textio.write_text(path, json.dumps(doc))
    again = generate.outputs(results, EXPERIMENTS)["tables/t06d-rq2-proposal-arms.md"].decode()
    assert "summary.json is bench_summary 1.1, which has no `permutation_invariance` entry (re-run)" in again


def test_a_run_experiment_shows_the_gap_for_a_listed_metric(files: dict[str, str]) -> None:
    ablation = files["tables/t11-rq4-ablation.md"]  # point "none" is re2-oracle-rq1-v1, which ran
    assert "| none | all | ob | veyltrace:off | 0.500 [0.375, 0.625] |" in ablation
    assert "the experiment does not list the metric `selective_accuracy`" in ablation  # rq1 does not list it
    assert "| AC@1 among CONFIRMED | Answer rate CONFIRMED | AC@1 among CONFIRMED or LIKELY |" in ablation


def test_the_brief_shift_point_at_0_s_is_computed_on_the_subset(files: dict[str, str]) -> None:
    shift = files["tables/t10-rq4-shift.md"]
    computed = "| 0 s | computed from per_case.csv, 90-case subset |"
    ob = next(line for line in shift.splitlines() if line.startswith(f"{computed} ob | veyltrace:brief |"))
    assert (
        "| 0.500<sup>" in ob and "| 1.000<sup>" in ob and "| 6 | 0 | 6/0/0/0/0 |" in ob
    )  # 2 cases × 3 seeds
    assert ob.endswith("| re2-oracle-rq2-v1 @ fixture (computed from per_case.csv, 90-case subset) |")
    ss = next(line for line in shift.splitlines() if line.startswith(f"{computed} ss | veyltrace:brief |"))
    assert ss.startswith(f"{computed} ss | veyltrace:brief | 1.000<sup>")
    assert f"{computed} tt | veyltrace:brief | not run<sup>" in shift  # no rq2 rows on tt
    assert "no interval: computed from per_case.csv, 90-case subset" in shift
    zero_off = [
        line for line in shift.splitlines() if line.startswith("| 0 s |") and "| ob | veyltrace:off |" in line
    ]
    assert len(zero_off) == 1 and "re2-oracle-rq1-v1 @ fixture" in zero_off[0]  # one x = 0, from rq1
    assert "| -60 s | 90-case subset (bench/re2_investigate_cases.yaml) | ob | veyltrace:brief |" in shift


def test_without_subset_rows_the_point_is_not_run(results: Path) -> None:
    path = results / "re2-oracle-rq2-v1" / "per_case.csv"
    header = textio.read_text(path).splitlines()[0]
    textio.write_text(path, header + "\n")
    shift = generate.outputs(results, EXPERIMENTS)["tables/t10-rq4-shift.md"].decode()
    assert "its per_case.csv has no veyltrace:brief rows for the 90-case subset's case ids and seeds" in shift
    computed = "| 0 s | computed from per_case.csv, 90-case subset | ob |"
    assert (
        f"{computed} veyltrace:brief | not run<sup>" in shift and f"{computed} prior-only | n/a<sup>" in shift
    )
    zero = [
        line
        for line in shift.splitlines()
        if line.startswith("| 0 s |") and "| ob | prior-only | 0.250" in line
    ]
    assert len(zero) == 1  # no second x = 0 floor block from rq2 (verification of H1)


def test_the_rq4_grids_take_their_coordinates_and_floors_from_the_specs(files: dict[str, str]) -> None:
    shift = files["tables/t10-rq4-shift.md"]
    points = [
        line.split(" | ")[0][2:]
        for line in shift.splitlines()
        if line.startswith("| ") and " s |" in line[:12]
    ]
    order = ["-120 s", "-60 s", "-30 s", "0 s", "+30 s", "+60 s", "+120 s"]
    assert sorted(set(points), key=lambda p: int(p.split()[0])) == order
    assert "| 0 s | all | ob | veyltrace:off | 0.500 [0.375, 0.625] |" in shift
    assert (
        "| -60 s | all | ob | prior-only | 0.250<sup>" in shift
    )  # prior-only reads no telemetry: same cases
    decoys = files["tables/t12-rq4-rcaevalc.md"]
    assert "| pi=0, rate=0/h | all | ob | veyltrace:off |" in decoys and "| pi=0.5, rate=2/h |" in decoys
    assert (
        "| pi=0, rate=0/h | 90-case subset (bench/re2_investigate_cases.yaml) | ob | veyltrace:brief |"
        in decoys
    )
    assert "not applicable: different case set" in decoys  # floors of the AI cells
    borrowed = "rcaeval:baro (from re2-oracle-rq1-v1 (baselines ignore events))"
    assert f"| pi=0, rate=0/h | all | ob | {borrowed} | 0.375 [0.250, 0.500] |" in decoys  # rq1's floor
    ai = "| pi=0, rate=0/h | 90-case subset (bench/re2_investigate_cases.yaml) | ob | rcaeval:baro | n/a<sup>"
    assert ai in decoys  # the AI cells are on the subset: no borrowed floor
    ablation = files["tables/t11-rq4-ablation.md"]
    assert (
        "not run under this protocol (the experiment omits this floor)" in ablation
    )  # drop metrics: no N-Sigma
    assert "| Lift@1 | AC@1 − Chance@1 |" in shift and "| Lift@1 | AC@1 − Chance@1 |" in decoys
    assert "drop events" in files["tables/t11-rq4-ablation.md"]


def test_table_6_shows_its_floors_and_seeded_arms(files: dict[str, str]) -> None:
    t6 = files["tables/t06-rq2-re2-oracle-rq2-v1.md"]
    assert "| Fault-case runs (cases × seeds) |" in t6
    assert "| ob | rcaeval:baro | 0.375 [0.250, 0.500] |" in t6 and "re2-oracle-rq1-v1 @ fixture |" in t6
    assert "| ob | prior-only | 0.250<sup>" in t6
    assert "not run: bench_summary 1.1 has no per-seed groups" in t6
    investigate = files["tables/t06-rq2-re2-oracle-investigate-v1.md"]
    assert "| ob | rcaeval:baro | n/a<sup>" in investigate and "different case set" in investigate
    comparisons = files["tables/t06c-rq2-comparisons.md"]
    superiority = "| veyltrace:brief − veyltrace:off | superiority (rq2) | none | 0.125 [0.000, 0.250] |"
    assert f"{superiority} 8 | 4 | 0.2500 | n/a<sup>" in comparisons
    assert "per-case hit is a mean over seeds, not boolean, so no McNemar" in comparisons


def test_cost_and_replay(files: dict[str, str]) -> None:
    cost = files["tables/t08-rq5-cost.md"]
    assert "| Peak RSS p50 (MiB) |" in cost
    assert "| re2-oracle-rq1-v1 | ob | veyltrace:off | 25000 | 31000 | 1500 | 1600 | n/a<sup>" in cost
    replay = files["tables/t09-rq6-replay.md"]
    assert (
        "| Tier 1, CI | not run<sup>3</sup> | not run<sup>3</sup> |" in replay
        and "replay/ci (not run) |" in replay
    )
    assert "- replay/ci: not run: no committed result (veyltrace bench replay --role ci)" in replay


def test_replay_reads_the_committed_replay_summaries(results: Path) -> None:
    """Table 9 from bench/results/replay/<role>/ (03 §13.5-§13.6, #440): rate, exact interval, counts."""
    examples = BENCH.parent / "contracts" / "examples"
    out = results / "replay" / "recording"
    out.mkdir(parents=True)
    rows = json.loads(textio.read_text(examples / "bench_replay.example.json"))
    io.write_path("bench_replay", rows, out / "replay.csv")
    io.write_path(
        "bench_replay_summary",
        json.loads(textio.read_text(examples / "bench_replay_summary.example.json")),
        out / "replay_summary.json",
    )
    table = generate.outputs(results, EXPERIMENTS)["tables/t09-rq6-replay.md"].decode()
    row = "| Tier 1, recording laptop | 0.500 [0.013, 0.987] | 1/2 | 2/2 | 0: 1, 5: 1 |"
    row += " replay/recording @ a35144c4 |"
    assert row in table
    assert "| Tier 2 regeneration, 50 recorded cases | 1.000 [0.025, 1.000] | 1/1 | 1/1 | — |" in table
    assert "| Tier 1, second laptop | not run<sup>" in table
    assert "- replay/recording: commit a35144c4f0e1d2c3b4a5968778695a4b3c2d1e0f; sha256 replay.csv " in table
    assert "protocol: recording: Windows-11-10.0.26100-SP0, Python 3.12.7, host 1a2b3c4d5e6f" in table
