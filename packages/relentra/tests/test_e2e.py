"""End to end through the Explain engines (X-00 acceptance, #10 / #91).

synth-01 runs the whole pipeline with AI off and with AI record on the FakeProvider config
(`llm.provider = fake`, the determinism gate's fake arm): Relentra writes skipped proposals and an
empty trace, Causivra writes the card and a receipt whose agent-trace head is null.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.ids import AIMode
from veyltrace_core.pipeline import run_case
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root
from veyltrace_relentra.stub import STUB_NOTE


@pytest.mark.parametrize("ai_mode", ["off", "record"])
def test_full_pipeline_through_explain_engines(ai_mode: AIMode, tmp_path: Path) -> None:
    summary = run_case(
        "synth",
        "synth-01",
        ai_mode,
        {"llm.provider": "fake"},
        runs_root=tmp_path / "runs",
        config_dir=repo_root() / "config",
        code_commit=FIXTURE_CODE_COMMIT,
    )
    assert summary.outcome == "ok", (summary.reason, summary.failed_step)
    relentra = next(r for r in summary.results if r.engine == "relentra")
    if ai_mode == "off":
        assert relentra.status == "skipped"
        assert not io.exists("proposals", summary.run_dir)
    else:
        assert relentra.status == "ok" and STUB_NOTE in relentra.notes
        proposals = io.read_model("proposals", summary.run_dir, models.Proposals, validate=True)
        assert proposals.status == "skipped" and proposals.case_id == summary.case_id
    receipt = io.read_model("receipt", summary.run_dir, models.Receipt, validate=True)
    assert receipt.predicate.agent_trace_head is None
    manifest = io.read_model("run_manifest", summary.run_dir, models.RunManifest)
    assert manifest.ai.mode == ai_mode
    assert manifest.ai.cassette_sha256 is None  # no model was called, so nothing was recorded
