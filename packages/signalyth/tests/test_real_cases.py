"""Real-case smoke (02 §7): RE2-OB, RE2-SS, RE2-TT through the pipeline up to Signalyth.

Skipped without `${VEYLTRACE_DATA}` (marker `real_data`). Per suite, the first fetched case runs
twice: the signal cube validates against its contracts, Sock Shop has no trace series or edges,
and both runs write byte-identical files (the writer sorts by the 03 keys). The Signalyth step
time is reported; the 10 s of 02 §8 is an estimate that O-11 measures, so only the 30 s run
budget is asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_core import io
from veyltrace_core.config import data_root
from veyltrace_core.context import RunPlan
from veyltrace_core.pipeline import execute
from veyltrace_infralume.index import read_index

pytestmark = pytest.mark.real_data
OUTPUTS = ("signal_cube.series", "signal_cube.edges", "signal_cube.templates", "signal_cube.critical_path")
RUN_BUDGET_MS = 30_000  # 02 §9: 30 s per case for the deterministic path


def _run(suite: str, case: str, root: Path) -> tuple[Path, float]:
    summary = execute(RunPlan(dataset=suite, case=case, runs_root=root, to_step="signalyth"))
    assert summary.outcome == "ok", (summary.failed_step, summary.reason, summary.error)
    return summary.run_dir, summary.wall_ms["signalyth"]


@pytest.mark.parametrize("suite", ["re2-ob", "re2-ss", "re2-tt"])
def test_real_signal_cube(suite: str, tmp_path: Path) -> None:
    index = read_index(data_root(), suite)
    if not index:
        pytest.skip(f"no {suite} case fetched under {data_root()}")
    case = sorted(index)[0]
    first, wall_ms = _run(suite, case, tmp_path / "a")
    print(f"{suite} {case}: signalyth {wall_ms / 1000:.1f} s")
    assert wall_ms <= RUN_BUDGET_MS
    tables = {c: io.read_table(c, first, validate=True) for c in OUTPUTS}
    sources = set(tables["signal_cube.series"].column("source").to_pylist())
    if suite == "re2-ss":  # Sock Shop publishes no traces (rcaeval_facts)
        assert sources == {"metrics"} and tables["signal_cube.edges"].num_rows == 0
    else:
        assert sources == {"metrics", "traces"} and tables["signal_cube.edges"].num_rows > 0
        assert tables["signal_cube.critical_path"].num_rows > 0
    second, _ = _run(suite, case, tmp_path / "b")
    for contract in OUTPUTS:
        assert io.path_of(contract, first).read_bytes() == io.path_of(contract, second).read_bytes(), contract
