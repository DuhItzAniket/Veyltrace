"""`veyltrace bench tables` and the RQ1 tables (R-17c, #379): Table 3 datasets, Table 5 per
benchmark and protocol with the floors, and the H1 comparisons, from hand-made 1.1 fixtures.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from veyltrace_bench import cli as bench_cli
from veyltrace_bench.tables import generate
from veyltrace_core import textio

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
T5 = "tables/t05-rq1-re2-oracle.md"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


@pytest.fixture
def files(results: Path) -> dict[str, str]:
    return {k: v.decode() for k, v in generate.outputs(results, EXPERIMENTS).items() if k.endswith(".md")}


def _row(text: str, *starts: str) -> str:
    """The one Markdown row starting with `| a | b |`."""
    prefix = "| " + " | ".join(starts) + " |"
    found = [line for line in text.splitlines() if line.startswith(prefix)]
    assert len(found) == 1, (prefix, found)
    return found[0]


def test_table_5_re2_oracle_matches_its_golden_file(files: dict[str, str]) -> None:
    assert files[T5] == textio.read_text(FIXTURES / "expected" / "t05-rq1-re2-oracle.md")


def test_table_5_shows_each_system_next_to_its_floors(files: dict[str, str]) -> None:
    t5 = files[T5]
    header = next(line for line in t5.splitlines() if line.startswith("| System |"))
    assert "| Lift@1 | AC@1 − Chance@1 | Per-seed AC@1 (mean ± SD) | Fault cases | Unranked |" in header
    assert _row(t5, "ob", "chance").startswith("| ob | chance | 0.125<sup>")  # no interval: not a case mean
    assert "| n/a<sup>" in _row(t5, "ob", "chance")  # Avg@5 … Rerank@1 do not apply to the floor
    assert _row(t5, "ob", "prior-only").startswith("| ob | prior-only | 0.250<sup>")  # its statistics are off
    off = _row(t5, "ob", "veyltrace:off")
    assert off.startswith("| ob | veyltrace:off | 0.500 [0.375, 0.625] |") and "| 0.875 (K=5)<sup>" in off
    assert "| 4.000 | 0.375<sup>" in off  # Lift@1 = 0.5 / 0.125; AC@1 − Chance@1 without an interval
    assert off.endswith(
        "| 8 | 0 | 8/0/0/0/0 | re2-oracle-rq1-v1 @ fixture |"
    )  # fault cases, unranked, outcomes
    assert "not applicable: deterministic method: one run per case" in t5
    order = [line.split(" | ")[1] for line in t5.splitlines() if line.startswith("| ob |")]
    assert order[:5] == ["chance", "prior-only", "rcaeval:baro", "rcaeval:nsigma", "simplerca"]  # YAML order
    assert order[-2:] == ["causatrix:rrf", "veyltrace:off"]
    assert "| tt | veyltrace:off | not run<sup>" in t5  # no re2-tt group in the fixture
    assert "| pooled | veyltrace:off | not run<sup>" in t5
    assert "re2 pooled intervals waits for the system-stratified cluster bootstrap" in t5
    assert "Protocol: re2-ob, re2-ss, re2-tt (all cases, excluding bench/dev_cases.yaml); oracle alert;" in t5


def test_not_run_experiments_render_whole_tables(files: dict[str, str]) -> None:
    detected = files["tables/t05-rq1-re2-detected.md"]
    assert "results from a dirty work tree are never used" in detected
    assert "| ob | veyltrace:off | not run<sup>" in detected
    assert "| ob | prior-only | 0.250<sup>" in detected  # prior-only reads no alert: the same floor
    fse = files["tables/t05-rq1-fse26-oracle.md"]
    assert "stretch dataset not verified" in fse and "fse26-oracle-rq1-v1 (not run)" in fse


def test_table_3_takes_normal_windows_from_the_experiment_that_adds_them(files: dict[str, str]) -> None:
    t3 = files["tables/t03-datasets.md"]
    assert _row(t3, "re2-ob", "ob").startswith(
        "| re2-ob | ob | 8 | 1 | 0 | 8 | 4 normal windows (from re2-oracle-rq3-v1) |"
    )
    assert "| re3-ob | ob | not run<sup>" in t3 and "no experiment adds them for this benchmark" in t3
    assert "- re2-oracle-rq3-v1: commit fixture" in t3  # the second source is listed too
    assert "| veyllab-ob | ob | not run<sup>" in t3


def test_the_comparisons(files: dict[str, str], results: Path) -> None:
    comparisons = files["tables/t05c-rq1-comparisons.md"]
    assert "| Sign-flip p (unadjusted) |" in comparisons
    row = _row(comparisons, "re2-ob ob", "ac_at_1", "veyltrace:off − rcaeval:baro", "superiority (rq1)")
    assert "| 0.125 [-0.125, 0.375] | 8 | 4 | 0.5000 | 2/1 | 1.0000 | <0.001 |" in row
    noninferiority = _row(
        comparisons, "re2-ob ob", "ac_at_1", "veyltrace:off − rcaeval:baro", "noninferiority"
    )
    assert "| 0.000 | 0.125 [-0.125, 0.375] | 8 | 4 | n/a<sup>" in noninferiority  # decided by the CI
    assert "no Holm family" in comparisons
    path = results / "re2-oracle-rq1-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    doc["statistics"]["comparisons"][0].update(low=None, high=None)
    textio.write_text(path, json.dumps(doc))
    again = generate.outputs(results, EXPERIMENTS)["tables/t05c-rq1-comparisons.md"].decode()
    assert "| 0.000 | 0.125<sup>" in again and "no interval in summary.json" in again


def test_cli_writes_then_checks(results: Path) -> None:
    argv = ["tables", "--results", str(results), "--experiments", str(EXPERIMENTS)]
    assert bench_cli.main([*argv, "--check"]) == bench_cli.CHECK_DIFFERS == 2  # nothing written yet
    assert bench_cli.main(argv) == 0
    assert bench_cli.main([*argv, "--check"]) == 0
    textio.write_text(results / T5, "hand edit\n")
    assert bench_cli.main([*argv, "--check"]) == 2
    textio.write_text(results / "not_run.yaml", "not a mapping\n")
    assert bench_cli.main([*argv, "--check"]) == 4  # a config error, not "differs"


def test_mcnemar_says_why_it_is_missing(results: Path) -> None:
    path = results / "re2-oracle-rq1-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    doc["statistics"]["comparisons"][1].update(
        n_pairs=0, mcnemar_only_a=None, mcnemar_only_b=None, mcnemar_p=None
    )
    textio.write_text(path, json.dumps(doc))
    table = generate.outputs(results, EXPERIMENTS)["tables/t05c-rq1-comparisons.md"].decode()
    assert "not applicable: no paired cases" in table and "McNemar is off" not in table


def test_table_3_pairs_a_revision_of_its_second_source(results: Path) -> None:
    textio.write_text(results / "not_run.yaml", "re2-oracle-loso-v1: {revises: re2-oracle-rq3-v1}\n")
    t3 = generate.outputs(results, EXPERIMENTS)["tables/t03-datasets.md"].decode().splitlines()
    base = next(n for n, line in enumerate(t3) if line.startswith("| re2-ob | ob |"))
    assert "4 normal windows (from re2-oracle-rq3-v1)" in t3[base]
    assert (
        t3[base + 1].startswith("| re2-ob | ob |") and "not run<sup>" in t3[base + 1]
    )  # the revision, not run
    assert any(line.startswith("- re2-oracle-loso-v1 (revises re2-oracle-rq3-v1): not run") for line in t3)
