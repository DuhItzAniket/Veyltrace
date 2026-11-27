"""Shared table semantics (R-17 #46, lead rules R1–R5): a revised pre-registered experiment reads
"revised as <id>" and its revision "revises <id>", in tables and figures alike; a metric that does
not apply is n/a, never "not run"; a value without an interval says so, and the RQ3 rates take
their interval from rq3-intervals; results in an older summary minor ran and keep their
provenance. Also Table A0's side results and uncovered 04 §6 cells, Table 3's one row per part,
and Table A2's development-case rows.

The revision scenario turns the fixture's re2-oracle-rq3-v1 results into the AI-off revision
re2-oracle-rq3-off-v1 (only its veyltrace:off groups), as the committed results are.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from veyltrace_bench.experiment import load_experiment
from veyltrace_bench.tables import cells, context, generate
from veyltrace_bench.tables.index import NO_COVER, covered, matrix_row
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import (
    NO_INTERVAL,
    OLD_FORMAT,
    REVISION_CUT,
    UNLISTED,
    load,
    load_rq3,
    read_register,
)
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_text_lf

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
RQ3, OFF = "re2-oracle-rq3-v1", "re2-oracle-rq3-off-v1"
REVISED = f"revised as {OFF} (04 §12, 25 Nov)"
DROPPED = f"{REVISED}; the revision does not run veyltrace:brief ({REVISION_CUT})"  # the cut arm (R1)


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(textio.read_text(path))
    return data


def _revise(results: Path, intervals: bool = True) -> None:
    """re2-oracle-rq3-v1's fixture results become its AI-off revision's, with rq3-intervals."""
    out = results / OFF
    (results / RQ3).rename(out)
    yaml = EXPERIMENTS / f"{OFF}.yaml"
    manifest = _json(out / "manifest.json")
    manifest.update(
        experiment_id=OFF,
        experiment_sha256=sha256_text_lf(yaml),
        experiment=load_experiment(yaml).model_dump(mode="json"),
    )
    textio.write_text(out / "manifest.json", json.dumps(manifest))
    summary = _json(out / "summary.json")
    summary["experiment_id"] = OFF
    summary["groups"] = [g for g in summary["groups"] if g["method"] == "veyltrace:off"]
    params = _json(results / "re2-oracle-rq1-v1" / "summary.json")["statistics"]["params"]
    summary["statistics"] = {"comparisons": [], "intervals": [], "not_run": [], "params": params}
    textio.write_text(out / "summary.json", json.dumps(summary))
    textio.write_text(results / "not_run.yaml", f"{OFF}: {{revises: {RQ3}}}\n")
    if intervals:
        side = results / "rq3-intervals" / OFF
        side.mkdir(parents=True)
        scopes = {s: {"coverage": {"estimate": 0.875, "low": 0.625, "high": 1.0},
                      "aurc_verdict": {"estimate": 0.25, "low": 0.125, "high": 0.5}}
                  for s in ("ob", "ss", "tt", "pooled")}  # fmt: skip
        doc = {"experiment_id": OFF, "level": 0.95, "resamples": 2000, "intervals": scopes}
        textio.write_text(side / "summary.json", json.dumps(doc))
        textio.write_text(side / "rows.csv", "cluster\nob-1\n")


def test_a_revised_experiment_reads_revised_not_not_run(results: Path) -> None:
    _revise(results)
    register = read_register(results)
    old = load(results, RQ3, register)
    assert old.reason == REVISED and old.revised_as == (OFF,)
    assert cells.not_run(REVISED) == cells.Cell(cells.REVISED, REVISED)
    assert old.label == f"{RQ3} (revised as {OFF})"
    ctx = context.context(results, EXPERIMENTS)
    pre, rev = ctx.get(RQ3), ctx.get(OFF)
    assert pre.label == f"{RQ3} (pre-registered; revised as {OFF})"
    assert pre.revision_methods == {"veyltrace:off"}
    assert rev.role == f"revises {RQ3}" and rev.label == f"{OFF} @ fixture (revises {RQ3})"
    off = pre.metric("re2-ob", "ob", "veyltrace:off", "ac_at_k", "ac_at_1")
    assert off == cells.Cell(cells.REVISED, REVISED)
    brief = pre.metric("re2-ob", "ob", "veyltrace:brief", "ac_at_k", "ac_at_1")
    assert brief == cells.Cell(cells.REVISED, DROPPED)
    assert "LLM budget; #532, ADR 20261121-ak-r16-cut-list, addendum of 25 Nov" in DROPPED  # gap 34
    assert pre.pooled("re2", "veyltrace:off", "ac_at_1").text == cells.REVISED
    files = generate.outputs(results, EXPERIMENTS)
    t7 = files["tables/t07-rq3-calibration.md"].decode()
    assert f"- {RQ3} (pre-registered): {REVISED}; protocol:" in t7  # no "not run" for a revised id
    assert f"| {RQ3} (pre-registered; revised as {OFF}) |" in t7
    assert f"| {OFF} @ fixture (revises {RQ3}) |" in t7


def test_the_revision_rows_are_paired_once(results: Path) -> None:
    """generate.paired inserts the rows that stand in for the pre-registered id, not the
    revision's own rows, although both now carry the role "revises <id>"; and the revision's own
    row under its own id is left out, since the stand-in prints the same values (gap 35)."""
    _revise(results)
    ctx = context.context(results, EXPERIMENTS)

    def build(c: context.Context) -> list[Table]:
        rows = [Row((cells.text(i),), c.get(i)) for i in (RQ3, OFF)]
        return [Table("t", "T", "c", ("Id",), tuple(rows))]

    (table,) = generate.paired(build, ctx)
    got = [(r.cells[0].text, r.source.label if r.source else "") for r in table.rows]
    assert got == [
        (RQ3, f"{RQ3} (pre-registered; revised as {OFF})"),
        (RQ3, f"{OFF} @ fixture (revises {RQ3})"),
    ]

    def alone(c: context.Context) -> list[Table]:  # a table citing the revision only by its own id
        return [Table("t", "T", "c", ("Id",), (Row((cells.text(OFF),), c.get(OFF)),))]

    (table,) = generate.paired(alone, ctx)
    assert [r.cells[0].text for r in table.rows] == [OFF]  # kept: nothing stands in for it


def test_figures_pair_a_revision_like_the_tables(results: Path) -> None:
    _revise(results)
    files = generate.outputs(results, EXPERIMENTS)
    rows = list(csv.DictReader(files["figures/fig6-risk-coverage.csv"].decode().splitlines()))
    ob = [r for r in rows if r["panel"] == "ob" and r["x"] == "AURC verifier"]
    assert [(r["series"], r["experiment"], r["status"]) for r in ob] == [
        ("veyltrace:off", RQ3, REVISED),
        ("veyltrace:off", OFF, "ok"),  # right after the pre-registered point it replaces
        ("veyltrace:brief", RQ3, DROPPED),
    ]
    assert (ob[1]["value"], ob[1]["low"], ob[1]["high"]) == ("0.25", "0.125", "0.5")  # rq3-intervals
    fused = next(r for r in rows if r["panel"] == "ob" and r["x"] == "AURC fused" and r["experiment"] == OFF)
    assert fused["status"] == f"ok; {NO_INTERVAL}"  # no interval for it in the side file
    image = files["figures/fig6-risk-coverage-ob.svg"].decode()
    assert f"veyltrace:off (revises {RQ3})" in image and "veyltrace:off (pre-registered)" in image
    assert "not run" not in image


def test_rq3_intervals_bound_the_rq3_rates_and_must_match_the_summary(results: Path) -> None:
    _revise(results)
    res = context.context(results, EXPERIMENTS).get(OFF)
    assert res.rq3 is not None and [n for n, _ in res.hashes][-2:] == [
        f"rq3-intervals/{OFF}/rows.csv",
        f"rq3-intervals/{OFF}/summary.json",
    ]  # the side file is cited with the experiment (R4)
    off = ("re2-ob", "ob", "veyltrace:off")
    assert res.metric(*off, "coverage", "coverage") == cells.Cell("0.875 [0.625, 1.000]")
    assert res.metric(*off, "coverage", "coverage_gap") == cells.Cell("-0.025", NO_INTERVAL)
    assert res.pooled("re2", "veyltrace:off", "coverage") == cells.Cell("0.875 [0.625, 1.000]")
    path = results / "rq3-intervals" / OFF / "summary.json"
    doc = _json(path)
    doc["intervals"]["ob"]["coverage"]["estimate"] = 0.5
    textio.write_text(path, json.dumps(doc))
    with pytest.raises(ConfigError, match=r"is not summary\.json's"):
        context.context(results, EXPERIMENTS).get(OFF).metric(*off, "coverage", "coverage")
    doc["experiment_id"] = RQ3
    textio.write_text(path, json.dumps(doc))
    with pytest.raises(ConfigError, match="holds the intervals of"):
        load_rq3(results, OFF)


def test_a_metric_that_does_not_apply_is_n_a_not_not_run(results: Path) -> None:
    res = load(results, "re2-oracle-rq1-v1", read_register(results))
    baro = ("re2-ob", "ob", "rcaeval:baro")
    unlisted = cells.not_applicable(UNLISTED.format("onset_error"))
    assert res.metric(*baro, "onset_error", "n_onset") == unlisted and unlisted.text == "n/a"
    assert res.pooled("re2", "rcaeval:baro", "retrieval_at_k") == cells.rate(None)  # null in every part
    assert res.pooled("re2", "rcaeval:baro", "onset_error_median_ms") == unlisted


def test_an_older_summary_ran_and_keeps_its_provenance(results: Path) -> None:
    res = load(results, "re2-oracle-baselines-r05", read_register(results))
    assert res.reason == OLD_FORMAT.format("0.1.0") and res.commit == "fixture" and len(res.hashes) == 3
    assert res.old is not None and res.old.groups == 2 and res.label == "re2-oracle-baselines-r05 @ fixture"
    assert res.reason is not None and cells.not_run(res.reason).text == cells.NOT_TABULATED
    index = generate.outputs(results, EXPERIMENTS)["tables/a0-results-index.md"].decode()
    assert "| re2-oracle-baselines-r05 | RQ1 | no | run (bench_summary 0.1.0)<sup>" in index
    assert "| 2 | none<sup>" in index
    assert "bench_summary 0.1.0 statistics: not run: cluster bootstrap" in index
    assert "- re2-oracle-baselines-r05: ran (bench_summary 0.1.0); its summary.json is not tabulated" in index
    assert "; commit fixture; sha256 manifest.json " in index


def test_the_index_lists_side_results_replays_and_uncovered_cells(results: Path) -> None:
    _revise(results)
    shutil.copytree(results / "re2-oracle-rq1-v1", results / "perf-o11")  # any non-experiment folder
    index = generate.outputs(results, EXPERIMENTS)["tables/a0-results-index.md"].decode()
    assert f"| {RQ3} | RQ3 | yes | revised<sup>" in index
    assert "the revision does not run veyltrace:brief" in index  # the arm the revision drops
    assert f"| {OFF} @ fixture (revises {RQ3}) |" in index
    assert f"; + 8 RQ3 intervals (rq3-intervals/{OFF})" in index
    assert f"| rq3-intervals/{OFF} | RQ3 | - | run | n/a<sup>" in index
    assert "| 8 intervals (95% cluster bootstrap, 2000 resamples) |" in index
    assert "| perf-o11 | RQ5 | - | run |" in index and "- perf-o11: sha256 manifest.json " in index
    assert "| replay/ci | RQ6 | - | not run<sup>" in index
    for cell in ("re1-oracle/baselines", "re1-oracle/rankers", "re1-oracle/off"):
        assert f"| 04 §6 cell {cell} | - | - | not run<sup>" in index
    assert NO_COVER in index
    assert "metrics without interval (" in index and "not run<sup>" not in _row(index, "re2-oracle-rq1-v1")


def _row(text: str, first: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"| {first} |"))


def test_every_committed_yaml_maps_to_a_planned_cell() -> None:
    for exp in context.reportable(EXPERIMENTS):
        assert covered(exp) <= context.CELLS, (exp.experiment_id, covered(exp) - context.CELLS)
    shift = load_experiment(EXPERIMENTS / "re2-shift-m60-v1.yaml")
    assert matrix_row(shift) == "re2-onset-shift"
    assert matrix_row(load_experiment(EXPERIMENTS / "re2-oracle-planted-v1.yaml")) == "re2-proposal-decoys"
    assert matrix_row(load_experiment(EXPERIMENTS / f"{OFF}.yaml")) == "re2-calibration"


def test_table_3_has_one_row_per_part_with_the_revisions_windows(results: Path) -> None:
    _revise(results, intervals=False)
    t3 = generate.outputs(results, EXPERIMENTS)["tables/t03-datasets.md"].decode()
    ob = [line for line in t3.splitlines() if line.startswith("| re2-ob | ob |")]
    assert len(ob) == 1
    assert f"| 4 normal windows (from {OFF}, revises {RQ3}, 04 §12, 25 Nov) |" in ob[0]
    assert f"- {OFF} (revises {RQ3}): commit fixture;" in t3 and f"- {RQ3}" not in t3


def test_table_a2_reports_the_development_cases_rows(results: Path) -> None:
    dev = context.context(results, EXPERIMENTS).dev_cases
    assert dev is not None
    path = results / "re2-oracle-baselines-r05" / "per_case.csv"
    header = textio.read_text(path).splitlines()[0]
    line = f"{dev[0]},re2-ob,ob,rcaeval:baro,off,,,,oracle,ok,,0,,,a;b,0,1,1" + "," * 12
    assert len(line.split(",")) == len(header.split(","))
    textio.write_text(path, f"{header}\n{line}\n")
    a2 = generate.outputs(results, EXPERIMENTS)["tables/a2-development-cases.md"].decode()
    assert f"| {dev[0]} | re2-ob | rcaeval:baro | ok | 0 | 1 | 1 | re2-oracle-baselines-r05 @ fixture |" in a2
    assert f"| {dev[1]} | not run<sup>" in a2  # no committed row for it


def test_table_a2_lists_the_timing_runs_of_the_development_cases(results: Path) -> None:
    dev = context.context(results, EXPERIMENTS).dev_cases
    assert dev is not None
    perf = results / "perf-o11"
    perf.mkdir()
    header = "case,system,pass,outcome,wall_ms,peak_rss_mb"
    rows = [
        f"{dev[0]},re2-ob,1,ok,7234.1,708.5",
        f"{dev[0]},re2-ob,2,ok,7116.3,722.0",
        "aaaaaaaaaaaa,re2-ob,1,ok,1,1",
    ]
    textio.write_text(perf / "m4.csv", "\n".join([header, *rows]) + "\n")
    textio.write_text(perf / "README.md", "timing sample\n")
    a2 = generate.outputs(results, EXPERIMENTS)["tables/a2-development-cases.md"].decode()
    assert f"| {dev[0]} | re2-ob | pipeline timing run, pass 1 (m4.csv) | ok | n/a<sup>" in a2
    assert f"| {dev[0]} | re2-ob | pipeline timing run, pass 2 (m4.csv) | ok | n/a<sup>" in a2
    assert "aaaaaaaaaaaa" not in a2  # only the development cases (gap 89)
    source = next(line for line in a2.splitlines() if line.startswith("- perf-o11: sha256 "))
    assert "m4.csv " in source and "README.md " in source  # cited with its file hashes (R4)
