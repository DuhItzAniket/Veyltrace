"""Relentra's outputs when no model is called: `status = skipped` (08 §2.2).

AI-on runs need a `proposals.json` and an `agent_trace.jsonl` that are honest about what happened.
No model was called, so `model` is null (03 §9.1) and no state machine ran, so the trace has no lines
and the receipt's `agent_trace_head` is null. The reasons: `relentra.enabled = false`, an empty slate
(08 §3.1 step 4), or `investigate` mode, which X-08 adds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ConfigError, ContractValidationError

__all__ = [
    "ENGINE",
    "MODES",
    "STUB_NOTE",
    "Settings",
    "build_proposals",
    "run_stub",
    "settings_from",
    "skip_reason",
]

ENGINE: Final = "relentra"
#: EngineResult.notes entry of a run without a model call, so bench and reviewers can tell them apart.
STUB_NOTE: Final = "stub: Relentra called no model"
#: proposals.mode values Relentra itself writes; `external` is only for MCP hypotheses (03 §9.1).
MODES: Final = ("brief", "investigate")
REASON_DISABLED: Final = "relentra.enabled is false"
REASON_EMPTY_SLATE: Final = "slate has no candidates (08 §3.1 step 4)"
REASON_NOT_BUILT: Final = "investigate mode is not built yet (X-08)"


@dataclass(frozen=True)
class Settings:
    """The config keys this stub reads (config/relentra.yaml; 08 §4)."""

    enabled: bool
    mode: str


def settings_from(config: Mapping[str, Any]) -> Settings:
    """Validate `enabled` and `mode`; a bad value is a ConfigError (exit 4), never a guess."""
    enabled: object = config.get("enabled")
    mode: object = config.get("mode")
    if not isinstance(enabled, bool):
        msg = f"relentra.enabled must be a bool, got {enabled!r}"
        raise ConfigError(msg)
    if mode not in MODES:
        msg = f"relentra.mode must be one of {MODES}, got {mode!r}"
        raise ConfigError(msg)
    return Settings(enabled=enabled, mode=str(mode))


def skip_reason(settings: Settings, slate: models.Slate) -> str:
    """Why this run calls no model, in the order 08 §2.2 and §3.1 check it."""
    if not settings.enabled:
        return REASON_DISABLED
    if not slate.candidates:
        return REASON_EMPTY_SLATE
    return REASON_NOT_BUILT


def build_proposals(case_id: str, settings: Settings) -> dict[str, Any]:
    """`proposals.json` for a run that called no model: skipped, no model, zero budget (03 §9.1)."""
    return {
        "schema_version": CONTRACTS["proposals"].version,
        "case_id": case_id,
        "status": "skipped",
        "mode": settings.mode,
        "model": None,
        "budget_used": {"turns": 0, "tokens_in": 0, "tokens_out": 0, "wall_ms": 0.0},
        "proposals": [],
        "asks": [],
    }


def run_stub(ctx: RunContext) -> EngineResult:
    """Pipeline step 7 (X-00 stub). With AI off the runner skips Relentra; called anyway, it
    writes nothing (08 §3.1 step 1)."""
    if ctx.ai_mode == "off":
        return EngineResult.skipped(ENGINE, "ai_mode is off (08 §3.1 step 1)")
    settings = settings_from(ctx.config)
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    slate = ctx.read_model("slate", models.Slate)
    if slate.case_id != manifest.case_id:
        msg = f"slate is for case {slate.case_id}, case_manifest for {manifest.case_id}"
        raise ContractValidationError("slate", msg)
    outputs = [("proposals", ctx.write("proposals", build_proposals(manifest.case_id, settings)))]
    outputs.append(("agent_trace", io.JsonlWriter("agent_trace", ctx.run_dir).close()))
    return EngineResult(
        engine=ENGINE,
        status="ok",
        outputs=tuple(outputs),
        notes=(STUB_NOTE, skip_reason(settings, slate)),
    )
