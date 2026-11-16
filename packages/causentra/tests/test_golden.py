"""Golden tests: Causentra on the committed upstream fixtures reproduces its committed verdict.

Each fixture case (synth-01..05 and every variant, incl. synth-05@silent and the AI-on
synth-01@fake) is assembled through the claim pass with `fixture_run_dir`, run with the context
the pipeline would build (same config overrides and AI mode, code_commit "fixture", so the same
run_id), and compared by canonical content with `assert_golden`. A case whose upstream fixtures do
not exist yet (e.g. synth-01@detected before Anomara's detector) is skipped, as update_golden does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_causentra import api
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.testing import (
    SYNTH_CASES,
    VARIANTS,
    assert_golden,
    fixture_run_dir,
    golden,
    make_context,
)

THROUGH = "faultloom.claim_pass"
CASES = (*SYNTH_CASES, *sorted(VARIANTS))


def _run_on_fixtures(case: str, tmp_path: Path) -> Path:
    try:
        run_dir = fixture_run_dir(case, tmp_path, through=THROUGH)
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")
    variant = VARIANTS.get(case)
    ctx = make_context(
        "causentra",
        run_dir,
        ai_mode=variant.ai_mode if variant is not None else "off",
        overrides=variant.overrides if variant is not None else {},
    )
    result = api.run(ctx)
    assert result.status == "ok", result.notes
    return run_dir


@pytest.mark.parametrize("case", CASES)
def test_verdict_matches_golden(case: str, tmp_path: Path) -> None:
    run_dir = _run_on_fixtures(case, tmp_path)
    assert_golden(io.read("verdict", run_dir), "verdict", case)


@pytest.mark.parametrize("case", CASES)
def test_golden_verdict_ranks_every_slate_candidate(case: str, tmp_path: Path) -> None:
    """The committed verdict keeps every slate candidate (AGENTS Never 5) and hashes itself."""
    run_dir = _run_on_fixtures(case, tmp_path)
    expected = golden("verdict", case)
    assert isinstance(expected, models.Verdict)
    slate = io.read_model("slate", run_dir, models.Slate)
    assert {c.service for c in slate.candidates} <= {r.service for r in expected.ranked}
    assert len(expected.ranks_rcaeval) == len(slate.all_scores)
