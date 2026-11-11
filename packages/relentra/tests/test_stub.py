"""The X-00 Relentra stub: config checks, skip reasons, outputs and goldens (08 §2.2, §3.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.context import RunContext
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.testing import VARIANTS, assert_golden, fixture_run_dir, make_context
from veyltrace_relentra import api
from veyltrace_relentra.stub import (
    REASON_DISABLED,
    REASON_EMPTY_SLATE,
    REASON_NOT_BUILT,
    STUB_NOTE,
    Settings,
    settings_from,
    skip_reason,
)

FAKE_CASE = "synth-01@fake"
#: Relentra runs after Causatrix (02 §4 step 7).
THROUGH = "causatrix"


def _fake_dir(tmp_path: Path) -> Path:
    return fixture_run_dir(FAKE_CASE, tmp_path, through=THROUGH)


def _fake_ctx(run_dir: Path, **overrides: object) -> RunContext:
    variant = VARIANTS[FAKE_CASE]
    return make_context(
        "relentra", run_dir, ai_mode=variant.ai_mode, overrides={**variant.overrides, **overrides}
    )


@pytest.mark.parametrize(
    "config",
    [{"enabled": "yes", "mode": "brief"}, {"enabled": True, "mode": "external"}, {"enabled": True}],
)
def test_settings_reject_bad_values(config: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        settings_from(config)


def test_skip_reason_order() -> None:
    empty = models.Slate.model_validate(
        {
            "schema_version": "0.1.0",
            "case_id": "59e0d31bcc42",
            "k": 5,
            "rankers_active": [],
            "fusion": {"method": "rrf", "k": 60, "weights": {}},
            "candidates": [],
            "all_scores": [],
        }
    )
    assert skip_reason(Settings(enabled=False, mode="brief"), empty) == REASON_DISABLED
    assert skip_reason(Settings(enabled=True, mode="brief"), empty) == REASON_EMPTY_SLATE


def test_fake_variant_matches_golden(tmp_path: Path) -> None:
    run_dir = _fake_dir(tmp_path)
    result = api.run(_fake_ctx(run_dir))
    assert result.status == "ok"
    assert result.notes[0] == STUB_NOTE
    assert_golden(io.read("proposals", run_dir), "proposals", FAKE_CASE)
    assert io.path_of("agent_trace", run_dir).read_bytes() == b""
    proposals = io.read_model("proposals", run_dir, models.Proposals, validate=True)
    assert proposals.status == "skipped" and proposals.model is None and proposals.proposals == []


def test_slate_with_candidates_reports_brief_mode_missing(tmp_path: Path) -> None:
    run_dir = _fake_dir(tmp_path)
    slate = io.read_model("slate", run_dir, models.Slate)
    if not slate.candidates:  # pragma: no cover - synth-01 has a non-empty universe
        pytest.skip("slate fixture has no candidates")
    assert REASON_NOT_BUILT in api.run(_fake_ctx(run_dir)).notes


def test_disabled_and_mode_come_from_config(tmp_path: Path) -> None:
    run_dir = _fake_dir(tmp_path)
    result = api.run(_fake_ctx(run_dir, **{"relentra.enabled": False, "relentra.mode": "investigate"}))
    assert REASON_DISABLED in result.notes
    assert json.loads(io.path_of("proposals", run_dir).read_text(encoding="utf-8"))["mode"] == "investigate"


def test_ai_off_writes_nothing(tmp_path: Path) -> None:
    run_dir = _fake_dir(tmp_path)
    result = api.run(make_context("relentra", run_dir, ai_mode="off"))
    assert result.status == "skipped"
    assert not io.exists("proposals", run_dir)


def test_slate_for_another_case_is_refused(tmp_path: Path) -> None:
    run_dir = _fake_dir(tmp_path)
    path = io.path_of("slate", run_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["case_id"] = "000000000000"
    io.write("slate", raw, run_dir)
    with pytest.raises(ContractValidationError):
        api.run(_fake_ctx(run_dir))
