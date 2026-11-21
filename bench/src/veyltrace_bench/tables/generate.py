"""Generate every paper table from committed results, write them, or check them (R-17).

Outputs are a sorted {path relative to the results root: bytes} map, so writing and checking
compare the same bytes. `bench/results/tables/` is owned by the generator (11 §10: generated,
never hand-edited): a `.md` or `.tex` there that the generator no longer writes is stale and is
removed on write, and reported by a check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from veyltrace_bench.tables.context import Context, context
from veyltrace_bench.tables.index import development_cases, results_index
from veyltrace_bench.tables.render import Row, Table, latex, markdown
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError

TABLES_DIR = "tables"
GENERATED_SUFFIXES = (".md", ".tex")  # what TABLES_DIR may hold; anything else there is left alone

Builder = Callable[[Context], list[Table]]
BUILDERS: tuple[Builder, ...] = (results_index, development_cases)
REVISES = "revises "  # the role of a revision's results (Context.revised)
UNPAIRED: frozenset[Builder] = frozenset({results_index, development_cases})  # list every experiment once


def _revision(row: Row) -> bool:
    """Whether the row cites a revision: its source or a second source (`also`) says "revises"."""
    return any(s.role.startswith(REVISES) for s in (row.source, *row.also) if s is not None and s.role)


def _key(table: Table, row: Row) -> tuple[str, ...]:
    return tuple(row.cells[i].text for i in table.key)


def paired(build: Builder, ctx: Context) -> list[Table]:
    """`build`'s tables; where the register pairs revisions with a pre-registered experiment (04
    §12), the builder runs again once per revision (sorted by id), and each row citing that
    revision goes right after the last pre-registered row with the same key (`Table.key`, e.g.
    system and method), both labelled by their source cell; a revised row whose key the
    pre-registered table lacks (a method the revision added) goes at the end (M1 of the review)."""
    tables = build(ctx)
    if not ctx.revises or build in UNPAIRED:
        return tables
    twins = [build(ctx.revised(new)) for new in sorted(ctx.revises)]
    out: list[Table] = []
    for i, table in enumerate(tables):
        revised: dict[tuple[str, ...], list[Row]] = {}
        for twin in twins:
            if twin[i].name != table.name:
                raise ConfigError(f"the revised pass of {table.name!r} built {twin[i].name!r} instead")
            for row in filter(_revision, twin[i].rows):
                revised.setdefault(_key(table, row), []).append(row)
        last = {_key(table, row): n for n, row in enumerate(table.rows)}
        rows: list[Row] = []
        for n, row in enumerate(table.rows):
            rows.append(row)
            if last[_key(table, row)] == n:
                rows += revised.pop(_key(table, row), [])
        rows += [row for key in sorted(revised) for row in revised[key]]
        out.append(replace(table, rows=tuple(rows)))
    return out


def outputs(
    results_root: Path, experiments_dir: Path, builders: Sequence[Builder] = BUILDERS
) -> dict[str, bytes]:
    """Every generated file, as {path relative to the results root: bytes}, sorted by path."""
    ctx = context(results_root, experiments_dir)
    files: dict[str, bytes] = {}
    for build in builders:
        for table in paired(build, ctx):
            for suffix, render in ((".md", markdown), (".tex", latex)):
                path = f"{TABLES_DIR}/{table.name}{suffix}"
                if path in files:
                    raise ConfigError(f"two tables are named {table.name!r}")
                files[path] = render(table).encode("utf-8")
    return dict(sorted(files.items()))


def _on_disk(root: Path) -> list[str]:
    folder = root / TABLES_DIR
    if not folder.is_dir():
        return []
    found = (p.name for p in folder.iterdir() if p.is_file() and p.suffix in GENERATED_SUFFIXES)
    return sorted(f"{TABLES_DIR}/{name}" for name in found)


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
