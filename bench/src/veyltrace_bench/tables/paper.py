"""Compact paper views and full-grid longtables of the generated tables (R-17, lead decision of
27 Nov).

Why: the full grids have up to 26 columns and 900 rows; no ACM column or page holds them, so LaTeX
floated them out of the PDF. The `.md` stays the authoritative full grid. For each table the main
text cites, `<name>-paper.tex` is a view of it: the headline columns its research question needs,
the rows chosen by their labels, optionally pivoted (one column per system), intervals stacked
under their point where columns are narrow, and notes as marks with their text below. A view
only chooses, reorders and places cells: every value it shows is a cell of the full table with the
same text and note (`Shown.origin` names it; a test checks every view). For every table,
`<name>-full.tex` is the full grid as a `longtable` for the appendix, which breaks across pages; its
columns are split into parts that fit the text width, each part repeating the row number and the
row's key columns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from veyltrace_bench.tables.cells import NOT_RUN, REVISED, Cell
from veyltrace_bench.tables.figures import SHIFT_SERIES
from veyltrace_bench.tables.render import (
    GENERATED,
    NO_SOURCE,
    SOURCE_COLUMN,
    Row,
    Table,
    source_lines,
    tex_cells,
    tex_escape,
)
from veyltrace_bench.tables.results import Results
from veyltrace_core.errors import ConfigError

PAPER_SUFFIX = "-paper"
FULL_SUFFIX = "-full"
RESULTS_PATH = "bench/results/tables"
ABSENT = frozenset({REVISED, NOT_RUN})  # a row reading only these shows no value of its own
#: A cell "<point> [<low>, <high>]<rest>", e.g. "0.083 [0.083, 0.084] (K=5)", which a stacked view
#: prints as the point over the interval.
INTERVAL = re.compile(r"^(\S+) (\[[^\]]*\].*)$")
#: `\\{}`: the interval starts with "[", which a bare `\\` would read as its optional skip.
STACK = r"\providecommand{\vtci}[2]{\begin{tabular}[t]{@{}l@{}}#1\\{}#2\end{tabular}}%"
TABCOLSEP = "3pt"  # a priori: half the LaTeX default, as dense result tables usually set it

# Full-grid layout (a priori, measured in acmart sigconf with Linux Libertine): the one-column text
# width is 506 pt (500 leaves a margin); a \scriptsize character of our cells is about 2.3 pt (digits)
# to 2.8 pt (letters) wide, 3.0 with room; each column adds 2 x TABCOLSEP of padding.
FULL_WIDTH_PT = 500.0
CHAR_PT = 3.0
PAD_PT = 6.0
WRAP_CHARS = 36  # a cell longer than this wraps inside its column


@dataclass(frozen=True)
class Pivot:
    """One row per distinct `index` tuple (and per `values` column when there are several), one
    column per distinct text of `across` (in order of first appearance), holding that value cell
    of the full-table row with that index and `across` text."""

    index: tuple[str, ...]
    across: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class View:
    """What a paper view shows of a table: `columns` (full-table names, in order) of the rows that
    match any alternative in `rows` ({column: allowed texts}; none keeps every row), or a `pivot`
    of those rows. `headers` shortens column names (listed below the table); `wrap` columns break
    lines (tabularx X); `stack` prints intervals under their point; `omit_absent` leaves out rows
    whose every shown value reads "revised" or "not run" and names their sources below."""

    columns: tuple[str, ...] = ()
    rows: tuple[Mapping[str, tuple[str, ...]], ...] = ()
    pivot: Pivot | None = None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    wrap: tuple[str, ...] = ()
    stack: bool = False
    omit_absent: bool = True


@dataclass(frozen=True)
class Shown:
    """One cell of a view: the full table's cell at `origin` (row, column), unchanged, or a label
    (`origin` None: a pivot row's value name, or blank where the full table has no such row).
    `mark` is a note of the view, never a value: which revision a row's values come from, or which
    other text the full table prints at a pivot position."""

    cell: Cell
    origin: tuple[int, int] | None
    mark: str | None = None


@dataclass(frozen=True)
class PaperTable:
    """A built view: one header row, body rows, per-column flags and provenance."""

    table: Table
    head: tuple[str, ...]
    body: tuple[tuple[Shown, ...], ...]
    wrap: tuple[bool, ...]
    values: tuple[bool, ...]  # per column: a value column (stackable), not a row label
    stack: bool
    sources: tuple[Results, ...]
    omitted: tuple[str, ...]  # source cells of rows left out for showing only revised / not run
    renamed: tuple[tuple[str, str], ...]  # (short header, full column name)
    shown_columns: int  # full-table columns the view draws on

    @property
    def shown_rows(self) -> int:
        return len({s.origin[0] for line in self.body for s in line if s.origin is not None})


# ------------------------------------------------------------------------------------ views

CI_COLUMNS = ("AC@1", "AC@3", "AC@5", "Rerank@1")  # 04 §9 headline accuracy of RQ1/RQ2
BRIEF = "veyltrace:brief"
OUTCOMES = "Outcomes ok/failed/timeout/no_alert/rejected"
COMPARISON = View(
    columns=("Scope", "A − B", "Kind", "Difference", "Sign-flip p (unadjusted)", "Holm p"),
    headers={"Sign-flip p (unadjusted)": "Sign-flip p"},
    wrap=("A − B", "Kind"),
    stack=True,
)
#: The view of each table the main text cites (lead decision, 27 Nov): the columns its RQ tests.
VIEWS: dict[str, View] = {
    "t03-datasets": View(
        columns=("Dataset", "Cases", "Excluded", "Fault cases", "Normal windows"),
        wrap=("Normal windows",),
        omit_absent=False,
    ),
    "t05-rq1-re2-oracle": View(columns=("System", "Method", *CI_COLUMNS)),
    "t05c-rq1-comparisons": COMPARISON,
    "t06-rq2-re2-oracle-rq2-v1": View(
        columns=("System", "Method", *CI_COLUMNS, OUTCOMES), headers={OUTCOMES: "Outcomes"}
    ),
    "t06c-rq2-comparisons": COMPARISON,
    "t06d-rq2-proposal-arms": View(  # H2b and H2c; the arms' accuracy is in the full grid
        columns=("System", "Method", "Metric", "Value", "Pairs"),
        rows=({"Metric": ("decoy_top1_change", "permutation_invariance")},),
        wrap=("Metric",),
        stack=True,
    ),
    "t07-rq3-calibration": View(
        columns=(
            "Experiment",
            "System",
            "Method",
            "Coverage",
            "Mean set size",
            "AURC V − F",
            "False-alarm rate",
            "Wrong NO_FAULT rate",
        ),
        headers={
            "Mean set size": "Set size",
            "False-alarm rate": "False alarm",
            "Wrong NO_FAULT rate": "Wrong NO_FAULT",
        },
        stack=True,
    ),
    "t08-rq5-cost": View(  # the deterministic path from its solo run, the AI arms from RQ2
        columns=(
            "System",
            "Method",
            "Wall p50 (ms)",
            "Wall p95 (ms)",
            "Peak RSS p50 (MiB)",
            "Peak RSS p95 (MiB)",
        ),
        rows=(
            {"Experiment": ("re2-oracle-rq1-v1",), "Method": ("veyltrace:off",)},
            {"Experiment": ("re2-oracle-rq2-v1",), "Method": ("veyltrace:brief", "agent-only:brief")},
        ),
        headers={
            "Wall p50 (ms)": "Wall p50",
            "Wall p95 (ms)": "Wall p95",
            "Peak RSS p50 (MiB)": "RSS p50",
            "Peak RSS p95 (MiB)": "RSS p95",
        },
    ),
    "t09-rq6-replay": View(
        columns=("Measurement", "Rate", "Runs", "Verdict reproduced"),
        headers={"Verdict reproduced": "Reproduced"},
        wrap=("Measurement",),
        stack=True,
    ),
    "t10-rq4-shift": View(  # Figure 7's series, AC@1 per system (H4a); brief shifted on the subset
        rows=(
            {"Method": tuple(m for m in SHIFT_SERIES if m != BRIEF), "Case set": ("all",)},
            {"Method": (BRIEF,)},
        ),
        pivot=Pivot(index=("Method", "Shift"), across="System", values=("AC@1",)),
    ),
    "t11-rq4-ablation": View(  # H4b: the share of CONFIRMED verdicts that are correct
        columns=("Sources", "System", "AC@1", "AC@1 among CONFIRMED", "CONFIRMED verdicts"),
        rows=({"Method": ("veyltrace:off",)},),
        headers={"AC@1 among CONFIRMED": "AC@1 conf.", "CONFIRMED verdicts": "Conf."},
    ),
    "t12-rq4-rcaevalc": View(  # H4c: veyltrace:off against naive-change on all RE2 cases
        rows=({"Method": ("veyltrace:off", "naive-change"), "Case set": ("all",)},),
        pivot=Pivot(index=("Method", "Grid point"), across="System", values=("AC@1", "Decoy ranked first")),
    ),
}


# ------------------------------------------------------------------------------------ build


def _index(table: Table, names: Sequence[str]) -> list[int]:
    missing = [n for n in names if n not in table.columns]
    if missing:
        raise ConfigError(f"paper view of {table.name}: no column {', '.join(map(repr, missing))}")
    return [table.columns.index(n) for n in names]


def _selected(table: Table, view: View) -> list[int]:
    """Row numbers matching any alternative of `view.rows`, in table order."""
    if not view.rows:
        return list(range(len(table.rows)))
    alternatives = [dict(zip(_index(table, list(alt)), alt.values(), strict=True)) for alt in view.rows]
    return [
        i
        for i, row in enumerate(table.rows)
        if any(all(row.cells[j].text in allowed for j, allowed in alt.items()) for alt in alternatives)
    ]


def _revision_mark(row: Row) -> str | None:
    src = row.source
    if src is None or src.stands_in_for is None:
        return None
    return f"values from {src.label}"


def _sources(rows: Sequence[Row]) -> tuple[Results, ...]:
    cited = {s.experiment_id: s for r in rows for s in (r.source, *r.also) if s is not None}
    return tuple(cited[k] for k in sorted(cited))


def _renamed(view: View, names: Sequence[str]) -> tuple[tuple[str, str], ...]:
    return tuple((view.headers[n], n) for n in names if n in view.headers)


def _plain(table: Table, view: View) -> PaperTable:
    cols = _index(table, view.columns)
    labels = {j for j in cols if j in table.key}
    seen: set[tuple[str, ...]] = set()
    body: list[tuple[Shown, ...]] = []
    kept: list[Row] = []
    omitted: dict[str, None] = {}
    for i in _selected(table, view):
        row = table.rows[i]
        value_texts = [row.cells[j].text for j in cols if j not in labels]
        if view.omit_absent and value_texts and all(t in ABSENT for t in value_texts):
            omitted[row.source.label if row.source else NO_SOURCE] = None
            continue
        texts = tuple(row.cells[j].text for j in cols)
        if texts in seen:  # a revision repeating, in every shown column, the row beside it
            continue
        seen.add(texts)
        mark = _revision_mark(row)
        body.append(tuple(Shown(row.cells[j], (i, j), mark if n == 0 else None) for n, j in enumerate(cols)))
        kept.append(row)
    return PaperTable(
        table=table,
        head=tuple(view.headers.get(table.columns[j], table.columns[j]) for j in cols),
        body=tuple(body),
        wrap=tuple(table.columns[j] in view.wrap for j in cols),
        values=tuple(j not in labels for j in cols),
        stack=view.stack,
        sources=_sources(kept),
        omitted=tuple(omitted),
        renamed=_renamed(view, view.columns),
        shown_columns=len(cols),
    )


def _ranked(keys: Sequence[tuple[str, ...]]) -> list[tuple[str, ...]]:
    """Distinct keys sorted by each component's first appearance, component by component."""
    if not keys:
        return []
    rank: list[dict[str, int]] = [{} for _ in keys[0]]
    for key in keys:
        for n, text in enumerate(key):
            rank[n].setdefault(text, len(rank[n]))
    return sorted(set(keys), key=lambda k: tuple(rank[n][t] for n, t in enumerate(k)))


def _pick(table: Table, rows: Sequence[int], column: int, used: list[Row]) -> Shown:
    """The cell of one pivot position: the first row in table order (a pre-registered experiment's
    before a revision's) that is not "revised", unless every row is. Another row there with a
    different text (a second experiment covering the same slot) is named in the cell's mark, so
    the view never hides a value the full table prints at that position."""
    if not rows:
        return Shown(Cell(""), None)
    ordered = sorted(rows, key=lambda i: _revision_mark(table.rows[i]) is not None)
    present = [i for i in ordered if table.rows[i].cells[column].text != REVISED] or ordered
    i, cell = present[0], table.rows[present[0]].cells[column]
    used.append(table.rows[i])
    others = [
        f"{src.label if (src := table.rows[k].source) else NO_SOURCE}: {table.rows[k].cells[column].text}"
        for k in present[1:]
        if table.rows[k].cells[column].text != cell.text
    ]
    marks = [m for m in (_revision_mark(table.rows[i]),) if m] + (
        ["the full table also has " + "; ".join(others)] if others else []
    )
    return Shown(cell, (i, column), "; ".join(marks) or None)


def _pivot(table: Table, view: View, pivot: Pivot) -> PaperTable:
    index = _index(table, pivot.index)
    (across,) = _index(table, [pivot.across])
    values = _index(table, pivot.values)
    chosen = _selected(table, view)
    key_of = {i: tuple(table.rows[i].cells[j].text for j in index) for i in chosen}
    groups: list[str] = []
    cells_at: dict[tuple[tuple[str, ...], str], list[int]] = {}
    first: dict[tuple[str, ...], int] = {}
    for i in chosen:
        group = table.rows[i].cells[across].text
        if group not in groups:
            groups.append(group)
        cells_at.setdefault((key_of[i], group), []).append(i)
        first.setdefault(key_of[i], i)
    multi = len(values) > 1
    body: list[tuple[Shown, ...]] = []
    used: list[Row] = []
    for key in _ranked(list(key_of.values())):
        for v in values:
            line = [Shown(table.rows[first[key]].cells[j], (first[key], j)) for j in index]
            if multi:
                line.append(Shown(Cell(view.headers.get(table.columns[v], table.columns[v])), None))
            line += [_pick(table, cells_at.get((key, g), []), v, used) for g in groups]
            body.append(tuple(line))
    head = [view.headers.get(table.columns[j], table.columns[j]) for j in index]
    head += [""] * int(multi) + groups
    labels = len(index) + int(multi)
    return PaperTable(
        table=table,
        head=tuple(head),
        body=tuple(body),
        wrap=tuple(False for _ in head),
        values=tuple(n >= labels for n in range(len(head))),
        stack=view.stack,
        sources=_sources(used),
        omitted=(),
        renamed=_renamed(view, [*pivot.index, *pivot.values]),
        shown_columns=len(index) + 1 + len(values),
    )


def build(table: Table, view: View) -> PaperTable:
    """The view of `table`; a column the table lacks is a ConfigError."""
    if view.pivot is not None:
        return _pivot(table, view, view.pivot)
    return _plain(table, view)


# ------------------------------------------------------------------------------------ LaTeX


class _Marks:
    """Note numbers of a view by first appearance, as the full table numbers its own."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def marker(self, note: str) -> str:
        if note not in self.texts:
            self.texts.append(note)
        return rf"\textsuperscript{{{self.texts.index(note) + 1}}}"


def _paper_cell(shown: Shown, stack: bool, marks: _Marks) -> str:
    text = shown.cell.text
    found = INTERVAL.match(text) if stack and shown.origin is not None else None
    out = rf"\vtci{{{tex_escape(found[1])}}}{{{tex_escape(found[2])}}}" if found else tex_escape(text)
    return out + "".join(marks.marker(n) for n in (shown.cell.note, shown.mark) if n is not None)


def _labels(pt: PaperTable) -> int:
    """The leading label columns, whose repeats a view prints once per group."""
    n = 0
    while n < len(pt.values) and not pt.values[n]:
        n += 1
    return n


def paper_latex(pt: PaperTable) -> str:
    """A `table` float (unwrapped by the paper's \\resulttable) holding the view, \\footnotesize,
    tabularx to the line width when a column wraps; marks, the columns it renamed, what it leaves
    out and its sources follow in \\scriptsize."""
    table, marks = pt.table, _Marks()
    lead = _labels(pt)
    rows: list[str] = []
    previous: tuple[str, ...] = ()
    for line in pt.body:
        texts = tuple(s.cell.text for s in line[:lead])
        cells = [_paper_cell(s, pt.stack, marks) for s in line]
        for n in range(lead):  # a label equal to the row above (with all labels before it) prints once
            if texts[: n + 1] == previous[: n + 1] and line[n].mark is None:
                cells[n] = ""
        previous = texts
        rows.append(" & ".join(cells) + r" \\")
    spec = "".join(r">{\raggedright\arraybackslash}X" if w else "l" for w in pt.wrap)
    env = ("tabularx", r"{\linewidth}") if any(pt.wrap) else ("tabular", "")
    lines = [
        f"% {GENERATED}",
        f"% Paper view of {table.name} (paper.py); the full grid is {table.name}{FULL_SUFFIX}.tex and .md.",
        r"\begin{table}[t]",
        r"\centering",
        rf"\caption{{{tex_escape(table.title)}. {tex_escape(table.caption)}}}",
        rf"\label{{tab:{table.name}{PAPER_SUFFIX}}}",
        r"\footnotesize",
        rf"\setlength{{\tabcolsep}}{{{TABCOLSEP}}}%",
        *([STACK] if pt.stack else []),
        rf"\begin{{{env[0]}}}{env[1]}{{@{{}}{spec}@{{}}}}",
        r"\hline",
        " & ".join(tex_escape(h) for h in pt.head) + r" \\",
        r"\hline",
        *rows,
        r"\hline",
        rf"\end{{{env[0]}}}",
        r"\par\smallskip\scriptsize\raggedright",
    ]
    if marks.texts:
        notes = (rf"\textsuperscript{{{i}}}{_text(n)}" for i, n in enumerate(marks.texts, 1))
        lines.append("; ".join(notes) + r".\par")
    if pt.renamed:
        lines.append("Columns: " + "; ".join(f"{_text(s)}: {_text(f)}" for s, f in pt.renamed) + r".\par")
    scope = (
        f"This view shows {pt.shown_rows} of {len(table.rows)} rows and draws on {pt.shown_columns} of "
        f"{len(table.columns)} columns"
    )
    if pt.omitted:
        scope += "; left out as revised or not run in every shown column: " + "; ".join(pt.omitted)
    scope += f". Every row, column, note and file hash: the appendix and {RESULTS_PATH}/{table.name}.md."
    lines.append(_text(scope) + r"\par")
    labels = [s.label for s in pt.sources] or [f"none: every row has {NO_SOURCE}"]
    lines.append(_text("Sources: " + "; ".join(labels) + ".") + r"\par")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def _text(value: str) -> str:
    """Header, note and source text, which may break after a "/" (paths, URLs, a/b/c headers)."""
    return tex_escape(value).replace("/", r"/\allowbreak{}")


def _widths(table: Table) -> list[int]:
    """Characters each full-grid column needs (the source column last): its longest cell (a note
    mark counted as two) or its longest header word, at most WRAP_CHARS."""
    columns = [*table.columns, SOURCE_COLUMN]
    out: list[int] = []
    for j, name in enumerate(columns):
        cells = [
            len(r.cells[j].text) + 2 * (r.cells[j].note is not None)
            if j < len(table.columns)
            else len(r.source.label if r.source else NO_SOURCE)
            for r in table.rows
        ]
        out.append(min(max([*cells, *map(len, re.split(r"[ /]", name))]), WRAP_CHARS))
    return out


def full_parts(table: Table) -> list[list[int]]:
    """The full grid's non-key columns (indices; len(columns) is the source column) split into
    parts that fit FULL_WIDTH_PT next to the row number and the key columns each part repeats."""
    pt = [w * CHAR_PT + PAD_PT for w in _widths(table)]
    fixed = len(str(len(table.rows))) * CHAR_PT + PAD_PT + sum(pt[j] for j in table.key)
    parts: list[list[int]] = []
    used = fixed
    for j in (j for j in range(len(pt)) if j not in table.key):
        if parts and used + pt[j] <= FULL_WIDTH_PT:
            parts[-1].append(j)
            used += pt[j]
        else:
            parts.append([j])
            used = fixed + pt[j]
    return parts


def full_latex(table: Table) -> str:
    """The full grid as one `longtable` per column part, \\scriptsize, for \\resulttablefull (which
    defines \\vtfullcaption, \\vtfullnext, \\vtfullpart and \\vtfullcont), then every note, the
    sources with their hashes, and the generated caption."""
    columns = [*table.columns, SOURCE_COLUMN]
    body, notes = tex_cells(table)
    widths = _widths(table)

    def width(j: int) -> str:
        return f"{widths[j] * CHAR_PT:.1f}pt"

    parts = full_parts(table)
    lines = [
        f"% {GENERATED}",
        f"% Full grid of {table.name} (paper.py), {len(parts)} column part(s), for \\resulttablefull.",
        r"\begingroup\scriptsize",
        rf"\setlength{{\tabcolsep}}{{{TABCOLSEP}}}%",
    ]
    for k, part in enumerate(parts, 1):
        shown = [*table.key, *part]
        spec = "r" + "".join(rf">{{\raggedright\arraybackslash}}p{{{width(j)}}}" for j in shown)
        head = " & ".join([r"\#", *(_text(columns[j]) for j in shown)]) + r" \\"
        lines += [
            *([rf"\vtfullnext{{{k}}}"] if k > 1 else []),
            rf"\begin{{longtable}}{{@{{}}{spec}@{{}}}}",
            (r"\vtfullcaption" if k == 1 else rf"\vtfullpart{{{k}}}{{{len(parts)}}}") + r" \\",
            r"\hline",
            head,
            r"\hline",
            r"\endfirsthead",
            rf"\multicolumn{{{len(shown) + 1}}}{{@{{}}l@{{}}}}{{\vtfullcont{{{k}}}{{{len(parts)}}}}} \\",
            r"\hline",
            head,
            r"\hline",
            r"\endhead",
            r"\hline",
            r"\endfoot",
            *(" & ".join([str(n), *(row[j] for j in shown)]) + r" \\" for n, row in enumerate(body, 1)),
            r"\end{longtable}",
        ]
    lines.append(r"\par\raggedright\noindent")
    lines += [rf"\textsuperscript{{{i}}} {_text(n)}\par" for i, n in enumerate(notes, 1)]
    lines += [rf"\noindent Source: {_text(s)}\par" for s in source_lines(table)]
    lines.append(rf"\noindent Generated caption: {_text(table.title)}. {_text(table.caption)}\par")
    lines.append(r"\endgroup")
    return "\n".join(lines) + "\n"
