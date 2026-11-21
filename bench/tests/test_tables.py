"""The table generator (R-17b, #378): Markdown and LaTeX rendering, byte-identical regeneration,
the results index (Table A0) against its golden file, and write/check with stale files.

Results come from hand-made bench_summary 1.1 fixtures (fixtures/tables/make_fixtures.py), copied
to tmp_path; the experiment YAMLs are the committed ones, so the index covers the real matrix.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from veyltrace_bench.tables import cells, context, generate
from veyltrace_bench.tables.index import NO_DEV_REPORT
from veyltrace_bench.tables.render import Row, Table, latex, markdown
from veyltrace_bench.tables.results import NO_RESULTS, Register, load
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
    src = load(FIXTURES / "results", "re2-oracle-rq3-v1", Register())
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


RQ1 = "re2-oracle-rq1-v1"


def _edit_manifest(results: Path, experiment_id: str, edit: Callable[[dict[str, Any]], object]) -> None:
    path = results / experiment_id / "manifest.json"
    doc = json.loads(textio.read_text(path))
    edit(doc)
    textio.write_text(path, json.dumps(doc))


def test_specs_come_from_the_manifest_and_must_match_the_committed_yaml(results: Path) -> None:
    _edit_manifest(results, RQ1, lambda d: d["experiment"].update(description="as the manifest ran it"))
    ctx = context.context(results, EXPERIMENTS)
    assert ctx.spec(RQ1).description == "as the manifest ran it"  # the manifest, not the YAML
    assert ctx.spec("re2-oracle-rq3-v1").description.startswith("RQ3")  # no results: the YAML
    assert "; protocol: re2-ob, re2-ss, re2-tt (all cases, excluding bench/dev_cases.yaml); oracle alert" in (
        generate.outputs(results, EXPERIMENTS)[INDEX].decode()
    )
    _edit_manifest(results, RQ1, lambda d: d.update(experiment_sha256="0" * 64))
    reason = context.context(results, EXPERIMENTS).get(RQ1).reason or ""
    assert reason.startswith("results are from another version of the YAML")


def test_a_development_case_in_a_prereg_re2_run_is_an_error(results: Path) -> None:
    dev = context.context(results, EXPERIMENTS).dev_cases
    assert dev is not None and len(dev) == 3
    _edit_manifest(
        results, RQ1, lambda d: d["datasets"][0].update(cases=sorted([*d["datasets"][0]["cases"], dev[0]]))
    )
    with pytest.raises(ConfigError, match="ran development cases"):
        context.context(results, EXPERIMENTS)


def test_the_development_cases_have_their_own_slot(results: Path) -> None:
    a2 = generate.outputs(results, EXPERIMENTS)["tables/a2-development-cases.md"].decode()
    assert "97bf1c72d29f" in a2 and f"not run: {NO_DEV_REPORT}" in a2


def test_the_register_may_name_04_6_cells_without_a_yaml(results: Path) -> None:
    textio.write_text(results / "not_run.yaml", "cloud-opsbench/agent-only: optional in 04 §3\n")
    index = generate.outputs(results, EXPERIMENTS)[INDEX].decode()
    assert "| 04 §6 cell cloud-opsbench/agent-only | - | - | not run<sup>" in index
    textio.write_text(results / "not_run.yaml", "cloud-opsbench/brief: not a planned cell\n")
    with pytest.raises(ConfigError, match="neither an experiment YAML nor a 04 §6 cell"):
        generate.outputs(results, EXPERIMENTS)


def test_a_revision_prints_next_to_the_pre_registered_rows(results: Path) -> None:
    textio.write_text(results / "not_run.yaml", f"re2-oracle-prior-only-v1: {{revises: {RQ1}}}\n")
    ctx = context.context(results, EXPERIMENTS)

    def build(c: context.Context) -> list[Table]:
        res = c.get(RQ1)
        return [Table("t", "T", "c", ("Ran",), (Row((cells.text(res.experiment_id),), res),))]

    (table,) = generate.paired(build, ctx)
    md = markdown(table)
    assert f"| {RQ1} | {RQ1} @ fixture (pre-registered) |" in md
    assert f"| re2-oracle-prior-only-v1 | re2-oracle-prior-only-v1 @ fixture (revises {RQ1}) |" in md
    textio.write_text(results / "not_run.yaml", "re2-oracle-prior-only-v1: {revises: re2-typo-v1}\n")
    with pytest.raises(ConfigError, match="revises unknown experiments"):
        context.context(results, EXPERIMENTS)


def test_revised_rows_follow_the_last_row_of_their_key(results: Path) -> None:
    textio.write_text(
        results / "not_run.yaml",
        f"re2-oracle-prior-only-v1: {{revises: {RQ1}}}\nre2-oracle-rq3-v1: {{revises: {RQ1}}}\n",
    )
    ctx = context.context(results, EXPERIMENTS)

    def build(c: context.Context) -> list[Table]:  # the revisions report one row per part, rq1 two
        res = c.get(RQ1)
        labels = ["a", "b"] if res.role == "pre-registered" else ["r"]
        rows = [Row((cells.text(p), cells.text(m)), res) for p in c.spec(RQ1).dataset.parts for m in labels]
        return [Table("t", "T", "c", ("Part", "Method"), tuple(rows))]

    (table,) = generate.paired(build, ctx)
    got = [(r.cells[0].text, r.cells[1].text, r.source.experiment_id if r.source else "") for r in table.rows]
    assert got[:4] == [
        ("re2-ob", "a", RQ1), ("re2-ob", "b", RQ1),
        ("re2-ob", "r", "re2-oracle-prior-only-v1"), ("re2-ob", "r", "re2-oracle-rq3-v1"),
    ]  # fmt: skip
    assert len(got) == 12 and got[-1] == ("re2-tt", "r", "re2-oracle-rq3-v1")


def test_a_revision_must_name_a_pre_registered_experiment_directly(results: Path) -> None:
    chain = "re2-oracle-rq3-v1: {revises: re2-oracle-prior-only-v1}\n"
    chain += f"re2-oracle-prior-only-v1: {{revises: {RQ1}}}\n"
    for register in (chain, "re2-oracle-rq3-v1: {revises: re2-oracle-baselines-r05}\n"):
        textio.write_text(results / "not_run.yaml", register)
        with pytest.raises(ConfigError, match="no chain"):
            context.context(results, EXPERIMENTS)
