"""Golden cards on the synth verdict fixtures (X-03 acceptance, #20; 10 §7 "Golden" row).

Each case runs the card step on `fixture_run_dir(case, through="causentra")` with the variant's
overrides and AI mode, as `update_golden` would, and compares `card.json` and `card.md` with
`packages/causivra/fixtures/<case>/`. Two runs give byte-identical files (10 §7 determinism row).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_causivra import api
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.hashing import self_hash
from veyltrace_core.testing import (
    SYNTH_CASES,
    VARIANTS,
    assert_golden,
    fixture_run_dir,
    golden_file,
    make_context,
)

CASES = (*SYNTH_CASES, *sorted(VARIANTS))
#: The card step runs after Causentra (02 §4 step 10a).
THROUGH = "causentra"


def _run(case: str, tmp_path: Path) -> Path:
    try:
        run_dir = fixture_run_dir(case, tmp_path, through=THROUGH)
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")
    variant = VARIANTS.get(case)
    ctx = make_context(
        "causivra",
        run_dir,
        phase="card",
        ai_mode=variant.ai_mode if variant is not None else "off",
        overrides=variant.overrides if variant is not None else {},
    )
    result = api.run(ctx)
    assert result.status == "ok"
    assert [name for name, _ in result.outputs] == ["card", "card.md"]
    return run_dir


@pytest.mark.parametrize("case", CASES)
def test_card_matches_golden(case: str, tmp_path: Path) -> None:
    run_dir = _run(case, tmp_path)
    assert_golden(io.read("card", run_dir), "card", case)
    expected = golden_file("causivra", case, "card.md")
    assert (run_dir / "card.md").read_bytes() == expected.read_bytes()


@pytest.mark.parametrize("case", CASES)
def test_card_copies_its_verdict(case: str, tmp_path: Path) -> None:
    run_dir = _run(case, tmp_path)
    card = io.read_model("card", run_dir, models.Card, validate=True)
    verdict = io.read_model("verdict", run_dir, models.Verdict)
    assert (card.status, card.root, card.confidence) == (verdict.status, verdict.root, verdict.confidence)
    assert card.verdict_hash == verdict.verdict_hash and card.card_hash == self_hash("card", card)


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    a, b = _run("synth-01", tmp_path / "a"), _run("synth-01", tmp_path / "b")
    for name in ("card.json", "card.md"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
