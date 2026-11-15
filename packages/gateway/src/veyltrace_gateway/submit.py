"""`POST /runs` and the run event stream (06 §3.2). The run id is known first (02 §4.1): a finished
run is 200, a queued or running one 202; replay without a record run's cassette is 409."""

# No `from __future__ import annotations`: FastAPI reads the route annotations at creation.
import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from veyltrace_core.config import data_root
from veyltrace_core.ids import is_case_id, is_run_id
from veyltrace_core.pipeline import CASSETTE_DIR, find_run, run_dir_for
from veyltrace_gateway.api_models import RunRequest
from veyltrace_gateway.cases import check_dataset
from veyltrace_gateway.errors import ApiError
from veyltrace_gateway.jobs import Job, JobRunner
from veyltrace_gateway.runs import finished_status, job_status
from veyltrace_gateway.settings import GatewaySettings

__all__ = ["submit_router"]

_FINAL: Final = frozenset({"done", "failed"})


def _sse(event: str, data: dict[str, object]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, sort_keys=True)}\n\n".encode()


def submit_router(settings: GatewaySettings, runs_root: Path, runner: JobRunner) -> APIRouter:
    router = APIRouter()

    @router.post("/runs", status_code=202, responses={200: {"description": "the run already exists"}})
    def post_run(request: RunRequest) -> JSONResponse:
        check_dataset(request.dataset, runs_root, data_root())
        if not is_case_id(request.case_id):
            raise ApiError(404, "case_not_found", f"{request.case_id!r} is not a case id")
        rid = runner.plan_run_id(request.case_id, request.ai_mode, request.dataset)
        found = find_run(rid, runs_root)
        if found is not None:
            return JSONResponse(finished_status(found).model_dump(mode="json"), status_code=200)
        if request.ai_mode == "replay":
            record = runner.plan_run_id(request.case_id, "record", request.dataset)
            cassette = run_dir_for(runs_root, request.dataset, request.case_id, record) / CASSETTE_DIR
            if not cassette.is_dir():
                raise ApiError(409, "no_cassette", "replay needs a finished record run of this case")
        job = runner.submit(request.dataset, request.case_id, request.ai_mode, rid)
        return JSONResponse(job_status(job).model_dump(mode="json"), status_code=202)

    @router.get("/runs/{run_id}/events", response_class=StreamingResponse)
    async def run_events(run_id: str) -> StreamingResponse:
        job = runner.get(run_id) if is_run_id(run_id) else None
        if job is None and find_run(run_id, runs_root) is None:
            raise ApiError(404, "run_not_found", f"no run {run_id!r}")
        return StreamingResponse(_events(job, settings.events_poll_s), media_type="text/event-stream")

    return router


async def _events(job: Job | None, poll_s: float) -> AsyncIterator[bytes]:
    """Step events as they happen, then done or failed; a finished run on disk is just `done`."""
    if job is None:
        yield _sse("done", {})
        return
    sent = 0
    while True:
        new, final = job.events[sent:], job.state in _FINAL
        for event in new:
            yield _sse(str(event["event"]), event)
        sent += len(new)
        if final and sent == len(job.events):
            return
        await asyncio.sleep(poll_s)
