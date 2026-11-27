"""The tables list files in the same order on every platform (#664).

Sorting `Path` objects is case-insensitive on Windows and by code point on POSIX, so a side-result
folder with `README.md` next to lower-case names printed its sources in a different order on macOS
than on the recording host, and `bench tables --check` failed there with every hash equal.
"""

from __future__ import annotations

from pathlib import Path

from veyltrace_bench.tables import context
from veyltrace_bench.tables.context import by_name

NAMES = ("b-two.csv", "README.md", "a-one.csv", "Zeta.txt")
#: Code-point order: upper case before lower case, whatever the host.
CODE_POINT = ("README.md", "Zeta.txt", "a-one.csv", "b-two.csv")


def test_by_name_is_code_point_order(tmp_path: Path) -> None:
    for name in NAMES:
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    assert tuple(p.name for p in sorted(tmp_path.iterdir(), key=by_name)) == CODE_POINT


def test_side_hashes_list_files_in_code_point_order(tmp_path: Path) -> None:
    folder = tmp_path / "perf-sample"
    folder.mkdir()
    for name in NAMES:
        (folder / name).write_text(name + "\n", encoding="utf-8")
    side = context._side(tmp_path, folder)  # pyright: ignore[reportPrivateUsage]  # the unit under test
    assert tuple(name for name, _ in side.source.hashes) == CODE_POINT
