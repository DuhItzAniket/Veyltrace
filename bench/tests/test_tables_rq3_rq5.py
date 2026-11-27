"""Tables 7, 7b, 7c, 8, 8b, 8c, A1 and Fig 6 (R-17 #46, audit gaps 27–51, 82–83): the H3c
difference V − F and pooled rows with their rq3-intervals intervals, NO_FAULT precision and recall,
the runs behind each set size, per-fold coverage, the literal τ_nf sensitivity analysis, the
reasons of undefined NO_FAULT rates and of missing cost (slate reuse, replayed AI arms), the AI
path's recorded cost (rq5-ai-cost) and the slowest laptop (perf-o11), and every experiment in A1.

The revision scenario turns the fixture's re2-oracle-rq3-v1 results into its AI-off revision
re2-oracle-rq3-off-v1, as the committed results are (test_tables_semantics does the same).
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from veyltrace_bench.experiment import load_experiment
from veyltrace_bench.tables import cells, context, generate, rq56
from veyltrace_bench.tables.rq23 import NO_DECLARED, NO_NORMAL
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_text_lf

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
RQ3, OFF, RQ2 = "re2-oracle-rq3-v1", "re2-oracle-rq3-off-v1", "re2-oracle-rq2-v1"
STAND_IN = f"{OFF} @ fixture (revises {RQ3})"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(textio.read_text(path))
    return data


def _interval(estimate: float, low: float, high: float) -> dict[str, float]:
    return {"estimate": estimate, "low": low, "high": high}


def _revise(results: Path, difference: float = -0.125) -> Path:
    """re2-oracle-rq3-v1's fixture results become its AI-off revision's, with an rq3-intervals file
    holding V − F (the fixture's AURC V 0.25 and F 0.375) and the literal τ_nf analysis."""
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
    for g in summary["groups"]:
        g["metrics"]["coverage"]["by_fold"] = [
            {"fold": "foldA", "coverage": 1.0, "n_fault": 4},
            {"fold": "foldB", "coverage": 0.75, "n_fault": 4},
        ]
        g["metrics"]["no_fault_rates"]["by_fold"] = [
            {"fold": "foldA", "false_alarm_rate": 0.5, "n_normal": 2},
            {"fold": "foldB", "false_alarm_rate": 0.0, "n_normal": 2},
        ]
    params = _json(results / "re2-oracle-rq1-v1" / "summary.json")["statistics"]["params"]
    summary["statistics"] = {"comparisons": [], "intervals": [], "not_run": [], "params": params}
    textio.write_text(out / "summary.json", json.dumps(summary))
    textio.write_text(results / "not_run.yaml", f"{OFF}: {{revises: {RQ3}}}\n")
    side = results / "rq3-intervals" / OFF
    side.mkdir(parents=True)
    scopes = {
        s: {"coverage": _interval(0.875, 0.625, 1.0), "aurc_difference": _interval(difference, -0.25, 0.0)}
        for s in ("ob", "ss", "tt", "pooled")
    }
    rates = {
        "false_alarm_rate": _interval(0.125, 0.0, 0.25),
        "wrong_no_fault_rate": _interval(0.5, 0.25, 0.75),
    }
    fit = {"lands_on_infinity": True, "m_fitted": 4, "m_literal": 3, "n_never": 1, "tau_nf_literal": 10.4624}
    literal: dict[str, Any] = {s: rates for s in ("ob", "ss", "tt", "pooled")}
    literal["held_out_fold"] = {"foldA": fit, "foldB": {**fit, "lands_on_infinity": False}}
    doc = {"experiment_id": OFF, "level": 0.95, "resamples": 2000, "intervals": scopes,
           "literal_tau_sensitivity": literal}  # fmt: skip
    textio.write_text(side / "summary.json", json.dumps(doc))
    textio.write_text(side / "rows.csv", "cluster\nob-1\n")
    return out


def _md(results: Path) -> dict[str, str]:
    return {k: v.decode() for k, v in generate.outputs(results, EXPERIMENTS).items()}


def _rows(table: str, start: str) -> list[str]:
    return [re.sub(r"<sup>\d+</sup>", "", line) for line in table.splitlines() if line.startswith(start)]


def test_table_7_has_v_minus_f_pooled_rows_and_the_runs_behind_each_set(results: Path) -> None:
    _revise(results)
    t7 = _md(results)["tables/t07-rq3-calibration.md"]
    ob = _rows(t7, f"| {RQ3} | crossfit2 (rcaeval-re2) | 0.1 | ob | veyltrace:off | 0.500")
    assert len(ob) == 1 and ob[0].endswith(f"| 8 | 8 | 0 | none | 4 | {STAND_IN} |")
    assert "| 0.250 | 0.375 | -0.125 [-0.250, 0.000] | 0.250 | 0.000 | 1.000 | 0.750 |" in ob[0]
    assert f"| {OFF} | crossfit2" not in t7  # the revision's own rows are not printed twice (gap 35)
    pooled = _rows(t7, f"| {RQ3} | crossfit2 (rcaeval-re2) | 0.1 | pooled | veyltrace:off | ")
    assert len(pooled) == 2 and pooled[0].count("revised") > 10  # the pre-registered slot, then its revision
    assert "| 0.875 [0.625, 1.000] | no value |" in pooled[1] and "| -0.125 [-0.250, 0.000] |" in pooled[1]
    assert pooled[1].endswith(f"| n/a | n/a | n/a | n/a | n/a | {STAND_IN} |")
    assert "| Median set size |" in t7 and "| NO_FAULT precision | NO_FAULT recall |" in t7
    assert "default_tau with calibrated = false" in t7  # the τ_nf fallback is in the caption (gap 32)


def test_v_minus_f_must_be_the_difference_of_the_two_areas(results: Path) -> None:
    _revise(results, difference=0.5)
    with pytest.raises(ConfigError, match="AURC V − F"):
        generate.outputs(results, EXPERIMENTS)


def test_table_7b_has_a_row_per_held_out_fold(results: Path) -> None:
    _revise(results)
    t7b = _md(results)["tables/t07b-rq3-folds.md"]
    rows = _rows(t7b, f"| {RQ3} | crossfit2 (rcaeval-re2) | ob | veyltrace:off |")
    assert rows == [
        f"| {RQ3} | crossfit2 (rcaeval-re2) | ob | veyltrace:off | {'revised | ' * 5}{RQ3} (pre-registered; "
        f"revised as {OFF}) |",
        f"| {RQ3} | crossfit2 (rcaeval-re2) | ob | veyltrace:off | foldA | 4 | 1.000 | 2 | 0.500 "
        f"| {STAND_IN} |",
        f"| {RQ3} | crossfit2 (rcaeval-re2) | ob | veyltrace:off | foldB | 4 | 0.750 | 2 | 0.000 "
        f"| {STAND_IN} |",
    ]


def test_table_7c_reports_the_literal_tau_sensitivity(results: Path) -> None:
    _revise(results)
    t7c = _md(results)["tables/t07c-rq3-tau-sensitivity.md"]
    assert (
        f"| {RQ3} | veyltrace:off | held-out foldA | 10.462 | yes | 1 | 3 | 4 | n/a |"
        in _rows(t7c, f"| {RQ3} | veyltrace:off | held-out foldA")[0]
    )
    assert f"| {RQ3} | veyltrace:off | held-out foldB | 10.462 | no |" in t7c
    (pooled,) = _rows(t7c, f"| {RQ3} | veyltrace:off | pooled |")
    assert "| 0.125 [0.000, 0.250] | 0.500 [0.250, 0.750] |" in pooled  # literal τ_nf, rq3-intervals
    assert "20261121-ak-calibration-fit-conventions" in t7c


def test_an_undefined_no_fault_rate_says_why(results: Path) -> None:
    path = results / RQ3 / "summary.json"
    doc = _json(path)
    ob = next(g for g in doc["groups"] if g["dataset"] == "re2-ob" and g["method"] == "veyltrace:off")
    rates = ob["metrics"]["no_fault_rates"]
    rates.update(n_normal=0, false_alarm_rate=None, no_fault_recall=None)  # no normal windows
    ss = next(g for g in doc["groups"] if g["dataset"] == "re2-ss" and g["method"] == "veyltrace:off")
    ss["metrics"]["no_fault_rates"].update(
        false_alarm_rate=1.0, wrong_no_fault_rate=0.0, no_fault_precision=None
    )
    textio.write_text(path, json.dumps(doc))
    t7 = _md(results)["tables/t07-rq3-calibration.md"]
    assert NO_NORMAL in t7 and NO_DECLARED in t7
    assert cells.UNDEFINED_NOTE not in t7.split("Notes:")[1].split("Sources:")[0]


def _side_results(results: Path) -> None:
    """An rq5-ai-cost summary and a perf-o11 CSV of the slowest laptop, as committed (R4)."""
    ai = results / "rq5-ai-cost"
    ai.mkdir()
    entry = {"model_wall_ms_p50": 175544.4, "model_wall_ms_p95": 236209.5, "n": 3,
             "status": {"complete": 2, "failed": 1}, "tokens_in_p50": 5983.0, "tokens_in_p95": 6260.0,
             "tokens_out_p50": 1521.0, "tokens_out_p95": 2048.0,
             "turns_p50": 2.0, "turns_p95": 2.0}  # fmt: skip
    doc = {"experiment_id": RQ2, "source": "replay/recording/replay.csv tier 1", "systems": {"ob": entry}}
    textio.write_text(ai / "summary.json", json.dumps(doc))
    textio.write_text(ai / f"{RQ2}.csv", "dataset,system\n")
    perf = results / "perf-o11"
    perf.mkdir()
    head = "case,system,pass,outcome,wall_ms,peak_rss_mb,alert_ms,infralume_ms\n"
    body = "c1,re2-ob,1,ok,23117.3,467.3,17.7,4524.7\nc1,re2-ob,2,ok,17826.4,472.0,24.2,\n"
    textio.write_text(perf / "i5-1135g7.csv", head + body)
    textio.write_text(perf / "README.md", "# perf-o11\n")


def _replay_brief(results: Path) -> None:
    """re2-oracle-rq2-v1's brief arm as replayed rows: ai_mode replay, no cost columns, null cost."""
    path = results / RQ2 / "per_case.csv"
    rows = list(csv.DictReader(textio.read_text(path).splitlines()))
    for r in rows:
        if r["method"] == "veyltrace:brief":
            r.update(ai_mode="replay", wall_ms="", peak_rss_mb="", tokens_in="", tokens_out="")
    out = [",".join(rows[0])] + [",".join(r.values()) for r in rows]
    textio.write_text(path, "\n".join(out) + "\n")
    doc = _json(results / RQ2 / "summary.json")
    for g in doc["groups"]:
        if g["method"] == "veyltrace:brief":
            g["metrics"]["cost"] = {k: (0 if k == "n_cost" else None) for k in g["metrics"]["cost"]}
    textio.write_text(results / RQ2 / "summary.json", json.dumps(doc))


def test_tables_8b_and_8c_read_the_committed_side_results(results: Path) -> None:
    _side_results(results)
    _replay_brief(results)
    files = _md(results)
    t8b = files["tables/t08b-rq5-ai-cost.md"]
    row = f"| Relentra brief proposer (recorded) | {RQ2} | ob | veyltrace:brief, agent-only:brief "
    row += "| 175544 | 236210 "
    assert row + "| 5983 | 6260 | 1521 | 2048 | 2 | 2 | 3 | complete 2, failed 1 | rq5-ai-cost |" in t8b
    assert "| Causivra narration |" in t8b and "template-narrated, with no model call (#520)" in t8b
    assert f"- {RQ2}: commit" in t8b and "- rq5-ai-cost: sha256 " in t8b
    t8c = files["tables/t08c-rq5-slowest-laptop.md"]
    assert "| Case | System | Outcome | Wall (ms) | Peak RSS (MiB) | alert (ms) | infralume (ms) |" in t8c
    assert _rows(t8c, "| c1 |") == ["| c1 | re2-ob | ok | 17826 | 472 | 24 | n/a | perf-o11 |"]  # pass 2 only
    t8 = files["tables/t08-rq5-cost.md"]
    assert rq56.REPLAYED.format(rq56.RECORDED) in t8  # the replayed arm points at Table 8b (gap 43)


def test_without_side_results_tables_8b_and_8c_say_so(results: Path) -> None:
    files = _md(results)
    assert rq56.NO_AI_COST in files["tables/t08b-rq5-ai-cost.md"]
    assert rq56.NO_PERF in files["tables/t08c-rq5-slowest-laptop.md"]
    assert "not run" not in files["tables/t08b-rq5-ai-cost.md"].split("Notes:")[1]


def test_a1_lists_every_experiment_with_the_reason_of_missing_cost(results: Path) -> None:
    _revise(results)
    a1 = _md(results)["tables/a1-cost-all.md"]
    baselines = _rows(a1, "| re2-oracle-baselines-r05 | ob | rcaeval:baro |")
    assert len(baselines) == 1 and baselines[0].count("n/a") == 9  # does not list cost (gap 51)
    assert rq56.HELD_OUT_SUM in a1  # held-out restarts sum two runs (gap 50)
    assert f"| {OFF} | ob |" not in a1  # the revision only stands in for the pre-registered id (gap 49)
    ctx = context.context(results, EXPERIMENTS)
    exp, res = ctx.spec("re2-oracle-rq1-v1"), ctx.get("re2-oracle-rq1-v1")
    slate = [m.model_copy(update={"kind": "causatrix"}) if m.id == "simplerca" else m for m in exp.methods]
    group = res.group("re2-ob", "ob", "simplerca")
    assert group is not None
    no_cost = group.model_copy(update={"metrics": group.metrics.model_copy(update={"cost": None})})
    groups = {**res._groups, ("re2-ob", "ob", "simplerca"): no_cost}  # pyright: ignore[reportPrivateUsage]  # a slate group's null cost
    nulled = replace(res, _groups=groups)
    cell = rq56._cost_cell(  # pyright: ignore[reportPrivateUsage]  # the slate-reuse reason (gaps 44, 47)
        exp.model_copy(update={"methods": slate}), nulled, "re2-ob", "ob", "simplerca", "wall_ms_p50", None
    )
    assert cell == cells.not_applicable(rq56.SLATE_REUSE)


def test_fig_6_has_v_minus_f_and_says_why_it_draws_no_curves(results: Path) -> None:
    _revise(results)
    files = generate.outputs(results, EXPERIMENTS)
    rows = list(csv.DictReader(files["figures/fig6-risk-coverage.csv"].decode().splitlines()))
    diff = [r for r in rows if r["panel"] == "ob" and r["x"] == "AURC V − F"]
    assert [(r["series"], r["experiment"], r["value"], r["low"], r["high"]) for r in diff] == [
        ("veyltrace:off", RQ3, "", "", ""),
        ("veyltrace:off", OFF, "-0.125", "-0.25", "0.0"),
        ("veyltrace:brief", RQ3, "", "", ""),
    ]
    assert "LLM budget" in diff[2]["status"]  # the cut arm cites the cut (gap 41)
    assert "curves not drawn" in files["figures/fig6-risk-coverage-ob.svg"].decode()
