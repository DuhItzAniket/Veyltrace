"""Real-case smoke (04 §7): RE2-OB, RE2-SS, RE2-TT through the pipeline up to Causync.

Skipped without `${VEYLTRACE_DATA}` (marker `real_data`). RCAEval has no change events, so
`changes` must be empty; the reference clock is `traces`, or `metrics` for Sock Shop, which
publishes no traces; and `tolerance_ns` is reported (04 §3.1 expects about 15 s on RE2). Two runs
must write byte-identical files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.config import data_root
from veyltrace_core.context import RunPlan
from veyltrace_core.pipeline import execute
from veyltrace_infralume.index import read_index

pytestmark = pytest.mark.real_data
OUTPUTS = ("alignment", "changes")


def _run(suite: str, case: str, root: Path) -> Path:
    summary = execute(RunPlan(dataset=suite, case=case, runs_root=root, to_step="causync"))
    assert summary.outcome == "ok", (summary.failed_step, summary.reason, summary.error)
    return summary.run_dir


@pytest.mark.parametrize("suite", ["re2-ob", "re2-ss", "re2-tt"])
def test_real_alignment_and_changes(suite: str, tmp_path: Path) -> None:
    index = read_index(data_root(), suite)
    if not index:
        pytest.skip(f"no {suite} case fetched under {data_root()}")
    case = sorted(index)[0]
    first = _run(suite, case, tmp_path / "a")
    alignment = io.read("alignment", first)
    assert isinstance(alignment, models.Alignment)
    print(f"{suite} {case}: reference {alignment.reference}, tolerance {alignment.tolerance_ns / 1e9:.0f} s")
    for o in alignment.offsets:
        print(f"  {o.source} {o.service or '-'}: {o.offset_ns / 1e6:.1f} ms, {o.method}, {o.confidence:.2f}")
    assert alignment.reference == ("metrics" if suite == "re2-ss" else "traces")
    assert alignment.tolerance_ns > 0
    assert io.read_table("changes", first, validate=True).num_rows == 0  # no events: the channel abstains
    second = _run(suite, case, tmp_path / "b")
    for contract in OUTPUTS:
        assert io.path_of(contract, first).read_bytes() == io.path_of(contract, second).read_bytes(), contract
