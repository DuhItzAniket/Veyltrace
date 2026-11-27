"""Paper views and full-grid longtables (R-17 #46, lead decision of 27 Nov): every value a paper
view shows is the full table's cell, unchanged; views pivot, filter and leave out rows as stated;
the full grid's column parts fit the text width and repeat each row's key."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import cells, generate, paper
from veyltrace_bench.tables.context import context
from veyltrace_bench.tables.render import SOURCE_COLUMN, Row, Table, latex, markdown, tex_escape
from veyltrace_bench.tables.results import Results
from veyltrace_core.errors import ConfigError

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables" / "results"
COMMITTED = BENCH / "results"
STACKED = re.compile(r"\\vtci\{([^{}]*)\}\{([^{}]*)\}")


def _tables(results: Path) -> dict[str, Table]:
    ctx = context(results, EXPERIMENTS)
    return {t.name: t for build in generate.BUILDERS for t in generate.paired(build, ctx)}


def _unstacked(tex: str) -> str:
    return STACKED.sub(r"\1 \2", tex)


def _check_views(tables: dict[str, Table]) -> int:
    """Every view's shown value is its origin cell (text and note), printed as the full grid
    prints it; returns how many values were checked."""
    checked = 0
    for name, view in paper.VIEWS.items():
        table = tables[name]
        built = paper.build(table, view)
        paper_tex = _unstacked(paper.paper_latex(built))
        full_tex = paper.full_latex(table)
        for line in built.body:
            assert len(line) == len(built.head), name
            for shown in line:
                if shown.origin is None:
                    continue
                i, j = shown.origin
                assert table.rows[i].cells[j] == shown.cell, (name, shown)
                text = tex_escape(shown.cell.text)
                assert text in paper_tex and text in full_tex, (name, text)
                checked += 1
    return checked


@pytest.fixture(scope="module")
def committed() -> dict[str, Table]:
    return _tables(COMMITTED)


def test_every_paper_view_shows_the_full_tables_values_unchanged(committed: dict[str, Table]) -> None:
    assert set(paper.VIEWS) <= set(committed)
    assert _check_views(committed) > 500


def test_views_also_build_on_the_fixtures(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES, tmp_path / "results")
    _check_views(_tables(tmp_path / "results"))


def test_outputs_add_a_full_grid_per_table_and_a_view_per_cited_table(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES, tmp_path / "results")
    files = generate.outputs(tmp_path / "results", EXPERIMENTS)
    names = {p.removeprefix("tables/").removesuffix(".md") for p in files if p.endswith(".md")}
    assert {f"tables/{n}{paper.FULL_SUFFIX}.tex" for n in names} <= set(files)
    papers = {p for p in files if p.endswith(f"{paper.PAPER_SUFFIX}.tex")}
    assert papers == {f"tables/{n}{paper.PAPER_SUFFIX}.tex" for n in paper.VIEWS}


def _src(eid: str, *, stands_in_for: str | None = None, revised_as: tuple[str, ...] = ()) -> Results:
    return Results(eid, commit="0123456789abcdef", stands_in_for=stands_in_for, revised_as=revised_as)


def _table(rows: list[tuple[tuple[str, ...], Results]]) -> Table:
    return Table(
        "t99-demo",
        "Table 99: demo",
        "Protocol: none.",
        ("System", "Method", "AC@1", "Count"),
        tuple(Row(tuple(cells.text(t) for t in texts), src) for texts, src in rows),
        key=(0, 1),
    )


def test_a_plain_view_filters_omits_absent_rows_and_drops_repeated_revisions() -> None:
    pre = _src("exp-v1", revised_as=("exp-off-v1",))
    rev = _src("exp-off-v1", stands_in_for="exp-v1")
    base = _src("base-v1")
    table = _table([
        (("ob", "off", "0.500 [0.400, 0.600]", "9"), base),
        (("ob", "off", cells.REVISED, cells.REVISED), pre),
        (("ob", "off", "0.500 [0.400, 0.600]", "9"), rev),  # same values: shown once
        (("ss", "off", "0.250 [0.100, 0.400]", "9"), rev),  # its own values: marked
        (("ss", "brief", "0.300 [0.200, 0.400]", "9"), base),
    ])  # fmt: skip
    view = paper.View(columns=("System", "AC@1"), rows=({"Method": ("off",)},), stack=True)
    built = paper.build(table, view)
    assert [[s.cell.text for s in line] for line in built.body] == [
        ["ob", "0.500 [0.400, 0.600]"],
        ["ss", "0.250 [0.100, 0.400]"],
    ]
    assert built.omitted == (pre.label,)
    assert built.body[1][0].mark == f"values from {rev.label}"
    tex = paper.paper_latex(built)
    assert r"\vtci{0.500}{[0.400, 0.600]}" in tex
    assert r"ss\textsuperscript{1} & \vtci{0.250}{[0.100, 0.400]}" in tex
    assert "values from exp-off-v1 @ 01234567" in tex and "shows 2 of 5 rows" in tex
    assert r"\begin{tabular}{@{}ll@{}}" in tex  # no wrap column: a natural-width tabular


def test_a_pivot_spreads_one_column_and_names_a_second_rows_other_value() -> None:
    a, b = _src("a-v1"), _src("b-v1")
    table = _table([
        (("ob", "off", "0.1", "1"), a),
        (("ss", "off", "0.2", "1"), a),
        (("ob", "nsigma", "0.3", "1"), a),
        (("ob", "off", "0.1", "1"), b),  # agrees with the first row
    ])  # fmt: skip
    view = paper.View(pivot=paper.Pivot(index=("Method",), across="System", values=("AC@1", "Count")))
    built = paper.build(table, view)
    assert built.head == ("Method", "", "ob", "ss")
    assert [[s.cell.text for s in line] for line in built.body] == [
        ["off", "AC@1", "0.1", "0.2"],
        ["off", "Count", "1", "1"],
        ["nsigma", "AC@1", "0.3", ""],  # no (nsigma, ss) row: blank, not a value
        ["nsigma", "Count", "1", ""],
    ]
    assert built.body[2][3].origin is None and built.body[0][2].mark is None
    clash = paper.build(_table([(("ob", "off", "0.1", "1"), a), (("ob", "off", "0.4", "1"), b)]), view)
    assert clash.body[0][2].cell.text == "0.1"  # the first row in table order
    assert clash.body[0][2].mark == f"the full table also has {b.label}: 0.4"
    assert clash.body[1][2].mark is None  # the second row agrees on Count
    with pytest.raises(ConfigError, match="no column 'Nope'"):
        paper.build(table, paper.View(columns=("System", "Nope")))


def test_the_full_grid_splits_columns_into_parts_that_repeat_the_key() -> None:
    wide = Table(
        "t98-wide",
        "Table 98: wide",
        "c",
        ("System", *(f"Metric {n}" for n in range(12))),
        (Row((cells.text("ob"), *(cells.text("0.083 [0.083, 0.084]") for _ in range(12))), None),),
    )
    parts = paper.full_parts(wide)
    assert len(parts) > 1 and sorted(j for part in parts for j in part) == list(range(1, 14))  # 13 = source
    tex = paper.full_latex(wide)
    assert tex.count(r"\begin{longtable}") == len(parts) and tex.count(r"\vtfullnext{") == len(parts) - 1
    assert tex.count(r"\vtfullcaption") == 1 and all(
        f"\\vtfullpart{{{k}}}" in tex for k in range(2, len(parts) + 1)
    )
    heads = [line for line in tex.splitlines() if line.startswith(r"\# & System &")]
    assert len(heads) == 2 * len(parts)  # first head and continued-page head per part
    assert SOURCE_COLUMN in heads[-1] and r"\allowbreak" not in heads[0]


def test_pdflatex_has_every_character_the_tables_print() -> None:
    row = Row((cells.text("τ_nf → +∞, λ = 2, π ≥ 0"),), None)
    tex = latex(Table("t", "T", "c", ("Name",), (row,)))
    assert r"$\tau$\_nf $\rightarrow$ +$\infty$, $\lambda$ = 2, $\pi$ $\geq$ 0" in tex
    assert tex.isascii() and markdown(Table("t", "T", "c", ("Name",), (row,))).count("τ_nf") == 1
