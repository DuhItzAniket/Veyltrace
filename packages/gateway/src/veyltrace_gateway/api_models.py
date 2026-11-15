"""Gateway-only API envelopes (03 §14; 06 §3.1). Run artifacts are never redefined here.

X-00: the `health` envelope of 06 §3.2. X-04 adds the error envelope (06 §3.1) and the wrappers
of the artifact routes; their items are the generated contract models, unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from veyltrace_contracts.models import EvidenceRow
from veyltrace_core.ids import AIMode

__all__ = ["ErrorBody", "ErrorDetail", "EvidencePage", "Health", "HealthAI", "HealthLive"]


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
