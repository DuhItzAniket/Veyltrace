"""Gateway-only API envelopes (03 §14; 06 §3.1). Run artifacts are never redefined here.

X-00: the `health` envelope of 06 §3.2. Its OpenAPI export (`openapi.json`) and the generated
TypeScript types arrive with X-04, together with the other envelopes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from veyltrace_core.ids import AIMode

__all__ = ["Health", "HealthAI", "HealthLive"]


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
