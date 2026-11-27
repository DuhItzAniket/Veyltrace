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
from dataclasses import dataclass, field, replace

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
    tex_title,
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
    whose every shown value reads "revised" or "not run" and names their sources below. `caption`
    describes exactly the rows and columns the view shows (the full table's caption describes
    columns a view drops); the LaTeX adds a pointer to the full grid. Empty: the table's title."""

    caption: str = ""
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
    caption: str = ""  # the view's own caption (View.caption)

    @property
    def shown_rows(self) -> int:
        return len({s.origin[0] for line in self.body for s in line if s.origin is not None})


# ------------------------------------------------------------------------------------ views

CI_COLUMNS = ("AC@1", "AC@3", "AC@5", "Rerank@1")  # 04 §9 headline accuracy of RQ1/RQ2
BRIEF = "veyltrace:brief"
OUTCOMES = "Outcomes ok/failed/timeout/no_alert/rejected"
#: Shared by the view captions that show accuracy with intervals (04 §8 and the tables' captions).
MISSES = "failed, timed-out, no-alert, rejected and unranked runs count as misses"
COMPARISON_RULE = (
    "per scope, the pair A − B, the Kind of test, the paired Difference with its 95% interval below "
    "it, the unadjusted sign-flip p and the Holm p within the family; non-inferiority is decided by "
    "the unadjusted interval against the pre-registered margin, superiority by the Holm-adjusted "
    "sign-flip p (04 §8). Protocol: see Sources."
)


def _comparison(caption: str) -> View:
    return View(
        caption=caption,
        columns=("Scope", "A − B", "Kind", "Difference", "Sign-flip p (unadjusted)", "Holm p"),
        headers={"Sign-flip p (unadjusted)": "Sign-flip p"},
        wrap=("A − B", "Kind"),
        stack=True,
    )


#: The view of each table the main text cites (lead decision, 27 Nov): the columns its RQ tests,
#: each with a caption of exactly what it shows (a test checks it names no column it drops).
VIEWS: dict[str, View] = {
    "t03-datasets": View(
        caption=(
            "Datasets: per dataset part, its Cases and the Excluded ones from the manifest of its RQ1 "
            "experiment, its Fault cases (those of veyltrace:off) and its Normal windows (04 §5.4, from "
            "the experiment that adds them). Development cases are excluded (04 §10.5)."
        ),
        columns=("Dataset", "Cases", "Excluded", "Fault cases", "Normal windows"),
        wrap=("Normal windows",),
        omit_absent=False,
    ),
    "t05-rq1-re2-oracle": View(
        caption=(
            "RQ1 accuracy on RE2 (re2-ob, re2-ss, re2-tt; all cases except bench/dev_cases.yaml) under "
            "the oracle alert, no shift, all sources, AI off: AC@1, AC@3 and AC@5 on ranks_rcaeval "
            "(status ignored, 04 §7) and Rerank@1, per System and Method, with 95% cluster-bootstrap "
            f"intervals in brackets; {MISSES}; a seeded arm pools its cases × seeds rows (04 §8)."
        ),
        columns=("System", "Method", *CI_COLUMNS),
    ),
    "t05c-rq1-comparisons": _comparison("RQ1 paired comparisons (H1a, H1b): " + COMPARISON_RULE),
    "t06-rq2-re2-oracle-rq2-v1": View(
        caption=(
            "RQ2 proposer on RE2 (re2-oracle-rq2-v1; all cases except bench/dev_cases.yaml), oracle "
            "alert, no shift, all sources, the AI arms' model and seeds as in its protocol (Sources): "
            "AC@1, AC@3 and AC@5 on ranks_rcaeval and Rerank@1, per System and Method, with 95% "
            f"cluster-bootstrap intervals in brackets; {MISSES}; a seeded arm pools its cases × seeds "
            "rows (04 §8). Outcomes counts the group's rows per run outcome (03 §13.3)."
        ),
        columns=("System", "Method", *CI_COLUMNS, OUTCOMES),
        headers={OUTCOMES: "Outcomes"},
    ),
    "t06c-rq2-comparisons": _comparison(
        "RQ2 paired comparisons (H2a; exploratory rows, 04 §2 RQ2 verifier vs agent-only, are "
        "unadjusted): " + COMPARISON_RULE
    ),
    "t06d-rq2-proposal-arms": View(  # H2b and H2c; the arms' accuracy is in the full grid
        caption=(
            "RQ2 planted and permuted proposals, per System and Method: the Value of decoy_top1_change "
            "(H2b: share of (case, seed) pairs whose top-1 changed under a planted decoy proposal) and "
            "of permutation_invariance (H2c: share of (case, seed) pairs with one verdict_hash across "
            "proposal permutations), bench_summary 1.2 entries (03 §13.3), with 95% exact "
            "(Clopper–Pearson) binomial intervals over the Pairs below each value, as 04 §2 RQ2 "
            "pre-registers. Protocol: see Sources."
        ),
        columns=("System", "Method", "Metric", "Value", "Pairs"),
        rows=({"Metric": ("decoy_top1_change", "permutation_invariance")},),
        wrap=("Metric",),
        stack=True,
    ),
    "t07-rq3-calibration": View(
        caption=(
            "RQ3 calibration on held-out folds (04 §5.4), per Experiment, System and Method: Coverage, "
            "Mean set size, AURC V − F (risk-coverage area of the verified score V minus the fused "
            "score F; H3c: below 0 favours V) and the NO_FAULT rates on normal windows (False-alarm "
            "rate) and fault cases (Wrong NO_FAULT rate), bench_summary 1.2 entries (03 §13.3) pooled "
            "over seeds, each with the 95% cluster-bootstrap interval of rq3-intervals/<id>/summary.json "
            "below it where one is committed (04 §8). τ_nf follows the 04 §12 row of 2026-11-21; "
            "Table 7c is the literal 04 §5.4 reading. Pooled rows (system as stratum) are secondary "
            "(04 §10 rule 3). Protocol: see Sources."
        ),
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
        caption=(
            "RQ5 cost on RE2, per System and Method: nearest-rank p50 and p95 over the group's rows (03 "
            "§13.3) of the wall time per case (ms) and the run's peak RSS (MiB, per_case.csv "
            "peak_rss_mb), for veyltrace:off from its solo run re2-oracle-rq1-v1 and the brief arms of "
            "re2-oracle-rq2-v1. No committed file records the machine of these runs; the slowest "
            "laptop's measurement, which H5 is read against, is Table 8c, and the AI path's recorded "
            "model time and tokens are Table 8b."
        ),
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
        caption=(
            "RQ6 replay, per Measurement. Tier 1: the Rate of recorded AI runs whose `veyltrace replay` "
            "exits 0, with its exact (Clopper–Pearson) 95% interval below it, over the Runs; Verdict "
            "reproduced counts the recomputed verdict_hash equal to the recorded one. Tier 2: the Rate "
            "of a fixed sample whose regenerated proposals are byte-identical (on the recording's own "
            "provider, 04 §12)."
        ),
        columns=("Measurement", "Rate", "Runs", "Verdict reproduced"),
        headers={"Verdict reproduced": "Reproduced"},
        wrap=("Measurement",),
        stack=True,
    ),
    "t10-rq4-shift": View(  # Figure 7's series, AC@1 per system (H4a); brief shifted on the subset
        caption=(
            "RQ4 alert-shift robustness (H4a): AC@1 with its 95% cluster-bootstrap interval in "
            "brackets, one column per System and pooled, per Method and Shift of the oracle alert (RE2, "
            "all sources; ±60 and ±120 s test H4a, ±30 s is exploratory, 04 §2), for rcaeval:nsigma, "
            "rcaeval:baro, simplerca, causatrix:rrf and veyltrace:off on all cases, and veyltrace:brief "
            "(the 0 s point is re2-oracle-rq1-v1, and for veyltrace:brief re2-oracle-rq2-v1, on all "
            "cases; a shifted brief run is on the 90-case subset). A value without an interval says "
            f"so (04 §8); {MISSES}."
        ),
        rows=(
            {"Method": tuple(m for m in SHIFT_SERIES if m != BRIEF), "Case set": ("all",)},
            {"Method": (BRIEF,)},
        ),
        pivot=Pivot(index=("Method", "Shift"), across="System", values=("AC@1",)),
    ),
    "t11-rq4-ablation": View(  # H4b: the share of CONFIRMED verdicts that are correct
        caption=(
            "RQ4 telemetry ablation (H4b) of veyltrace:off on RE2, oracle alert, no shift, per Sources "
            "dropped before ingest (04 §5.2 order; none is the unperturbed run) and System: AC@1 with "
            "its 95% cluster-bootstrap interval in brackets, AC@1 among CONFIRMED (the share of "
            "CONFIRMED verdicts that are correct, which H4b reads) and CONFIRMED verdicts (their number: "
            "answer_rate_confirmed × n_fault of summary.json's selective_accuracy entry, an exact "
            f"integer, 03 §13.3); {MISSES}. A cell without a value says why in its note."
        ),
        columns=("Sources", "System", "AC@1", "AC@1 among CONFIRMED", "CONFIRMED verdicts"),
        rows=({"Method": ("veyltrace:off",)},),
        headers={"AC@1 among CONFIRMED": "AC@1 conf.", "CONFIRMED verdicts": "Conf."},
    ),
    "t12-rq4-rcaevalc": View(  # H4c: veyltrace:off against naive-change on all RE2 cases
        caption=(
            "RQ4 RCAEval-C decoy grid (H4c): AC@1 and Decoy ranked first, each with its 95% "
            "cluster-bootstrap interval in brackets, one column per System and pooled, of veyltrace:off "
            "and naive-change per Grid point (true-change probability pi, decoy rate), on all RE2 "
            "cases under the oracle alert, decoys planted in [-1800, 300] s around it (04 §5.2). A "
            f"value without an interval says so (04 §8); {MISSES}."
        ),
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
    built = _pivot(table, view, view.pivot) if view.pivot is not None else _plain(table, view)
    return replace(built, caption=view.caption)


def drawn_columns(view: View) -> tuple[str, ...]:
    """The full-table columns a view shows (a pivot: its index, the column it spreads and its
    values); every other column of the table is one the view drops."""
    if view.pivot is not None:
        return (*view.pivot.index, view.pivot.across, *view.pivot.values)
    return view.columns


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
    caption = tex_escape(pt.caption or f"{tex_title(table.title)}.")
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
        rf"\caption{{{caption} The full grid is \vtfullref{{{table.name}}}.}}",
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
    scope += f". Every row, column, note and file hash: {RESULTS_PATH}/{table.name}.md."
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
        # rows and columns as in the .md (Source included), which \resulttableentry reads alone
        rf"\vtfullsize{{{len(table.rows)}}}{{{len(columns)}}}",
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
    lines.append(rf"\noindent Generated caption: {_text(tex_title(table.title))}. {_text(table.caption)}\par")
    lines.append(r"\endgroup")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------ numbers

#: A reference, in LaTeX text, to a table or figure by the generator's number ("Table 7c", "Fig. 4").
NUMBER_REF = re.compile(r"\b(Table|Fig\.|Figure) (A?\d+[a-z]?)\b")
TITLE_NUMBER = re.compile(r"^Table (A?\d+[a-z]?): ")
FIGURE_NUMBER = re.compile(r"^fig(\d+)-")


def number_targets(tables: Sequence[Table], figures: Sequence[str]) -> dict[str, str]:
    """{"Table 7c": "\\vtref{t07c-...}", "Fig. 4": "\\vtfigref{fig4-...}"}: the paper macro each
    generator number resolves to (paper/preamble.tex), since LaTeX numbers the PDF's tables and
    figures and the generator's numbers (the .md's) differ from them. A number several tables
    share (Table 5: one per benchmark) means the one the main text prints (VIEWS); a number with
    no such single table is left out, so a reference to it is a ConfigError (link_numbers)."""
    named: dict[str, list[str]] = {}
    for table in tables:
        if (found := TITLE_NUMBER.match(table.title)) is not None:
            named.setdefault(found[1], []).append(table.name)
    out: dict[str, str] = {}
    for number, names in named.items():
        chosen = names if len(names) == 1 else [n for n in names if n in VIEWS]
        if len(chosen) == 1:
            out[f"Table {number}"] = rf"\vtref{{{chosen[0]}}}"
    for name in figures:
        if (found := FIGURE_NUMBER.match(name)) is not None:
            out[f"Fig. {found[1]}"] = out[f"Figure {found[1]}"] = rf"\vtfigref{{{name}}}"
    return out


def link_numbers(tex: str, targets: Mapping[str, str], name: str) -> str:
    """`tex` (a generated file `name`) with every generator number replaced by its paper macro."""

    def one(found: re.Match[str]) -> str:
        key = f"{found[1]} {found[2]}"
        if key not in targets:
            raise ConfigError(f"{name}: {key!r} names no single generated table or figure")
        return targets[key]

    return NUMBER_REF.sub(one, tex)
