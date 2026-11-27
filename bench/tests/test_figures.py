"""Figures (R-17e, #381): plain-data CSV of record plus deterministic SVG; not-run points are
listed in the CSV and never drawn as 0.
"""

from __future__ import annotations

import csv
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from veyltrace_bench.tables import cells, figures, generate, svg
from veyltrace_bench.tables.results import NO_GROUP, NO_INTERVAL, Point

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
    assert ob["Rerank@1"]["status"] == f"ok; {NO_INTERVAL}"  # and says so (04 §8)
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
    assert "points not plotted: " in image and " not run" in image and "(see the CSV status)" in image
    aurc = _rows(files["figures/fig6-risk-coverage.csv"])
    ob = {(r["series"], r["x"]): r["value"] for r in aurc if r["panel"] == "ob"}
    assert ob[("veyltrace:off", "AURC verifier")] == "0.25" and ob[("veyltrace:off", "AURC fused")] == "0.375"


def test_heatmap_marks_missing_cells_grey() -> None:
    image = svg.heatmap("t", ["a"], ["x", "y"], [[0.5, None]], "note")
    assert svg.NO_VALUE in image and "not run" not in image and "#dddddd" in image and "0.500" in image
    assert svg.heatmap("t", ["a"], ["x", "y"], [[0.5, None]], "note") == image


def test_fig7_has_one_0_s_point_per_series(results: Path) -> None:
    files = generate.outputs(results, EXPERIMENTS)
    shift = _rows(files["figures/fig7-shift.csv"])
    zero = [r for r in shift if r["x"] == "0"]
    assert [r["experiment"] for r in zero if r["series"] == "veyltrace:off"] == ["re2-oracle-rq1-v1"] * 3
    brief = {r["panel"]: r for r in zero if r["series"] == "veyltrace:brief"}
    assert brief["ob"]["value"] == "0.625" and brief["tt"]["value"] == ""  # rq2 on all cases (gap 52)
    assert len(zero) == len({(r["panel"], r["series"]) for r in zero})  # no duplicate x = 0 point


def test_a_long_note_wraps_inside_the_frame_and_grows_it() -> None:
    """Fig 8's one-line note ran past the 640 px edge: a note wraps to NOTE_CHARS per line and
    each further line makes the frame LINE_PX taller (viewBox included)."""
    note = " ".join(["2 of 18 points not plotted: 2 n/a (see the CSV status)"] * 4)
    for image in (
        svg.heatmap("t", ["a"], ["x"], [[0.5]], note),
        svg.lines("t", "x", "y", [0.0, 1.0], {"s": [(0.0, 0.5, None, None)]}, note),
    ):
        root = ET.fromstring(image)
        notes = [el.text or "" for el in root if el.get("fill") == "#555"]
        assert len(notes) > 1 and all(len(n) <= svg.NOTE_CHARS for n in notes) and " ".join(notes) == note
        height = svg.HEIGHT + svg.LINE_PX * (len(notes) - 1)
        assert root.get("height") == str(height) and root.get("viewBox") == f"0 0 {svg.WIDTH} {height}"
    assert ET.fromstring(svg.heatmap("t", ["a"], ["x"], [[0.5]], "note")).get("height") == str(svg.HEIGHT)
    gap = svg.placeholder("Fig. 5: t", "why")  # drawn text drops the generator's number, <title> keeps it
    assert '"middle">t</text>' in gap and '"middle">Fig. 5' not in gap and "<title>Fig. 5: t</title>" in gap


def test_heatmap_labels_round_as_the_tables() -> None:
    assert ">0.063<" in svg.heatmap("t", ["a"], ["x"], [[0.0625]], "note")  # ROUND_HALF_UP, as cells.fixed


def test_fig5_is_a_gap_with_its_reason_not_not_run(results: Path) -> None:
    """Gaps 17, 90: the experiment ran; the data is only in uncommitted run directories."""
    files = generate.outputs(results, EXPERIMENTS)
    rows = _rows(files["figures/fig5-predicate-requests.csv"])
    assert len(rows) == 1 and rows[0]["value"] == "" and rows[0]["experiment"] == "re2-oracle-rq2-v1"
    assert rows[0]["status"].startswith("no data in the committed results: ")
    assert rows[0]["source"] == "re2-oracle-rq2-v1 @ fixture"
    image = files["figures/fig5-predicate-requests.svg"].decode()
    assert "not run" not in image and "no data in the committed results" in image
    ET.fromstring(image)


@pytest.mark.parametrize(
    ("status", "word"),
    [
        ("not applicable: the experiment does not list the metric `selective_accuracy`", cells.UNDEFINED),
        ("undefined: null in summary.json", cells.UNDEFINED),
        ("not run: no committed results in bench/results", cells.NOT_RUN),
        ("revised as re2-oracle-rq3-off-v1 (04 §12, 25 Nov)", cells.REVISED),
        ("no data in the committed results: x", svg.NO_VALUE),
    ],
)
def test_a_point_without_a_value_reads_as_the_tables(status: str, word: str) -> None:
    """A metric the experiment does not list is "n/a" in a figure, as in its CSV status and the
    tables, never "no value"; "no value" is kept for a defined value no committed file holds."""
    assert figures.shown_as(Point(None, status=status)) == word


def test_heatmap_cells_and_footer_tell_n_a_from_no_value(results: Path) -> None:
    image = svg.heatmap("t", ["a"], ["x", "y"], [[0.5, None]], "note", [["", cells.UNDEFINED]])
    assert ">n/a<" in image and svg.NO_VALUE not in image
    files = generate.outputs(results, EXPERIMENTS)
    for path in (p for p in files if p.startswith("figures/fig8-ablation-") and p.endswith(".svg")):
        data = files[path].decode()
        listed = [r for r in _rows(files["figures/fig8-ablation.csv"]) if path.endswith(f"-{r['panel']}.svg")]
        n_a = sum(r["status"].startswith(cells.NOT_APPLICABLE) for r in listed)
        assert data.count(">n/a<") == n_a
        assert (f"{n_a} n/a" in data) is (n_a > 0)
