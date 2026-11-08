"""End to end: the pipeline from ingest through FaultLoom's claim pass on synth-01…05 (R-00).

Runs the real installed engines (whatever stage each lane has reached) through
`veyltrace_core.pipeline.execute`, so the entry point, the step wiring (main at step 5, claim pass
at step 8), the output-hash checks and the contract writer are all exercised as in `diagnose`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.context import RunPlan
from veyltrace_core.pipeline import execute
from veyltrace_core.testing import SYNTH_CASES
from veyltrace_core.testing.update_golden import FIXTURE_ENV

STEPS = ("faultloom", "faultloom.claim_pass")


@pytest.mark.parametrize("case", SYNTH_CASES)
def test_pipeline_runs_through_the_claim_pass(tmp_path: Path, case: str) -> None:
    plan = RunPlan(
        dataset="synth",
        case=case,
        to_step="faultloom.claim_pass",
        runs_root=tmp_path / "runs",
        code_commit="fixture",
        env=FIXTURE_ENV,
    )
    summary = execute(plan)
    assert summary.outcome == "ok", summary.reason
    by_step = {record.name: result for record, result in zip(summary.steps, summary.results, strict=True)}
    for name in STEPS:
        assert by_step[name].engine == "faultloom"
        assert by_step[name].status == "ok", by_step[name].notes
    # AI off: no proposals, so the claim pass carries the main evidence forward byte-identical.
    assert by_step["faultloom"].outputs == by_step["faultloom.claim_pass"].outputs
    evidence = io.read_table("evidence", summary.run_dir, validate=True)
    assert evidence.num_rows == by_step["faultloom.claim_pass"].metrics["atoms"]
    # Every atom is about a member of U (manifest services and non-external graph nodes, 06 §2.1).
    manifest = io.read_model("case_manifest", summary.run_dir, models.CaseManifest)
    nodes = io.read_table("graph.nodes", summary.run_dir)
    members = set(manifest.services) | {
        str(n)
        for n, k in zip(nodes.column("node").to_pylist(), nodes.column("kind").to_pylist(), strict=True)
        if k != "external"
    }
    assert {str(c) for c in evidence.column("candidate").to_pylist()} <= members
    assert by_step["faultloom"].metrics["universe"] == len(members)
