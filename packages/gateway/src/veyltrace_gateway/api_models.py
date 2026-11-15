"""Gateway-only API envelopes (03 §14; 06 §3.1). Run artifacts are never redefined here.

X-00: the `health` envelope of 06 §3.2. X-04 adds the error envelope (06 §3.1) and the wrappers
of the artifact routes; their items are the generated contract models, unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from veyltrace_contracts.models import (
    AgentTraceLine,
    EvidenceRow,
    GraphEdgesRow,
    GraphNodesRow,
    GraphPathsRow,
)
from veyltrace_core.ids import AIMode

__all__ = [
    "AgentTrace",
    "ErrorBody",
    "ErrorDetail",
    "EvidencePage",
    "GraphView",
    "Health",
    "HealthAI",
    "HealthLive",
    "RunStatus",
]


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthAI(_Envelope):
    """AI defaults the console shows. `reachable` is null until the provider probe exists (X-04)."""

    default_mode: AIMode
    provider: str
    model: str
    reachable: bool | None


class HealthLive(_Envelope):
    enabled: bool
    receiving: bool


class Health(_Envelope):
    """`GET /api/v1/health` (06 §3.2)."""

    status: Literal["ok", "degraded"]
    version: str
    code_commit: str
    ai: HealthAI
    live: HealthLive


class ErrorDetail(_Envelope):
    code: str
    message: str


class ErrorBody(_Envelope):
    """Every error response (06 §3.1)."""

    error: ErrorDetail


class EvidencePage(_Envelope):
    """`GET /runs/{run_id}/evidence`: one page of evidence rows (03 §7) after the filters."""

    items: list[EvidenceRow]
    total: int
    limit: int
    offset: int


class AgentTrace(_Envelope):
    """`GET /runs/{run_id}/agent-trace`: the trace lines (03 §9.2) and the server-side chain check."""

    lines: list[AgentTraceLine]
    chain_ok: bool


class GraphView(_Envelope):
    """`GET /runs/{run_id}/graph`: the three graph tables (03 §6) as contract rows."""

    nodes: list[GraphNodesRow]
    edges: list[GraphEdgesRow]
    paths: list[GraphPathsRow]


class RunStatus(_Envelope):
    """`run_status` (06 §3.2). `step` is core's step index (0-13), `step_name` its name."""

    run_id: str
    dataset: str
    case_id: str
    ai_mode: AIMode
    state: Literal["queued", "running", "done", "failed"]
    step: int
    step_name: str
    error: str | None
