"""Generate every paper table and figure from committed results, write them, or check them (R-17).

Outputs are a sorted {path relative to the results root: bytes} map, so writing and checking
compare the same bytes. `bench/results/tables/` and `figures/` are owned by the generator (11
§10: generated, never hand-edited): a `.md`/`.tex` (tables) or `.csv`/`.svg` (figures) there that
the generator no longer writes is stale and is removed on write, and reported by a check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from veyltrace_bench.tables import paper
from veyltrace_bench.tables.context import Context, context
from veyltrace_bench.tables.figures import FIGURES_DIR, figures
from veyltrace_bench.tables.index import development_cases, results_index
from veyltrace_bench.tables.render import Row, Table, latex, markdown
from veyltrace_bench.tables.rq1 import accuracy, datasets, rq1_comparisons
from veyltrace_bench.tables.rq4 import ablation, decoys, shift
from veyltrace_bench.tables.rq23 import calibration, proposer
from veyltrace_bench.tables.rq56 import cost, replay
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError

TABLES_DIR = "tables"
#: What each generated directory holds; any other file there is left alone.
GENERATED = {TABLES_DIR: (".md", ".tex"), FIGURES_DIR: (".csv", ".svg")}

Builder = Callable[[Context], list[Table]]
BUILDERS: tuple[Builder, ...] = (
    results_index, development_cases, datasets, accuracy, rq1_comparisons,
    proposer, calibration, cost, replay, shift, ablation, decoys,
)  # fmt: skip
#: Builders that list every experiment once (A0, A2), or resolve a revision themselves (Table 3
#: takes its normal windows from the revision, so a second pass would only repeat its rows).
UNPAIRED: frozenset[Builder] = frozenset({results_index, development_cases, datasets})


def _revision(row: Row) -> bool:
    """Whether the row cites a revision in the slot of the experiment it revises (its source or a
    second source, `also`, stands in for it; Context.revised), not the revision under its own id."""
    return any(s.stands_in_for is not None for s in (row.source, *row.also) if s is not None)


def _standalone(row: Row, replaced: set[str]) -> bool:
    """Whether the row cites a revision under its own id while the revised pass of the same table
    cites it in the slot of the experiment it revises (`replaced`): the same values twice."""
    src = row.source
    return src is not None and src.stands_in_for is None and src.experiment_id in replaced


def _key(table: Table, row: Row) -> tuple[str, ...]:
    return tuple(row.cells[i].text for i in table.key)


def paired(build: Builder, ctx: Context) -> list[Table]:
    """`build`'s tables; where the register pairs revisions with a pre-registered experiment (04
    §12), the builder runs again once per revision (sorted by id), and each row citing that
    revision goes right after the last pre-registered row with the same key (`Table.key`, e.g.
    system and method), both labelled by their source cell; a revised row whose key the
    pre-registered table lacks (a method the revision added) goes at the end (M1 of the review).
    The revision's own rows, under its own id, are then left out of that table, since the revised
    rows print the same values (gap 35 of the R-17 audit)."""
    tables = build(ctx)
    if not ctx.revises or build in UNPAIRED:
        return tables
    twins = [build(ctx.revised(new)) for new in sorted(ctx.revises)]
    out: list[Table] = []
    for i, table in enumerate(tables):
        revised: dict[tuple[str, ...], list[Row]] = {}
        replaced: set[str] = set()
        for new, twin in zip(sorted(ctx.revises), twins, strict=True):
            if twin[i].name != table.name:
                raise ConfigError(f"the revised pass of {table.name!r} built {twin[i].name!r} instead")
            for row in filter(_revision, twin[i].rows):
                revised.setdefault(_key(table, row), []).append(row)
                replaced.add(new)
        kept = [row for row in table.rows if not _standalone(row, replaced)]
        last = {_key(table, row): n for n, row in enumerate(kept)}
        rows: list[Row] = []
        for n, row in enumerate(kept):
            rows.append(row)
            if last[_key(table, row)] == n:
                rows += revised.pop(_key(table, row), [])
        rows += [row for key in sorted(revised) for row in revised[key]]
        out.append(replace(table, rows=tuple(rows)))
    return out


def outputs(
    results_root: Path, experiments_dir: Path, builders: Sequence[Builder] = BUILDERS
) -> dict[str, bytes]:
    """Every generated file, as {path relative to the results root: bytes}, sorted by path: per
    table its `.md` and `.tex`, its full grid as a longtable (`-full.tex`) and, for a table the
    paper's main text cites (paper.VIEWS), its compact paper view (`-paper.tex`)."""
    ctx = context(results_root, experiments_dir)
    files: dict[str, bytes] = {}
    for build in builders:
        for table in paired(build, ctx):
            rendered = {
                ".md": markdown(table),
                ".tex": latex(table),
                f"{paper.FULL_SUFFIX}.tex": paper.full_latex(table),
            }
            if (view := paper.VIEWS.get(table.name)) is not None:
                rendered[f"{paper.PAPER_SUFFIX}.tex"] = paper.paper_latex(paper.build(table, view))
            for suffix, text in rendered.items():
                path = f"{TABLES_DIR}/{table.name}{suffix}"
                if path in files:
                    raise ConfigError(f"two tables are named {table.name!r}")
                files[path] = text.encode("utf-8")
    return dict(sorted((files | figures(ctx)).items()))


def _on_disk(root: Path) -> list[str]:
    found: list[str] = []
    for name, suffixes in GENERATED.items():
        if (folder := root / name).is_dir():
            found += [f"{name}/{p.name}" for p in folder.iterdir() if p.is_file() and p.suffix in suffixes]
    return sorted(found)


def differences(files: Mapping[str, bytes], root: Path) -> list[str]:
    """Paths whose bytes on disk differ from `files`, are missing, or are stale; [] when identical."""
    out = [p for p, data in files.items() if not (root / p).is_file() or textio.read_bytes(root / p) != data]
    return sorted(out + [p for p in _on_disk(root) if p not in files])


def write(files: Mapping[str, bytes], root: Path) -> list[str]:
    """Write `files` below `root` and remove stale generated files; the paths changed, sorted."""
    changed = differences(files, root)
    for path in changed:
        if path in files:
            textio.write_bytes(root / path, files[path])
        else:
            (root / path).unlink()
    return changed
