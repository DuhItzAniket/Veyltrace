"""RQ4 tables and figures (R-17 #46, audit gaps 52-71): Tables 10-12 show the Causatrix rankers
alone, coverage and set size next to the calibrated unperturbed reference (re2-oracle-rq3-v1 and
its 04 §12 revision), H4b's selective accuracy with its CONFIRMED count and the reason a share is
undefined; the ablation cells carry 04 §5.2's names and order; Fig 8 adds the status mix.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from veyltrace_bench.experiment import load_experiment
from veyltrace_bench.tables import cells, context, generate, rq4
from veyltrace_bench.tables.results import NO_POOLED, NO_VALUE, load, read_register
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_text_lf

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
RQ3, OFF = "re2-oracle-rq3-v1", "re2-oracle-rq3-off-v1"
SELECTIVE = {"ac_at_1_confirmed": 0.75, "answer_rate_confirmed": 0.5, "ac_at_1_likely_or_better": 0.625,
             "answer_rate_likely_or_better": 0.875, "n_fault": 8}  # fmt: skip


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(textio.read_text(path))
    return data


def _md(results: Path, name: str) -> str:
    return generate.outputs(results, EXPERIMENTS)[f"tables/{name}.md"].decode()


def _selective(results: Path, **values: float | None) -> None:
    """Give re2-oracle-rq3-v1's ob veyltrace:off group a selective_accuracy entry."""
    path = results / RQ3 / "summary.json"
    doc = _json(path)
    for group in doc["groups"]:
        if (group["dataset"], group["method"]) == ("re2-ob", "veyltrace:off"):
            group["metrics"]["selective_accuracy"] = {**SELECTIVE, **values}
    textio.write_text(path, json.dumps(doc))


def _revise(results: Path) -> None:
    """re2-oracle-rq3-v1's fixture results become its AI-off revision's, with a pooled coverage
    interval in rq3-intervals (as test_tables_semantics builds them)."""
    out = results / OFF
    (results / RQ3).rename(out)
    yaml = EXPERIMENTS / f"{OFF}.yaml"
    manifest = _json(out / "manifest.json")
    manifest.update(experiment_id=OFF, experiment_sha256=sha256_text_lf(yaml),
                    experiment=load_experiment(yaml).model_dump(mode="json"))  # fmt: skip
    textio.write_text(out / "manifest.json", json.dumps(manifest))
    summary = _json(out / "summary.json")
    summary["experiment_id"] = OFF
    summary["groups"] = [g for g in summary["groups"] if g["method"] == "veyltrace:off"]
    params = _json(results / "re2-oracle-rq1-v1" / "summary.json")["statistics"]["params"]
    summary["statistics"] = {"comparisons": [], "intervals": [], "not_run": [], "params": params}
    textio.write_text(out / "summary.json", json.dumps(summary))
    textio.write_text(results / "not_run.yaml", f"{OFF}: {{revises: {RQ3}}}\n")
    side = results / "rq3-intervals" / OFF
    side.mkdir(parents=True)
    scopes = {
        s: {"coverage": {"estimate": 0.875, "low": 0.625, "high": 1.0}} for s in ("ob", "ss", "tt", "pooled")
    }
    doc = {"experiment_id": OFF, "level": 0.95, "resamples": 2000, "intervals": scopes}
    textio.write_text(side / "summary.json", json.dumps(doc))
    textio.write_text(side / "rows.csv", "cluster\nob-1\n")


def _rows(text: str, start: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(start)]


def test_the_rankers_alone_are_kept_at_every_point(results: Path) -> None:
    """Gaps 53, 63, 69: 04 §6 pre-registers the rankers alone for every RQ4 row."""
    ctx = context.context(results, EXPERIMENTS)
    rankers = [m.id for m in ctx.spec("re2-shift-m60-v1").methods if m.kind == "causatrix"]
    assert len(rankers) == 7 and set(rankers) <= set(rq4.kept(ctx.spec("re2-shift-m60-v1")))
    assert "causatrix:change_prox" in rq4.kept(ctx.spec("rcaevalc-pi0-l6-v1"))
    assert "causatrix:nsigma" in rq4.kept(ctx.spec("re2-drop-metrics-v1"))
    shift = _md(results, "t10-rq4-shift")
    assert _rows(shift, "| -60 s | all | ob | causatrix:nsigma |")


def test_coverage_columns_and_the_calibrated_reference_rows(results: Path) -> None:
    """Gaps 54, 62, 70: coverage and set size per cell; rq1 (uncalibrated) does not list them, so
    re2-oracle-rq3-v1's rows are the 0 s reference, and they are n/a for a method without a verdict."""
    shift = _md(results, "t10-rq4-shift")
    assert "| Coverage | Coverage gap | Mean set size |" in shift
    ref = _rows(shift, "| 0 s | all | ob | veyltrace:off |")
    assert len(ref) == 2 and ref[0].endswith("| re2-oracle-rq1-v1 @ fixture |")
    assert ref[1].endswith("| re2-oracle-rq3-v1 @ fixture |") and "| 0.875<sup>" in ref[1]
    assert "the experiment does not list the metric `coverage`" in shift  # rq1's cells
    assert "whose verdicts are uncalibrated (split none)" in shift
    for name in ("t11-rq4-ablation", "t12-rq4-rcaevalc"):
        assert "| Coverage | Coverage gap | Mean set size |" in _md(results, name)
    assert "| AC@1 | AC@3 | Retrieval@K | Lift@1 | AC@1 − Chance@1 | Decoy ranked first |" in _md(
        results, "t12-rq4-rcaevalc"
    )  # gap 68
    ablation = _md(results, "t11-rq4-ablation")
    assert len(_rows(ablation, "| none | all | ob | veyltrace:off |")) == 2


def test_the_reference_pairs_with_its_revision(results: Path) -> None:
    """R1: re2-oracle-rq3-v1 reads "revised as", its revision's rows follow, and the revision's
    pooled coverage comes from rq3-intervals."""
    _revise(results)
    shift = _md(results, "t10-rq4-shift")
    ob = _rows(shift, "| 0 s | all | ob | veyltrace:off |")
    assert [r.rstrip(" |").rsplit("| ", 1)[1] for r in ob] == [
        "re2-oracle-rq1-v1 @ fixture",
        f"{RQ3} (pre-registered; revised as {OFF})",
        f"{OFF} @ fixture (revises {RQ3})",
    ]
    assert "| 0 s | all | ob | veyltrace:off | revised<sup>" in ob[1]
    pooled = _rows(shift, "| 0 s | all | pooled | veyltrace:off |")[-1]
    assert "| 0.875 [0.625, 1.000] |" in pooled and pooled.endswith(f"| {OFF} @ fixture (revises {RQ3}) |")
    assert f"re2-oracle-rq3-v1 (revised as {OFF})" in shift  # the caption names the revision
    ablation = _md(results, "t11-rq4-ablation")
    assert f"re2-oracle-rq1-v1 and {OFF} do not list selective_accuracy" in ablation


def test_the_ablation_cells_have_04_5_2_names_and_order(results: Path) -> None:
    """Gaps 64, 67: one source dropped in 04 §5.2 order, then "metrics only"."""
    ctx = context.context(results, EXPERIMENTS)
    labels = [label for label, _ in rq4.drops(ctx)]
    assert labels == ["drop metrics", "drop logs", "drop traces", "drop events", "metrics only"]
    assert dict(rq4.drops(ctx))["metrics only"] == "re2-metrics-only-v1"
    rows = list(
        csv.DictReader(
            generate.outputs(results, EXPERIMENTS)["figures/fig8-ablation.csv"].decode().splitlines()
        )
    )
    ob = [r for r in rows if r["panel"] == "ob"]
    assert list(dict.fromkeys(r["series"] for r in ob)) == ["none", *labels]
    assert list(dict.fromkeys(r["x"] for r in ob)) == ["AC@1", "CONFIRMED share", "CONFIRMED or LIKELY share"]
    none = next(r for r in ob if r["series"] == "none" and r["x"] == "CONFIRMED share")
    assert none["status"] == "not applicable: the experiment does not list the metric `selective_accuracy`"


def test_selective_cells_count_confirmed_verdicts_and_say_why_they_are_null(results: Path) -> None:
    """Gaps 60, 61: CONFIRMED verdicts = answer rate × n_fault; no CONFIRMED verdict is named, not
    the generic null note; a pooled selective cell has no value (not "a count or a ratio")."""
    _selective(results)
    res = load(results, RQ3, read_register(results))
    assert res.metric("re2-ob", "ob", "veyltrace:off", "selective_accuracy", "n_confirmed") == cells.Cell("4")
    rate = res.metric("re2-ob", "ob", "veyltrace:off", "selective_accuracy", "answer_rate_confirmed")
    assert rate.text == "0.500" and rate.note is not None and "no interval" in rate.note
    ctx = context.context(results, EXPERIMENTS)
    spec = ctx.spec(RQ3)
    spec = spec.model_copy(update={"metrics": (*spec.metrics, "selective_accuracy")})
    pooled = rq4.pooled(spec, res, "veyltrace:off", rq4.SELECTIVE[0])
    assert pooled == cells.Cell(NO_VALUE, rq4.NO_POOLED_ENTRY.format("selective_accuracy"))
    assert rq4.pooled(spec, res, "veyltrace:off", rq4.SELECTIVE[1]).text == cells.UNDEFINED  # a count
    _selective(results, ac_at_1_confirmed=None, answer_rate_confirmed=0.0)
    res = load(results, RQ3, read_register(results))
    metric = rq4.SELECTIVE[0]
    null = res.metric("re2-ob", "ob", "veyltrace:off", metric[1], metric[2])
    got = rq4.reason(res, "re2-ob", "veyltrace:off", metric, "veyltrace", null)
    assert got == cells.not_applicable(rq4.NO_ANSWER.format("CONFIRMED", " (H4b is vacuous here)"))
    assert res.metric("re2-ob", "ob", "veyltrace:off", "selective_accuracy", "n_confirmed") == cells.Cell("0")


def test_a_share_that_is_not_k_of_n_is_an_error(results: Path) -> None:
    _selective(results, answer_rate_confirmed=0.3)  # 0.3 × 8 = 2.4
    res = load(results, RQ3, read_register(results))
    with pytest.raises(ConfigError, match="not k / n"):
        res.metric("re2-ob", "ob", "veyltrace:off", "selective_accuracy", "n_confirmed")


def test_null_robustness_cells_name_their_reason(results: Path) -> None:
    """A method without a verdict has no coverage; a group without a decoy case has no decoy share."""
    res = load(results, RQ3, read_register(results))
    null = cells.rate(None)
    assert rq4.reason(
        res, "re2-ob", "causatrix:rrf", rq4.COVERAGE[0], "causatrix", null
    ) == cells.not_applicable(rq4.NO_VERDICT)
    decoy = rq4.DECOY[5]
    assert decoy[2] == "decoy_ranked_first"
    assert rq4.reason(res, "re2-ob", "veyltrace:off", decoy, "veyltrace", null) == cells.not_applicable(
        rq4.NO_DECOY
    )
    unlisted = cells.not_applicable("x")
    assert rq4.reason(res, "re2-ob", "veyltrace:off", decoy, "veyltrace", unlisted) is unlisted


def test_a_pooled_value_without_an_interval_has_no_value_not_not_run(results: Path) -> None:
    """R1: the experiment ran, so a pooled cell without a committed interval is "no value"."""
    res = load(results, "re2-oracle-rq2-v1", read_register(results))
    cell = res.pooled("re2", "veyltrace:brief", "ac_at_1")
    assert cell == cells.Cell(NO_VALUE, NO_POOLED.format("re2", "ac_at_1"))


def test_fig7_takes_the_full_case_brief_point_with_its_interval(results: Path) -> None:
    """Gap 59: no shifted brief run has results, so Fig 7's 0 s brief point is rq2's own."""
    files = generate.outputs(results, EXPERIMENTS)
    rows = list(csv.DictReader(files["figures/fig7-shift.csv"].decode().splitlines()))
    brief = {r["panel"]: r for r in rows if r["x"] == "0" and r["series"] == "veyltrace:brief"}
    assert (brief["ob"]["value"], brief["ob"]["low"], brief["ob"]["status"]) == ("0.625", "0.5", "ok")
    assert brief["ob"]["source"] == "re2-oracle-rq2-v1 @ fixture"
    image = files["figures/fig7-shift-ob.svg"].decode()
    assert "computed from per_case.csv" not in image
    assert "H4a tests ±60 and ±120 s, other shifts are exploratory (04 §2)" in image
