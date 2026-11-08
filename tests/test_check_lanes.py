"""scripts/check_lanes.py: changed-file detection that the `lanes` CI job relies on (L-03).

Why: a plain `git diff --name-only` reports only the new path of a moved file, so moving another
lane's file into your own lane would pass the lane check. These tests pin the rename-safe and
Unicode-safe behaviour on a throwaway git repository.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _load_check_lanes() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_lanes", ROOT / "scripts" / "check_lanes.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_lanes", module)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")
    return repo


def test_moved_file_counts_at_both_paths(tmp_path: Path) -> None:
    """Moving an Explain-lane file into the Reason lane touches the Explain path too."""
    check_lanes = _load_check_lanes()
    repo = _repo(tmp_path, {"packages/relentra/src/x.py": "VALUE = 1\n" * 20})
    (repo / "packages/core/src").mkdir(parents=True)
    _git(repo, "mv", "packages/relentra/src/x.py", "packages/core/src/x.py")
    _git(repo, "commit", "-q", "-m", "move")
    changed = check_lanes.changed_files("base", cwd=repo)
    assert changed == ["packages/core/src/x.py", "packages/relentra/src/x.py"]


def test_non_ascii_paths_are_not_escaped(tmp_path: Path) -> None:
    """core.quotePath=false: a UTF-8 path comes back as itself, so lane patterns can match it."""
    check_lanes = _load_check_lanes()
    repo = _repo(tmp_path, {"README.md": "x\n"})
    name = "docs/team/ak-→-notes.md"
    path = repo / name
    path.parent.mkdir(parents=True)
    path.write_text("notes\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add")
    assert check_lanes.changed_files("base", cwd=repo) == [name]
