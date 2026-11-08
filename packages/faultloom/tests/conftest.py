"""Shared fixtures of FaultLoom's tests: fixture run directories ready for each pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_core.testing import fixture_run_dir


@pytest.fixture
def main_dir(tmp_path: Path) -> Path:
    """synth-01 run dir holding everything before FaultLoom's engine pass (through causalith)."""
    return fixture_run_dir("synth-01", tmp_path, through="causalith")


@pytest.fixture
def claim_dir(tmp_path: Path) -> Path:
    """synth-01 run dir holding everything before the claim pass (main evidence, slate; AI off)."""
    return fixture_run_dir("synth-01", tmp_path, through="relentra")
