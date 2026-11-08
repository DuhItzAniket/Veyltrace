"""steps.STEPS: the 14 named sub-steps, their 02 §4 stages and selection helpers."""

from __future__ import annotations

import pytest

from veyltrace_contracts.models import RunManifestStep
from veyltrace_core import steps

EXPECTED = (
    ("infralume", 0, "infralume", "main"),
    ("alert", 1, None, "main"),
    ("signalyth", 2, "signalyth", "main"),
    ("anomara", 3, "anomara", "main"),
    ("causync", 4, "causync", "main"),
    ("causalith", 4, "causalith", "main"),
    ("faultloom", 5, "faultloom", "main"),
    ("causatrix", 6, "causatrix", "main"),
    ("relentra", 7, "relentra", "main"),
    ("faultloom.claim_pass", 8, "faultloom", "claim_pass"),
    ("causentra", 9, "causentra", "main"),
    ("causivra.card", 10, "causivra", "card"),
    ("manifest", 10, None, "main"),
    ("causivra.receipt", 10, "causivra", "receipt"),
)


def test_order_stages_engines_phases() -> None:
    got = tuple((s.name, s.stage, s.engine, s.phase) for s in steps.STEPS)
    assert got == EXPECTED
    assert tuple(s.index for s in steps.STEPS) == tuple(range(14))


def test_names_match_run_manifest_steps_literal() -> None:
    literal = RunManifestStep.model_fields["name"].annotation
    assert literal is not None
    from typing import get_args

    assert get_args(literal) == steps.STEP_NAMES


def test_runner_and_paths() -> None:
    assert steps.step("alert").runner == "core"
    assert steps.step("signalyth").runner == "signalyth"
    assert steps.step("infralume").paths[0] == "case_manifest.json"
    assert "cassette/" in steps.step("relentra").files


def test_select_and_lookup() -> None:
    assert [s.name for s in steps.select("causync", "faultloom")] == ["causync", "causalith", "faultloom"]
    assert len(steps.select()) == 14
    with pytest.raises(ValueError, match="comes before"):
        steps.select("causentra", "alert")
    with pytest.raises(KeyError, match="unknown pipeline step"):
        steps.step("nope")
    assert steps.step_for("faultloom", "claim_pass") == steps.step("faultloom.claim_pass")
    assert steps.step_for("faultloom", "card") is None
    assert steps.index_of("manifest") == 12
