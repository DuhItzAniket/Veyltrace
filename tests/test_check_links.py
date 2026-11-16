"""scripts/check_links.py: which Markdown files the link check scans.

Why: side venvs such as `bench/.venv-rcaeval/` (git-ignored by `.venv-*/`) hold third-party
docs, e.g. RCAEval's own README, whose broken links are not ours to fix. They must be pruned
like `.venv/` so a local run reports only this repository's links.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_links", ROOT / "scripts" / "check_links.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_links", module)
    spec.loader.exec_module(module)
    return module


def test_side_venvs_are_pruned_like_dot_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    links = _load()
    for rel in (
        "docs/a.md",
        "bench/.venv-rcaeval/src/RCAEval/README.md",
        ".venv/lib/x.md",
        "bench/venv-notes.md",  # a file named like a venv is not a venv directory
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# x\n", encoding="utf-8")
    monkeypatch.setattr(links, "ROOT", tmp_path)
    found = [p.relative_to(tmp_path).as_posix() for p in links.collect([], [])]
    assert found == ["bench/venv-notes.md", "docs/a.md"]
