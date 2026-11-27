"""Figures (R-17e, #381): plain-data CSV of record plus deterministic SVG; not-run points are
listed in the CSV and never drawn as 0.
"""

from __future__ import annotations

import csv
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from veyltrace_bench.tables import generate, svg
from veyltrace_bench.tables.results import NO_GROUP, NO_INTERVAL

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    return root


def _rows(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(data.decode().splitlines()))


def test_figures_regenerate_identically_and_parse(results: Path, tmp_path: Path) -> None:
    files = generate.outputs(results, EXPERIMENTS)
    figures = {k: v for k, v in files.items() if k.startswith("figures/")}
    assert generate.outputs(shutil.copytree(results, tmp_path / "copy"), EXPERIMENTS) == files
    names = {Path(k).name for k in figures}
    assert {"fig4-retrieval-rerank.svg", "fig7-shift-ob.svg", "fig8-ablation-ob.svg", "fig9-rcaevalc-ob.svg",
            "fig5-predicate-requests.svg", "fig6-risk-coverage-ob.svg",
            "fig7-shift.csv"} <= names  # fmt: skip
    for path, data in figures.items():
        if path.endswith(".svg"):
            ET.fromstring(data)  # well-formed XML
        assert b"\r" not in data


def test_fig4_values_and_sources(results: Path) -> None:
    rows = _rows(generate.outputs(results, EXPERIMENTS)["figures/fig4-retrieval-rerank.csv"])
    ob = {r["x"]: r for r in rows if r["panel"] == "ob"}
    assert ob["AC@1"]["value"] == "0.5" and ob["AC@1"]["low"] == "0.375" and ob["AC@1"]["status"] == "ok"
    assert ob["Rerank@1"]["value"] == "0.571428571"  # exactly the summary value
    assert ob["Rerank@1"]["low"] == "" and ob["Rerank@1"]["high"] == ""  # a ratio has no interval
    assert ob["Rerank@1"]["status"] == f"ok; {NO_INTERVAL}"  # and says so (R3)
    assert ob["AC@1"]["source"] == "re2-oracle-rq1-v1 @ fixture"
    assert {r["experiment"] for r in rows} == {"re2-oracle-rq1-v1"} and rows[0]["commit"] == "fixture"
    tt = [r for r in rows if r["panel"] == "tt"]
    assert tt and all(r["value"] == "" and r["status"] == "not run: " + NO_GROUP for r in tt)


def test_not_run_points_are_listed_not_drawn(results: Path) -> None:
    files = generate.outputs(results, EXPERIMENTS)
    shift = _rows(files["figures/fig7-shift.csv"])
    assert any(r["status"].startswith("not run: no committed results") for r in shift)
    assert all(r["value"] == "" for r in shift if not r["status"].startswith("ok"))
    image = files["figures/fig7-shift-ob.svg"].decode()
    drawn = image.count("<circle")
    assert drawn == sum(1 for r in shift if r["panel"] == "ob" and r["status"].startswith("ok"))
    assert "points have no value (see the CSV status)" in image
    aurc = _rows(files["figures/fig6-risk-coverage.csv"])
    ob = {(r["series"], r["x"]): r["value"] for r in aurc if r["panel"] == "ob"}
    assert ob[("veyltrace:off", "AURC verifier")] == "0.25" and ob[("veyltrace:off", "AURC fused")] == "0.375"


def test_heatmap_marks_missing_cells_grey() -> None:
    image = svg.heatmap("t", ["a"], ["x", "y"], [[0.5, None]], "note")
    assert svg.NO_VALUE in image and "not run" not in image and "#dddddd" in image and "0.500" in image
    assert svg.heatmap("t", ["a"], ["x", "y"], [[0.5, None]], "note") == image


def test_fig7_takes_the_brief_0_s_point_from_the_subset(results: Path) -> None:
    files = generate.outputs(results, EXPERIMENTS)
    shift = _rows(files["figures/fig7-shift.csv"])
    zero = [r for r in shift if r["x"] == "0"]
    assert [r["experiment"] for r in zero if r["series"] == "veyltrace:off"] == ["re2-oracle-rq1-v1"] * 3
    brief = {r["panel"]: r for r in zero if r["series"] == "veyltrace:brief"}
    assert brief["ob"]["value"] == "0.5" and brief["ss"]["value"] == "1.0" and brief["tt"]["value"] == ""
    assert brief["ob"]["source"] == "re2-oracle-rq2-v1 @ fixture (computed from per_case.csv, 90-case subset)"
    assert len(zero) == len({(r["panel"], r["series"]) for r in zero})  # no duplicate x = 0 point
    assert (
        "veyltrace:brief at 0 s computed from per_case.csv, 90-case subset"
        in files["figures/fig7-shift-ob.svg"].decode()
    )


def test_heatmap_labels_round_as_the_tables() -> None:
    assert ">0.063<" in svg.heatmap("t", ["a"], ["x"], [[0.0625]], "note")  # ROUND_HALF_UP, as cells.fixed
