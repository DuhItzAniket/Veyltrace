"""The table generator (R-17b, #378): Markdown and LaTeX rendering, byte-identical regeneration,
the results index (Table A0) against its golden file, and write/check with stale files.

Results come from hand-made bench_summary 1.1 fixtures (fixtures/tables/make_fixtures.py), copied
to tmp_path; the experiment YAMLs are the committed ones, so the index covers the real matrix.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import cells, context, generate
from veyltrace_bench.tables.render import Row, Table, latex, markdown
from veyltrace_bench.tables.results import NO_RESULTS, load
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
INDEX = "tables/a0-results-index.md"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def test_regeneration_is_byte_identical_and_path_independent(results: Path, tmp_path: Path) -> None:
    first = generate.outputs(results, EXPERIMENTS)
    assert generate.outputs(results, EXPERIMENTS) == first
    moved = shutil.copytree(results, tmp_path / "elsewhere" / "results")
    assert generate.outputs(moved, EXPERIMENTS) == first
    assert list(first) == sorted(first) and all(b"\r" not in data for data in first.values())


def test_the_index_matches_its_golden_file_and_lists_every_reportable_experiment(results: Path) -> None:
    files = generate.outputs(results, EXPERIMENTS)
    assert files[INDEX] == textio.read_bytes(FIXTURES / "expected" / "a0-results-index.md")
    reportable = context.reportable(EXPERIMENTS)
    assert len(reportable) == len(list(EXPERIMENTS.glob("*.yaml"))) - 2  # synth-smoke, synth-baselines
    text = files[INDEX].decode()
    assert all(f"| {e.experiment_id} |" in text for e in reportable)
    assert "| re2-oracle-rq1-v1 | RQ1 | yes | run | 8 | 20 intervals, 2 comparisons, 1 not run |" in text
    assert "commit fixture; sha256 manifest.json " in text  # provenance of a run experiment
    assert text.count(f". not run: {NO_RESULTS}\n") == 1  # one note for every experiment without results


def test_write_then_check_and_stale_files(results: Path) -> None:
    files = generate.outputs(results, EXPERIMENTS)
    assert generate.write(files, results) == sorted(files)
    assert generate.differences(files, results) == [] and generate.write(files, results) == []
    textio.write_text(results / INDEX, "hand edit\n")
    textio.write_text(results / "tables" / "old.md", "stale\n")
    textio.write_text(results / "tables" / "notes.txt", "not generated: left alone\n")
    assert generate.differences(files, results) == [INDEX, "tables/old.md"]
    generate.write(files, results)
    assert not (results / "tables" / "old.md").exists() and (results / "tables" / "notes.txt").exists()
    assert generate.differences(files, results) == []


def test_a_register_naming_an_unknown_experiment_is_a_config_error(results: Path) -> None:
    textio.write_text(results / "not_run.yaml", "re2-typo-v1: cut\n")
    with pytest.raises(ConfigError, match="re2-typo-v1"):
        generate.outputs(results, EXPERIMENTS)


def test_renderers_escape_and_number_notes_once() -> None:
    src = load(FIXTURES / "results", "re2-oracle-rq3-v1", {})
    row = Row((cells.text("a|b_c"), cells.not_run("x ≥ 1 & y")), src)
    table = Table("t", "T", "Caption § 7.", ("Name", "Value"), (row, row))
    md = markdown(table)
    assert "| a\\|b_c | not run<sup>1</sup> | re2-oracle-rq3-v1 (not run) |" in md
    assert md.count("\n1. not run: x ≥ 1 & y\n") == 1 and "<sup>2</sup>" not in md
    tex = latex(table)
    assert r"a\textbar{}b\_c & not run\textsuperscript{1} &" in tex
    assert r"\textsuperscript{1} not run: x $\geq$ 1 \& y\\" in tex and r"\caption{T. Caption \S{} 7.}" in tex
    with pytest.raises(ValueError, match="cells"):
        Table("t", "T", "c", ("One",), (row,))
    orphan = markdown(Table("r", "R", "c", ("Rate",), (Row((cells.text("0.5"),), None),)))
    assert "| 0.5 | no bench experiment |" in orphan and orphan.endswith(
        "- none: every row has no bench experiment\n"
    )
