"""Table cells and result loading (R-17a, #377): canonical number text, every kind of "not run"
with its reason, and metric cells with their bootstrap interval or the reason they have none.

Results come from hand-made bench_summary 1.1 fixtures (fixtures/tables/make_fixtures.py), copied
to tmp_path.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.results import NO_RESULTS, load, read_register
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError, ContractValidationError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tables"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def test_cells_are_canonical() -> None:
    assert (
        cells.fixed(-0.0004) == "0.000" and cells.fixed(0.1235) == "0.123" and cells.fixed(2 / 3) == "0.667"
    )
    assert cells.rate(0.5, (0.375, 0.625)) == cells.Cell("0.500 [0.375, 0.625]")
    assert cells.rate(None) == cells.Cell("n/a", cells.UNDEFINED_NOTE)
    assert cells.count(25000.0).text == "25000" and cells.count(None).text == "n/a"
    assert cells.p_value(0.0004).text == "<0.001" and cells.p_value(0.0451).text == "0.045"
    assert cells.not_run("not run: x") == cells.Cell("not run", "not run: x") == cells.not_run("x")


def test_each_kind_of_missing_result_is_not_run_with_its_reason(results: Path) -> None:
    register = read_register(results)

    def reason(experiment_id: str) -> str | None:
        return load(results, experiment_id, register).reason

    assert reason("re2-oracle-rq1-v1") is None
    assert reason("re2-oracle-rq3-v1") == NO_RESULTS
    assert reason("fse26-oracle-rq1-v1") == "stretch dataset not verified (07 §1.1 cut item 2)"  # register
    assert (
        reason("re2-oracle-rq2-v1") == "incomplete result: no summary.json (bench writes manifest.json last)"
    )
    assert (
        reason("re2-oracle-baselines-r05") == "summary.json is bench_summary 0.1.0; tables read 1.1 (re-run)"
    )
    assert reason("re2-detected-rq1-v1") == "results from a dirty work tree are never used (04 §10.2)"


def test_metric_cells_carry_their_interval_or_say_why_not(results: Path) -> None:
    rq1 = load(results, "re2-oracle-rq1-v1", {})
    off = ("re2-ob", "ob", "veyltrace:off")
    assert rq1.label == "re2-oracle-rq1-v1 @ fixture"
    assert rq1.manifest is not None and [d.dataset for d in rq1.manifest.datasets] == ["synth"]
    assert [name for name, _ in rq1.hashes] == ["manifest.json", "per_case.csv", "summary.json"]
    assert rq1.metric(*off, "ac_at_k", "ac_at_1") == cells.Cell("0.500 [0.375, 0.625]")
    assert rq1.metric(*off, "ac_at_k", "ac_at_2").note == (
        "no interval: summary.json statistics has no `ac_at_2` interval for this group"
    )
    assert rq1.metric(*off, "lift", "lift_at_1") == cells.Cell("4.000")  # a ratio has no interval
    assert rq1.metric(*off, "cost", "wall_ms_p95") == cells.Cell("31000")
    assert rq1.metric(*off, "cost", "tokens_in_p50").text == "n/a"
    assert rq1.metric(*off, "retrieval_at_k", "retrieval_k") == cells.Cell("5")
    assert rq1.metric("re2-ob", "ob", "rcaeval:baro", "rerank_at_1", "rerank_at_1").text == "n/a"
    assert rq1.metric(*off, "onset_error", "n_onset") == cells.not_run(
        "the experiment does not list the metric `onset_error`"
    )
    assert rq1.metric("re2-tt", "tt", "veyltrace:off", "ac_at_k", "ac_at_1") == cells.not_run(
        "no (re2-tt, tt, veyltrace:off) group in its summary.json"
    )
    assert rq1.count(*off, "n_fault") == cells.Cell("8") and rq1.count(*off, "timeout") == cells.Cell("0")
    assert rq1.pooled("re2", "veyltrace:off", "ac_at_1") == cells.not_run(
        "re2 pooled intervals waits for the system-stratified cluster bootstrap"
    )
    prior = load(results, "re2-oracle-prior-only-v1", {})  # statistics is the "not run: …" string
    assert prior.metric("re2-ob", "ob", "prior-only", "ac_at_k", "ac_at_1") == cells.Cell(
        "0.250", "no interval: not run: fixture statistics are off"
    )
    assert prior.pooled("re2", "prior-only", "ac_at_1") == cells.not_run("fixture statistics are off")
    missing = load(results, "re2-oracle-rq3-v1", {})
    assert missing.metric(*off, "ac_at_k", "ac_at_1") == cells.not_run(NO_RESULTS)
    assert missing.label == "re2-oracle-rq3-v1 (not run)"


def test_a_current_summary_that_breaks_its_contract_is_an_error_not_a_not_run(results: Path) -> None:
    path = results / "re2-oracle-rq1-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    doc["groups"][0]["n_fault"] = -1
    textio.write_text(path, json.dumps(doc))
    with pytest.raises(ContractValidationError):
        load(results, "re2-oracle-rq1-v1", {})


def test_a_register_entry_needs_a_reason(results: Path) -> None:
    textio.write_text(results / "not_run.yaml", "re2-oracle-rq3-v1: ''\n")
    with pytest.raises(ConfigError, match="non-empty reason"):
        read_register(results)
    textio.write_text(results / "not_run.yaml", "- a list\n")
    with pytest.raises(ConfigError, match="mapping"):
        read_register(results)
    (results / "not_run.yaml").unlink()
    assert read_register(results) == {}
