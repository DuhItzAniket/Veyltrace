"""context: EngineResult/AIManifest normalisation, RunContext validation and hint redaction, RunPlan."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from veyltrace_contracts.models import CaseManifest
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.config import resolve_config
from veyltrace_core.context import AIManifest, EngineResult, RunContext, RunPlan, redact_hint
from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.ids import case_id

REPO = Path(__file__).resolve().parents[3]
CASE = case_id("synth-01")
RUN = "0123456789abcdef"
SHA_A = "a" * 64
SHA_B = "b" * 64
T0 = 1_700_000_000_000_000_000


def manifest(hint: int | None = T0 + 1320 * 10**9) -> CaseManifest:
    return CaseManifest.model_validate(
        dict(
            schema_version=CONTRACTS["case_manifest"].version,
            case_id=CASE,
            dataset="synth",
            system="ob",
            t_alert_hint_ns=hint,
            hint_source="oracle" if hint is not None else "none",
            data_start_ns=T0,
            data_end_ns=T0 + 1920 * 10**9,
            sources={"metrics": True, "logs": True, "traces": True, "events": True},
            services=["checkout", "frontend"],
            inputs=[],
            adapter={"name": "synth", "version": "1"},
            scrub={"rules_version": "1", "dropped_attributes": 0, "dropped_rows": 0},
        )
    )


def test_engine_result_sorts_and_freezes() -> None:
    r = EngineResult("x", "ok", outputs=(("slate", SHA_B), ("evidence", SHA_A)), metrics={"b": 2, "a": 1.5})
    assert r.outputs == (("evidence", SHA_A), ("slate", SHA_B))
    assert list(r.metrics) == ["a", "b"]
    with pytest.raises(TypeError):
        cast("dict[str, Any]", r.metrics)["c"] = 1
    assert r == EngineResult(
        "x", "ok", outputs=(("evidence", SHA_A), ("slate", SHA_B)), metrics={"a": 1.5, "b": 2}
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"outputs": (("a", SHA_A), ("a", SHA_B))},
        {"outputs": (("a", "nothex"),)},
        {"status": "great"},
        {"engine": ""},
        {"metrics": {"n": True}},
        {"metrics": {"n": float("nan")}},
    ],
)
def test_engine_result_rejects(kwargs: dict[str, Any]) -> None:
    base: dict[str, Any] = {"engine": "x", "status": "ok"}
    with pytest.raises((ValueError, TypeError)):
        EngineResult(**{**base, **kwargs})


def test_skipped_helper_and_ai_manifest() -> None:
    s = EngineResult.skipped("relentra", "ai off")
    assert (s.status, s.notes, s.outputs) == ("skipped", ("ai off",), ())
    ai = AIManifest("ollama", "m", None, prompts=(("z.md", SHA_A), ("a.md", SHA_B)))
    assert ai.prompts == (("a.md", SHA_B), ("z.md", SHA_A))
    with pytest.raises(ValueError, match="gguf"):
        AIManifest(None, None, "bad")


def test_redact_hint_pairs_hint_source() -> None:
    red = redact_hint(manifest())
    assert red.t_alert_hint_ns is None
    assert red.hint_source == "none"
    assert red.data_end_ns == manifest().data_end_ns


def _ctx(tmp_path: Path, step: str, **kw: Any) -> RunContext:
    resolved = resolve_config(config_dir=REPO / "config", ai_mode="off")
    engine = "core" if step == "alert" else step
    return RunContext(
        case_id=CASE,
        run_id=RUN,
        dataset="synth",
        run_dir=tmp_path,
        ai_mode="off",
        engine=engine,
        config=resolved.engine(engine),
        step=step,
        resolved=resolved,
        unredacted_hint=step in ("infralume", "alert"),
        **kw,
    )


def test_read_redacts_hint_except_infralume_and_alert(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "infralume")
    ctx.write("case_manifest", manifest())
    seen = {}
    for step in ("infralume", "alert", "signalyth", "anomara", "causentra"):
        value = _ctx(tmp_path, step).read("case_manifest")
        assert isinstance(value, CaseManifest)
        seen[step] = value.t_alert_hint_ns
    assert seen["infralume"] == seen["alert"] == T0 + 1320 * 10**9
    assert seen["signalyth"] is seen["anomara"] is seen["causentra"] is None
    assert ctx.exists("case_manifest")
    assert ctx.path("case_manifest") == tmp_path / "case_manifest.json"


def test_hint_redaction_cannot_be_bypassed(tmp_path: Path) -> None:
    """io.read redacts too, and renaming the step does not grant the hint (D-15)."""
    from dataclasses import replace

    from veyltrace_core import io

    _ctx(tmp_path, "infralume").write("case_manifest", manifest())
    signalyth = _ctx(tmp_path, "signalyth")
    for value in (
        io.read("case_manifest", tmp_path),
        io.read_path("case_manifest", tmp_path / "case_manifest.json", validate=True),
        io.read_model("case_manifest", tmp_path, CaseManifest),
        replace(signalyth, step="infralume").read("case_manifest"),
        replace(signalyth, step="alert").read("case_manifest"),
        signalyth.with_config("faultloom").read("case_manifest"),
    ):
        assert isinstance(value, CaseManifest)
        assert (value.t_alert_hint_ns, value.hint_source) == (None, "none")
    raw = io.read_unredacted("case_manifest", tmp_path)
    assert isinstance(raw, CaseManifest) and raw.t_alert_hint_ns == T0 + 1320 * 10**9
    # the capability alone is not enough: it only applies to the two hint steps
    assert not replace(signalyth, unredacted_hint=True).sees_hint


def test_context_validation_and_with_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "relentra")
    other = ctx.with_config("faultloom")
    assert other.config.engine == "faultloom"
    assert (other.step, other.engine) == ("relentra", "relentra")
    with pytest.raises(ValueError, match="case_id"):
        RunContext("XYZ", RUN, "synth", tmp_path, "off", "x", ctx.config)
    with pytest.raises(ValueError, match="phase"):
        RunContext(CASE, RUN, "synth", tmp_path, "off", "x", ctx.config, phase=cast("Any", "bad"))
    with pytest.raises(ValueError, match="step"):
        RunContext(CASE, RUN, "synth", tmp_path, "off", "x", ctx.config, step="bogus")
    bare = RunContext(CASE, RUN, "synth", tmp_path, "off", "relentra", ctx.config)
    with pytest.raises(ConfigError):
        bare.with_config("faultloom")


def test_run_plan_partial_and_validation() -> None:
    full = RunPlan("synth", CASE)
    assert (full.last_step, full.partial) == ("causivra.receipt", False)
    assert RunPlan("synth", CASE, to_step="alert").last_step == "alert"
    assert RunPlan("synth", CASE, write_receipt=False).last_step == "manifest"
    assert RunPlan("synth", CASE, write_manifest=False).last_step == "causivra.card"
    assert RunPlan("synth", CASE, to_step="causync").partial
    for bad in (
        {"dataset": "Bad/../x"},
        {"case": ""},
        {"to_step": "step-11"},
        {"from_step": "causentra", "to_step": "alert"},
        {"run_id": "short"},
        {"force_record": True},
        {"ai_mode": "on"},
        {"external_proposals": {"mode": "brief", "model": None}},  # Relentra's mode, not external
        {"external_proposals": {"mode": "external", "model": {"name": "m"}}},
    ):
        with pytest.raises(UsageError):
            RunPlan(**{"dataset": "synth", "case": CASE, **bad})


def test_run_plan_accepts_external_proposals() -> None:
    plan = RunPlan("synth", CASE, external_proposals={"mode": "external", "model": None})
    assert plan.external_proposals is not None


def test_typed_reads_keep_the_redaction(tmp_path: Path) -> None:
    from veyltrace_core.errors import ContractValidationError

    _ctx(tmp_path, "infralume").write("case_manifest", manifest())
    signalyth = _ctx(tmp_path, "signalyth")
    assert signalyth.read_model("case_manifest", CaseManifest).t_alert_hint_ns is None
    assert _ctx(tmp_path, "alert").read_model("case_manifest", CaseManifest).t_alert_hint_ns is not None
    with pytest.raises(ContractValidationError):
        signalyth.read_table("case_manifest")
