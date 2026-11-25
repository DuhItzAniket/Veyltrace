"""Read-only artifact routes over finished run directories (06 §3.2; X-04).

Why this shape: the gateway holds no analysis logic (package rule 1), so a route only finds the run
and returns what the pipeline wrote. JSON artifacts are served as the file's own canonical bytes,
after `veyltrace_core.io` has checked the contract version, so a response can never drift from the
file a receipt hashes (06 §3.1: contract objects unchanged). Table artifacts come back as rows of
the generated contract models; the gateway adds only envelopes (pages, chain check).

A run is found by `finished_run`: `veyltrace_core.pipeline.find_run` validates the 16-hex run id
before it touches the filesystem and skips `~` partial runs (06 §3.1; gateway rule 5), and
`is_finished` then requires the receipt, the last file a run writes. A full run's directory exists
from its first step, so without the receipt check a run still being written, or one that crashed,
would be served as finished.
"""

# No `from __future__ import annotations`: FastAPI resolves the `limit` annotation, which uses the
# settings, at route creation (a string annotation could not see the closure).
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Final, cast

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from veyltrace_contracts.models import (
    AgentTraceLine,
    ChangesRow,
    EvidenceRow,
    GraphEdgesRow,
    GraphNodesRow,
    GraphPathsRow,
    RunManifest,
    SignalCubeSeriesRow,
)
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.adapters import find_adapter
from veyltrace_core.errors import ArtifactMissing, ChainBroken, ContractValidationError
from veyltrace_core.hashing import verify_chain
from veyltrace_core.ids import is_atom_id, is_case_id, is_run_id
from veyltrace_core.log import get_logger
from veyltrace_core.pipeline import PARTIAL_SEPARATOR, find_run, is_finished
from veyltrace_core.steps import STEPS
from veyltrace_gateway.api_models import AgentTrace, EvidencePage, GraphView, RunStatus
from veyltrace_gateway.errors import ApiError
from veyltrace_gateway.jobs import Job, JobRunner
from veyltrace_gateway.settings import GatewaySettings

__all__ = ["CARD_MD", "JSON_ARTIFACTS", "finished_run", "finished_status", "job_status", "run_router"]

#: JSON artifact routes of 06 §3.2: path segment -> contract name.
JSON_ARTIFACTS: Final[Mapping[str, str]] = {
    "alert": "alert",
    "slate": "slate",
    "proposals": "proposals",
    "verdict": "verdict",
    "card": "card",
    "receipt": "receipt",
    "run-manifest": "run_manifest",
    "onsets": "onsets",
}
#: The rendered card (02 §4.1); Markdown, not a contract.
CARD_MD: Final = "card.md"
_JSON: Final = "application/json"
_LOG: Final = get_logger(__name__)


def finished_run(root: Path, run_id: str) -> Path | None:
    """The directory of the finished run `run_id` (it has its receipt), else None."""
    found = find_run(run_id, root)
    return found if found is not None and is_finished(found) else None


def _run_dir(root: Path, run_id: str) -> Path:
    found = finished_run(root, run_id)
    if found is None:
        raise ApiError(404, "run_not_found", f"no finished run {run_id!r}")
    return found


def _read(name: str, run_dir: Path) -> Any:
    try:
        return io.read(name, run_dir)
    except ArtifactMissing as exc:  # e.g. proposals and agent_trace when AI is off (06 §3.2)
        raise ApiError(404, "artifact_missing", f"this run has no {name}") from exc


def _json_route(root: Path, name: str) -> Callable[[str], Response]:
    def get(run_id: str) -> Response:
        run_dir = _run_dir(root, run_id)
        _read(name, run_dir)  # version and schema check before serving the bytes
        return Response(io.path_of(name, run_dir).read_bytes(), media_type=_JSON)

    return get


def _rows[M: BaseModel](name: str, run_dir: Path, model: type[M]) -> list[M]:
    table = _read(name, run_dir)
    return [model.model_validate(row) for row in cast(list[dict[str, Any]], table.to_pylist())]


def finished_status(run_dir: Path) -> RunStatus:
    """A finished run's status; `job_status` reports queued, running and failed runs."""
    manifest = cast(RunManifest, _read("run_manifest", run_dir))
    last = STEPS[-1]  # `step` is core's sub-step index, 0-13 (06 §3.2)
    return RunStatus(
        run_id=manifest.run_id, dataset=manifest.dataset, case_id=manifest.case_id, ai_mode=manifest.ai.mode,
        state="done", step=last.index, step_name=last.name, error=None,
    )  # fmt: skip


def _listed_status(run_dir: Path) -> RunStatus | None:
    """A finished run's status for `GET /runs`, or None (logged) when its manifest is unreadable:
    one run left by another contract version must not hide every other run. `GET /runs/{id}`
    still answers 500 `artifact_invalid` for it."""
    try:
        return finished_status(run_dir)
    except ContractValidationError as exc:
        _LOG.warning("run_unreadable", run_id=run_dir.name, error=str(exc))
        return None


def _finished_runs(root: Path, dataset: str | None, case_id: str | None) -> list[Path]:
    """Finished run dirs, sorted; the filters are validated before they reach a glob (rule 5)."""
    if dataset is not None and find_adapter(dataset) is None:
        raise ApiError(404, "dataset_not_found", f"unknown dataset {dataset!r}")
    if case_id is not None and not is_case_id(case_id):
        raise ApiError(404, "case_not_found", f"{case_id!r} is not a case id")
    pattern = f"{dataset or '*'}/{case_id or '*'}/*"
    return sorted(
        p for p in root.glob(pattern)
        if is_run_id(p.name) and PARTIAL_SEPARATOR not in p.name and is_finished(p)
    )  # fmt: skip


def _series(run_dir: Path, service: str | None, signal: str | None, max_points: int) -> list[Any]:
    """Rows of `signal_cube.series` after the filters, at most `max_points` per series: every n-th
    point, n fixed by the series length (06 §3.2; display only).

    Why rows are chosen from three columns first: a real case has about a million rows, and only
    the rows returned are worth converting and validating.
    """
    table = _read("signal_cube.series", run_dir)
    keys = zip(*(table.column(c).to_pylist() for c in ("series_id", "service", "signal")), strict=True)
    by_series: dict[str, list[int]] = {}
    for index, (series_id, row_service, row_signal) in enumerate(keys):
        if service in (None, row_service) and signal in (None, row_signal):
            by_series.setdefault(series_id, []).append(index)
    keep = [i for points in by_series.values() for i in points[:: -(-len(points) // max_points)]]
    return table.take(keep).to_pylist() if keep else []


def job_status(job: Job) -> RunStatus:
    """A queued, running or failed job's status (06 §3.2 run_status)."""
    return RunStatus(
        run_id=job.run_id, dataset=job.dataset, case_id=job.case_id, ai_mode=job.ai_mode,
        state=job.state, step=job.step, step_name=job.step_name, error=job.error,
    )  # fmt: skip


def run_router(settings: GatewaySettings, runs_root: Path, runner: JobRunner | None = None) -> APIRouter:
    """The artifact routes of 06 §3.2 for runs under `runs_root`; status also reports `runner`'s
    queued, running and failed jobs (a done job is its run directory)."""
    router = APIRouter()
    for segment, name in JSON_ARTIFACTS.items():
        model = cast(type[BaseModel], CONTRACTS[name].model)
        router.add_api_route(
            f"/runs/{{run_id}}/{segment}",
            _json_route(runs_root, name),
            methods=["GET"],
            response_class=Response,
            responses={200: {"model": model, "content": {_JSON: {}}}},
            name=f"get_{name}",
        )

    @router.get(
        "/runs/{run_id}/card.md", response_class=Response, responses={200: {"content": {"text/markdown": {}}}}
    )
    def get_card_md(run_id: str) -> Response:
        path = _run_dir(runs_root, run_id) / CARD_MD
        if not path.is_file():
            raise ApiError(404, "artifact_missing", f"this run has no {CARD_MD}")
        return Response(path.read_bytes(), media_type="text/markdown; charset=utf-8")

    @router.get("/runs/{run_id}/changes", response_model=list[ChangesRow])
    def get_changes(run_id: str) -> list[ChangesRow]:
        return _rows("changes", _run_dir(runs_root, run_id), ChangesRow)

    @router.get("/runs/{run_id}/evidence", response_model=EvidencePage)
    def get_evidence(
        run_id: str,
        candidate: str | None = None,
        kind: str | None = None,
        origin: str | None = None,
        limit: Annotated[int, Query(ge=1, le=settings.page_limit_max)] = settings.evidence_limit,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> EvidencePage:
        rows = [
            r
            for r in _rows("evidence", _run_dir(runs_root, run_id), EvidenceRow)
            if (candidate is None or r.candidate == candidate)
            and (kind is None or r.kind == kind)
            and (origin is None or r.origin == origin)
        ]
        return EvidencePage(items=rows[offset : offset + limit], total=len(rows), limit=limit, offset=offset)

    @router.get("/runs/{run_id}/evidence/{atom_id}", response_model=EvidenceRow)
    def get_atom(run_id: str, atom_id: str) -> EvidenceRow:
        if not is_atom_id(atom_id):
            raise ApiError(404, "atom_not_found", f"{atom_id!r} is not an atom id")
        rows = _rows("evidence", _run_dir(runs_root, run_id), EvidenceRow)
        found = next((r for r in rows if r.atom_id == atom_id), None)
        if found is None:
            raise ApiError(404, "atom_not_found", f"this run has no atom {atom_id}")
        return found

    @router.get("/runs/{run_id}/agent-trace", response_model=AgentTrace)
    def get_agent_trace(run_id: str) -> AgentTrace:
        lines = cast(list[AgentTraceLine], _read("agent_trace", _run_dir(runs_root, run_id)))
        try:
            verify_chain(lines)
            chain_ok = True
        except ChainBroken:
            chain_ok = False
        return AgentTrace(lines=lines, chain_ok=chain_ok)

    @router.get("/runs/{run_id}/graph", response_model=GraphView)
    def get_graph(run_id: str) -> GraphView:
        run_dir = _run_dir(runs_root, run_id)
        return GraphView(
            nodes=_rows("graph.nodes", run_dir, GraphNodesRow),
            edges=_rows("graph.edges", run_dir, GraphEdgesRow),
            paths=_rows("graph.paths", run_dir, GraphPathsRow),
        )

    @router.get("/runs/{run_id}/series", response_model=list[SignalCubeSeriesRow])
    def get_series(
        run_id: str, service: str | None = None, signal: str | None = None
    ) -> list[SignalCubeSeriesRow]:
        rows = _series(_run_dir(runs_root, run_id), service, signal, settings.series_max_points)
        return [SignalCubeSeriesRow.model_validate(row) for row in rows]

    @router.get("/runs/{run_id}", response_model=RunStatus)
    def get_run(run_id: str) -> RunStatus:
        job = runner.get(run_id) if runner is not None else None
        if job is not None and job.state != "done":
            return job_status(job)
        return finished_status(_run_dir(runs_root, run_id))

    @router.get("/runs", response_model=list[RunStatus])
    def list_runs(dataset: str | None = None, case_id: str | None = None) -> list[RunStatus]:
        listed = {p.name: _listed_status(p) for p in _finished_runs(runs_root, dataset, case_id)}
        done = {run_id: status for run_id, status in listed.items() if status is not None}
        pending = {
            j.run_id: job_status(j)
            for j in (runner.jobs() if runner is not None else [])
            if j.state != "done" and j.run_id not in listed
            and dataset in (None, j.dataset) and case_id in (None, j.case_id)
        }  # fmt: skip
        return [s for _, s in sorted({**done, **pending}.items())]

    return router
