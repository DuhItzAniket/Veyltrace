"""`/api/v1/live/*` (06 §3.4): status, snapshot and "Diagnose now".

"Diagnose now" takes the click time as `t_trigger_ns` (02 §5.1 "Live"), writes the snapshot,
hashed, before any run starts (package rule 6), then queues one run per `live.ai_modes` with
`dataset = live`, AI off first. Infralume's `otlp_live` adapter reads the snapshot and writes the
hint (`hint_source = live`), and core's alert step turns it into `alert.json`, so the gateway holds
no analysis logic. The clock is injected so tests fix the trigger.
"""

# No `from __future__ import annotations`: FastAPI reads the route annotations at creation.
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from veyltrace_core.config import data_root
from veyltrace_core.errors import ContractValidationError
from veyltrace_gateway.api_models import LiveRequest, LiveSnapshot, LiveStatus, RunStatus
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.errors import ApiError
from veyltrace_gateway.jobs import JobRunner
from veyltrace_gateway.otlp import ReceiverCounters
from veyltrace_gateway.runs import finished_run, finished_status, job_status
from veyltrace_gateway.settings import GatewaySettings
from veyltrace_gateway.snapshot import LIVE_DATASET, Snapshot, write_snapshot

__all__ = ["live_router"]


def live_router(
    settings: GatewaySettings,
    buffer: LiveBuffer | None,
    counters: ReceiverCounters | None,
    runs_root: Path,
    runner: JobRunner,
    clock: Callable[[], int] = time.time_ns,
) -> APIRouter:
    router = APIRouter()
    snapshots: list[str] = []
    run_ids: list[str] = []

    def live() -> LiveBuffer:
        if buffer is None:
            raise ApiError(503, "live_disabled", "the live receiver is off (gateway.live.enabled)")
        return buffer

    def snapshot(request: LiveRequest | None) -> Snapshot:
        before = request.before_min if request and request.before_min else settings.live.snapshot_before_min
        if before > settings.live.buffer_minutes:
            raise ApiError(422, "invalid_request", f"before_min exceeds live.buffer_minutes ({before})")
        try:
            snap = write_snapshot(live(), data_root(), clock(), before, "manual")
        except ContractValidationError as exc:
            raise ApiError(409, "snapshot_conflict", str(exc)) from None
        if snap is None:
            raise ApiError(409, "buffer_empty", f"no live data in the last {before} min")
        if snap.snapshot_id not in snapshots:
            snapshots.append(snap.snapshot_id)
        return snap

    @router.get("/live/status", response_model=LiveStatus)
    def get_status() -> LiveStatus:
        stats = live().stats()
        tally = counters or ReceiverCounters()
        return LiveStatus(
            receiving=live().receiving(settings.live.receiving_s),
            seconds_since_last_batch=stats.seconds_since_last,
            rows=stats.rows,
            bytes=stats.bytes,
            oldest_ns=stats.oldest_ns,
            newest_ns=stats.newest_ns,
            requests={"accepted": tally.accepted, "duplicate": tally.duplicate, "rejected": tally.rejected},
            snapshots=list(snapshots),
            run_ids=list(run_ids),
        )

    @router.post("/live/snapshot", response_model=LiveSnapshot)
    def post_snapshot(request: LiveRequest | None = None) -> LiveSnapshot:
        return LiveSnapshot(snapshot_id=snapshot(request).snapshot_id)

    @router.post("/live/diagnose", status_code=202, response_model=RunStatus)
    def post_diagnose(request: LiveRequest | None = None) -> JSONResponse:
        snap = snapshot(request)
        first: RunStatus | None = None
        for mode in settings.live.ai_modes:  # AI off first (06 §3.4)
            rid = runner.plan_run_id(snap.case_id, mode, LIVE_DATASET)
            done = finished_run(runs_root, rid)  # the same snapshot twice: the run already exists
            status = (
                finished_status(done)
                if done
                else job_status(runner.submit(LIVE_DATASET, snap.case_id, mode, rid))
            )
            first = first or status
            if rid not in run_ids:
                run_ids.append(rid)
        assert first is not None  # live.ai_modes is never empty (settings)
        return JSONResponse(first.model_dump(mode="json"), status_code=202)

    return router
