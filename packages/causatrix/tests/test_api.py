"""Engine-level tests of `api.run` on synth: required inputs and optional graph edges (07 §6).

Restored unchanged from the R-00 stub tests (review of #164); the ranking itself is pinned by
test_handmade.py, since the synth slate is empty while Anomara is a stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_causatrix import api
from veyltrace_core import io
from veyltrace_core.testing import fixture_run_dir, make_context


@pytest.mark.parametrize("absent", ["evidence", "graph.nodes"])
def test_run_fails_without_required_input(tmp_path: Path, absent: str) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    io.path_of(absent, run_dir).unlink()
    result = api.run(make_context("causatrix", run_dir))
    assert result.status == "failed"
    assert not io.exists("slate", run_dir)


def test_run_without_graph_edges_still_writes(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom")
    io.path_of("graph.edges", run_dir).unlink()
    result = api.run(make_context("causatrix", run_dir))
    assert result.status == "ok"
    assert result.metrics["graph_edges_in_u"] == 0
