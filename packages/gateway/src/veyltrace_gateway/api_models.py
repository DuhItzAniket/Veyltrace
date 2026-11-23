"""Gateway-only API envelopes (03 §14; 06 §3.1). Run artifacts are never redefined here.

X-00: the `health` envelope of 06 §3.2. X-04 adds the error envelope (06 §3.1) and the wrappers
of the artifact routes; their items are the generated contract models, unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from veyltrace_contracts.models import (
    AgentTraceLine,
    EvidenceRow,
    GraphEdgesRow,
    GraphNodesRow,
    GraphPathsRow,
    Sources,
    System,
)
from veyltrace_core.ids import AIMode

__all__ = [
    "AgentTrace",
    "CasePage",
    "CaseSummary",
    "DatasetSummary",
    "ErrorBody",
    "ErrorDetail",
    "EvidencePage",
    "GraphView",
    "Health",
    "HealthAI",
    "HealthLive",
    "LiveRequest",
    "LiveSnapshot",
    "LiveStatus",
    "ReplayReport",
    "RunRequest",
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


class DatasetSummary(_Envelope):
    """`GET /datasets` (06 §3.2): a dataset this laptop knows and its case count."""

    dataset: str
    cases: int


class CaseSummary(_Envelope):
    """`case_summary` (06 §3.2). `system` and `sources` come from the newest finished run's case
    manifest and are null before the case's first run; never answer keys or hints."""

    case_id: str
    dataset: str
    system: System | None
    sources: Sources | None
    runs: list[str]


class CasePage(_Envelope):
    """`GET /cases`: one page of case summaries, sorted by case id."""

    items: list[CaseSummary]
    total: int
    limit: int
    offset: int


class RunRequest(_Envelope):
    """`POST /runs` body (06 §3.2)."""

    dataset: str
    case_id: str
    ai_mode: AIMode


class ReplayReport(_Envelope):
    """`replay_report` (06 §3.2; 10 §3.9): the replay's state and exit code with its meaning
    (`veyltrace_core.errors.ReplayExit`, e.g. 0 ok, 2 hash_mismatch, 6 narrative_mismatch)."""

    run_id: str
    state: Literal["queued", "running", "done", "failed"]
    exit_code: int | None
    meaning: str | None
    error: str | None


class LiveRequest(_Envelope):
    """`POST /live/diagnose` and `/live/snapshot` body (06 §3.4): minutes of data before the
    trigger, default `live.snapshot_before_min`."""

    before_min: int | None = Field(default=None, ge=1)


class LiveSnapshot(_Envelope):
    """`POST /live/snapshot` (06 §3.4): the content-derived id of the snapshot written."""

    snapshot_id: str


class LiveStatus(_Envelope):
    """`live_status` (06 §3.4) without the watcher fields: the alert watcher is cut to v1.1
    (#227), so its state and last alert time arrive with it. Rows and bytes are per source;
    data times are ns; `requests` counts the receiver's accepted, duplicate and rejected bodies."""

    receiving: bool
    seconds_since_last_batch: float | None
    rows: dict[str, int]
    bytes: dict[str, int]
    oldest_ns: int | None
    newest_ns: int | None
    requests: dict[str, int]
    snapshots: list[str]
    run_ids: list[str]
