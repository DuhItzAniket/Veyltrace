"""End to end: the synth cases run through the pipeline up to and including Causentra (R-00).

synth-01 also runs the full pipeline, so the card and receipt steps accept this verdict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_causentra import stub
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.hashing import self_hash
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.pipeline import RunSummary, run_case
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, SYNTH_CASES

CASES = (*SYNTH_CASES, "synth-05@silent")


def _run(case: str, root: Path, to_step: str = "causivra.receipt") -> RunSummary:
    return run_case(
        "synth",
        make_case_id(case),
        "off",
        {},
        runs_root=root / "runs",
        code_commit=FIXTURE_CODE_COMMIT,
        to_step=to_step,
    )


def _check_verdict(summary: RunSummary) -> models.Verdict:
    assert summary.outcome == "ok", summary.reason
    record = next(r for r in summary.results if r.engine == "causentra")
    assert record.status == "ok"
    assert stub.STUB_NOTE in record.notes
    io.read("verdict", summary.run_dir, validate=True)
    verdict = io.read_model("verdict", summary.run_dir, models.Verdict)
    slate = io.read_model("slate", summary.run_dir, models.Slate)
    assert verdict.case_id == summary.case_id and verdict.run_id == summary.run_id
    assert verdict.status == "INCONCLUSIVE" and verdict.root is None
    assert [r.service for r in verdict.ranked] == [c.service for c in slate.candidates]
    assert all(t.result == "untestable" for r in verdict.ranked for t in r.trials)
    assert verdict.verdict_hash == self_hash("verdict", verdict)
    return verdict


@pytest.mark.parametrize("case", CASES)
def test_pipeline_through_causentra(case: str, tmp_path: Path) -> None:
    _check_verdict(_run(case, tmp_path, to_step="causentra"))


def test_full_pipeline_on_synth01_accepts_the_verdict(tmp_path: Path) -> None:
    summary = _run("synth-01", tmp_path)
    verdict = _check_verdict(summary)
    card = io.read_model("card", summary.run_dir, models.Card)
    receipt = io.read_model("receipt", summary.run_dir, models.Receipt)
    assert card.verdict_hash == verdict.verdict_hash
    assert receipt.predicate.verdict_hash == verdict.verdict_hash


def test_two_runs_give_the_same_verdict_bytes(tmp_path: Path) -> None:
    a = _run("synth-01", tmp_path / "a", to_step="causentra")
    b = _run("synth-01", tmp_path / "b", to_step="causentra")
    path_a = io.path_of("verdict", a.run_dir)
    path_b = io.path_of("verdict", b.run_dir)
    assert path_a.read_bytes() == path_b.read_bytes()
