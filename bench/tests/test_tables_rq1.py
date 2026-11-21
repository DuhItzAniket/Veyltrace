"""`veyltrace bench tables` and the RQ1 tables (R-17c, #379): Table 3 datasets, Table 5 per
benchmark and protocol with the floors, and the H1 comparisons, from hand-made 1.1 fixtures.
"""

from __future__ import annotations

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
    assert _row(t5, "ob", "chance").startswith("| ob | chance | 0.125<sup>")  # no interval: not a case mean
    assert "| n/a<sup>" in _row(t5, "ob", "chance")  # Avg@5 … Rerank@1 do not apply to the floor
    assert _row(t5, "ob", "prior-only").startswith("| ob | prior-only | 0.250<sup>")  # its statistics are off
    assert _row(t5, "ob", "veyltrace:off").startswith("| ob | veyltrace:off | 0.500 [0.375, 0.625] |")
    assert _row(t5, "ob", "veyltrace:off").endswith("| 8 | 8/0/0/0/0 | re2-oracle-rq1-v1 @ fixture |")
    order = [line.split(" | ")[1] for line in t5.splitlines() if line.startswith("| ob |")]
    assert order[:5] == [
        "chance",
        "prior-only",
        "rcaeval:baro",
        "rcaeval:nsigma",
        "simplerca",
    ]  # YAML order within a kind
    assert order[-2:] == ["causatrix:rrf", "veyltrace:off"]
    assert "| tt | veyltrace:off | not run<sup>" in t5  # no re2-tt group in the fixture
    assert "| pooled | veyltrace:off | not run<sup>" in t5
    assert "re2 pooled intervals waits for the system-stratified cluster bootstrap" in t5


def test_not_run_experiments_render_whole_tables(files: dict[str, str]) -> None:
    detected = files["tables/t05-rq1-re2-detected.md"]
    assert "results from a dirty work tree are never used" in detected
    assert "| ob | veyltrace:off | not run<sup>1</sup> |" in detected
    fse = files["tables/t05-rq1-fse26-oracle.md"]
    assert "stretch dataset not verified" in fse and "fse26-oracle-rq1-v1 (not run)" in fse


def test_table_3_and_the_comparisons(files: dict[str, str]) -> None:
    t3 = files["tables/t03-datasets.md"]
    assert _row(t3, "re2-ob", "ob").startswith("| re2-ob | ob | 8 | 1 | 0 | 8 | 0 |")
    assert "| nezha-ob | ob | not run<sup>" in t3
    comparisons = files["tables/t05c-rq1-comparisons.md"]
    row = _row(comparisons, "re2-ob ob", "ac_at_1", "veyltrace:off − rcaeval:baro", "superiority (rq1)")
    assert "| 0.125 [-0.125, 0.375] | 8 | 4 | 0.5000 | 2/1 | 1.0000 | <0.001 |" in row
    noninferiority = _row(
        comparisons, "re2-ob ob", "ac_at_1", "veyltrace:off − rcaeval:baro", "noninferiority"
    )
    assert "| 0.000 | 0.125 [-0.125, 0.375] |" in noninferiority and "no Holm family" in comparisons


def test_cli_writes_then_checks(results: Path) -> None:
    argv = ["tables", "--results", str(results), "--experiments", str(EXPERIMENTS)]
    assert bench_cli.main([*argv, "--check"]) == 1  # nothing written yet
    assert bench_cli.main(argv) == 0
    assert bench_cli.main([*argv, "--check"]) == 0
    textio.write_text(results / T5, "hand edit\n")
    assert bench_cli.main([*argv, "--check"]) == 1
