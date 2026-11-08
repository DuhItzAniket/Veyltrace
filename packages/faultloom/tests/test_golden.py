"""Golden tests: both FaultLoom passes on every synth fixture case and variant (06 §7 Golden).

Each test assembles the run directory the pipeline would hand the step from the producers'
committed fixtures and compares FaultLoom's output to its own committed fixture by canonical
content (assert_golden, D-16). A case whose upstream fixtures are not committed yet is skipped, as
update_golden does; a missing FaultLoom fixture for a case whose inputs exist fails in
assert_golden. Fixtures are refreshed with
`uv run python scripts/check.py --package faultloom --update-golden`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.testing import SYNTH_CASES, VARIANTS, assert_golden, make_context
from veyltrace_core.testing.rundir import fixture_run_dir
from veyltrace_faultloom.api import run

#: Every fixture directory name (SYNTH_CASES, then the variants A→Z).
CASES = (*SYNTH_CASES, *sorted(VARIANTS))
#: (phase, last sub-step before it, fixture phase of evidence) per FaultLoom pass.
PASSES = (("main", "causalith", "main"), ("claim_pass", "relentra", "final"))


def _upstream_run_dir(case: str, tmp_path: Path, through: str) -> Path:
    """The run dir through `through`; a variant whose upstream fixtures are not committed yet
    (synth-01@detected before Anomara's detector) is skipped, as update-golden SKIPs it."""
    try:
        return fixture_run_dir(case, tmp_path, through=through)
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")


@pytest.mark.parametrize(("phase", "through", "fixture_phase"), PASSES, ids=[p[0] for p in PASSES])
@pytest.mark.parametrize("case", CASES)
def test_evidence_matches_golden(
    tmp_path: Path, case: str, phase: str, through: str, fixture_phase: str
) -> None:
    run_dir = _upstream_run_dir(case, tmp_path, through)
    variant = VARIANTS.get(case)
    ctx = make_context(
        "faultloom",
        run_dir,
        phase="main" if phase == "main" else "claim_pass",
        ai_mode=variant.ai_mode if variant is not None else "off",
        overrides=variant.overrides if variant is not None else {},
    )
    result = run(ctx)
    assert result.status in ("ok", "degraded")
    assert_golden(io.path_of("evidence", run_dir), "evidence", case, phase=fixture_phase)
