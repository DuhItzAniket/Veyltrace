"""Table cells and result loading (R-17a, #377): canonical number text, every kind of "not run"
with its reason, and metric cells with their bootstrap interval or the reason they have none.

Results come from hand-made bench_summary 1.1 fixtures (fixtures/tables/make_fixtures.py), copied
to tmp_path.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.results import (
    NO_GROUP,
    NO_INTERVAL,
    NO_RESULTS,
    OLD_FORMAT,
    UNLISTED,
    Register,
    load,
    read_register,
)
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.hashing import sha256_text_lf

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tables"
EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"
NONE = Register()


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def test_cells_are_canonical() -> None:
    assert (
        cells.fixed(0.1235) == "0.124" and cells.fixed(0.1245) == "0.125"
    )  # ROUND_HALF_UP of the file's text
    assert cells.fixed(2 / 3) == "0.667" and cells.fixed(-0.0004) == "0.000"  # an estimate drops the sign
    assert cells.fixed(-0.0004, signed=True) == "-0.000"  # an interval bound keeps it
    assert cells.rate(0.5, (0.375, 0.625)) == cells.Cell("0.500 [0.375, 0.625]")
    assert cells.rate(0.0, (-0.0004, 0.25)).text == "0.000 [-0.000, 0.250]"
    assert cells.rate(None) == cells.Cell("n/a", cells.UNDEFINED_NOTE)
    assert cells.count(25000.0).text == "25000" and cells.count(None).text == "n/a"
    assert cells.p_value(0.0004).text == "<0.001" and cells.p_value(0.04515).text == "0.0452"
    assert cells.p_value(0.001).text == "0.0010" and cells.p_value(1.0).text == "1.0000"
    assert cells.not_run("not run: x") == cells.Cell("not run", "not run: x") == cells.not_run("x")


def test_each_kind_of_missing_result_is_not_run_with_its_reason(results: Path) -> None:
    register = read_register(results)

    def reason(experiment_id: str) -> str | None:
        return load(results, experiment_id, register).reason

    assert reason("re2-oracle-rq1-v1") is None
    assert reason("re2-oracle-loso-v1") == NO_RESULTS
    assert reason("fse26-oracle-rq1-v1") == "stretch dataset not verified (07 §1.1 cut item 2)"  # register
    assert (
        reason("re3-oracle-rq2-v1") == "incomplete result: no summary.json (bench writes manifest.json last)"
    )
    assert reason("re2-oracle-baselines-r05") == OLD_FORMAT.format("0.1.0")  # ran: not tabulated (R5)
    assert reason("re2-detected-rq1-v1") == "results from a dirty work tree are never used (04 §10.2)"


def test_results_of_another_yaml_version_are_not_run(results: Path) -> None:
    committed = sha256_text_lf(EXPERIMENTS / "re2-oracle-rq1-v1.yaml")
    assert load(results, "re2-oracle-rq1-v1", NONE, committed).reason is None
    other = load(results, "re2-oracle-rq1-v1", NONE, "0" * 64).reason or ""
    assert other.startswith(
        f"results are from another version of the YAML (sha {committed[:12]}…, committed 000000000000…"
    )


def test_metric_cells_carry_their_interval_or_say_why_not(results: Path) -> None:
    rq1 = load(results, "re2-oracle-rq1-v1", NONE)
    off = ("re2-ob", "ob", "veyltrace:off")
    assert rq1.label == "re2-oracle-rq1-v1 @ fixture"
    assert rq1.manifest is not None and rq1.manifest.experiment["experiment_id"] == "re2-oracle-rq1-v1"
    assert [d.dataset for d in rq1.manifest.datasets] == ["re2-ob", "re2-ss", "re2-tt"]
    assert [name for name, _ in rq1.hashes] == ["manifest.json", "per_case.csv", "summary.json"]
    assert rq1.metric(*off, "ac_at_k", "ac_at_1") == cells.Cell("0.500 [0.375, 0.625]")
    assert rq1.metric(*off, "ac_at_k", "ac_at_2").note == (
        "no interval: summary.json statistics has no `ac_at_2` interval for this group"
    )
    assert rq1.metric(*off, "lift", "lift_at_1") == cells.Cell("4.000", NO_INTERVAL)  # a ratio: none (R3)
    assert rq1.metric(*off, "cost", "wall_ms_p95") == cells.Cell("31000")
    assert rq1.metric(*off, "cost", "tokens_in_p50").text == "n/a"
    assert rq1.metric(*off, "retrieval_at_k", "retrieval_k") == cells.Cell("5")
    assert rq1.metric(*off, "retrieval_at_k", "retrieval_at_k").text == "0.875 (K=5)"  # K from retrieval_k
    assert rq1.metric("re2-ob", "ob", "rcaeval:baro", "rerank_at_1", "rerank_at_1").text == "n/a"
    assert rq1.metric("re2-ob", "ob", "rcaeval:baro", "retrieval_at_k", "retrieval_at_k").text == "n/a"
    assert rq1.metric(*off, "onset_error", "n_onset") == cells.not_applicable(UNLISTED.format("onset_error"))
    assert rq1.metric("re2-tt", "tt", "veyltrace:off", "ac_at_k", "ac_at_1") == cells.not_run(NO_GROUP)
    assert rq1.count(*off, "n_fault") == cells.Cell("8") and rq1.count(*off, "timeout") == cells.Cell("0")
    assert rq1.pooled("re2", "veyltrace:off", "ac_at_1") == cells.not_run(
        "re2 pooled intervals waits for the system-stratified cluster bootstrap"
    )
    assert rq1.system_of("re2-ob") == "ob" and rq1.system_of("re2-tt") == "tt"  # no tt group: the suffix
    prior = load(results, "re2-oracle-prior-only-v1", NONE)  # statistics is the "not run: …" string
    assert prior.metric("re2-ob", "ob", "prior-only", "ac_at_k", "ac_at_1") == cells.Cell(
        "0.250", "no interval: not run: fixture statistics are off"
    )
    assert prior.pooled("re2", "prior-only", "ac_at_1") == cells.not_run("fixture statistics are off")
    missing = load(results, "re2-oracle-loso-v1", NONE)
    assert missing.metric(*off, "ac_at_k", "ac_at_1") == cells.not_run(NO_RESULTS)
    assert missing.label == "re2-oracle-loso-v1 (not run)"
    assert replace(missing, role="pre-registered").label == "re2-oracle-loso-v1 (not run) (pre-registered)"


def test_a_current_summary_that_breaks_its_contract_is_an_error_not_a_not_run(results: Path) -> None:
    path = results / "re2-oracle-rq1-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    doc["groups"][0]["n_fault"] = -1
    textio.write_text(path, json.dumps(doc))
    with pytest.raises(ContractValidationError):
        load(results, "re2-oracle-rq1-v1", NONE)


def test_the_register_holds_reasons_and_revisions(results: Path) -> None:
    textio.write_text(
        results / "not_run.yaml",
        "re2-oracle-rq3-v1: cut\nre2-oracle-rq2-v1: {revises: re2-oracle-rq1-v1}\n"
        "re3-oracle-rq1-v1: {revises: re2-oracle-rq1-v1, reason: LLM budget}\n",
    )
    register = read_register(results)
    assert register.reasons == {"re2-oracle-rq3-v1": "cut", "re3-oracle-rq1-v1": "LLM budget"}
    assert register.revises == {
        "re2-oracle-rq2-v1": "re2-oracle-rq1-v1",
        "re3-oracle-rq1-v1": "re2-oracle-rq1-v1",
    }
    for bad in (
        "re2-oracle-rq3-v1: ''\n",
        "re2-oracle-rq3-v1: {revises: 3}\n",
        "x: {revises: a, other: b}\n",
    ):
        textio.write_text(results / "not_run.yaml", bad)
        with pytest.raises(ConfigError, match="non-empty reason"):
            read_register(results)
    textio.write_text(results / "not_run.yaml", "- a list\n")
    with pytest.raises(ConfigError, match="mapping"):
        read_register(results)
    (results / "not_run.yaml").unlink()
    assert read_register(results) == Register()


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0", "1.3.0"])
def test_summaries_of_1_1_and_1_2_are_read_others_are_not_tabulated(results: Path, version: str) -> None:
    """1.2 is the current minor (#411); a 1.1 file reads with the 1.2 entries null, and the cell
    names the file's version; any other minor ran but is not tabulated (R5)."""
    path = results / "re2-oracle-rq3-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    doc["schema_version"] = version
    if version == "1.1.0":
        for group in doc["groups"]:
            for entry in ("coverage", "set_size", "no_fault_rates", "risk_coverage", "selective_accuracy",
                          "decoy_top1_change", "permutation_invariance"):  # fmt: skip
                del group["metrics"][entry]
    textio.write_text(path, json.dumps(doc))
    res = load(results, "re2-oracle-rq3-v1", NONE)
    cell = res.metric("re2-ob", "ob", "veyltrace:off", "coverage", "coverage")
    if version == "1.3.0":
        assert res.reason == OLD_FORMAT.format("1.3.0") and res.commit == "fixture" and res.hashes
    elif version == "1.2.0":
        assert res.reason is None and res.file_version == "1.2.0" and cell == cells.Cell("0.875", NO_INTERVAL)
    else:
        assert res.reason is None and res.file_version == "1.1.0"
        assert cell == cells.not_run(
            "summary.json is bench_summary 1.1, which has no `coverage` entry (re-run)"
        )
