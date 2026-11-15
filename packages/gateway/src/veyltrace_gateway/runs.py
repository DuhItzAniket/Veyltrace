"""Read-only artifact routes over finished run directories (06 §3.2; X-04).

Why this shape: the gateway holds no analysis logic (package rule 1), so a route only finds the run
and returns what the pipeline wrote. JSON artifacts are served as the file's own canonical bytes,
after `veyltrace_core.io` has checked the contract version, so a response can never drift from the
file a receipt hashes (06 §3.1: contract objects unchanged). Table artifacts come back as rows of
the generated contract models; the gateway adds only envelopes (pages, chain check).

A run is found by `veyltrace_core.pipeline.find_run`, which validates the 16-hex run id before it
touches the filesystem and never returns a partial run (06 §3.1; gateway rule 5).
"""

# No `from __future__ import annotations`: FastAPI resolves the `limit` annotation, which uses the
# settings, at route creation (a string annotation could not see the closure).
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Final, cast

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from veyltrace_contracts.models import ChangesRow, EvidenceRow
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.ids import is_atom_id
from veyltrace_core.pipeline import find_run
from veyltrace_gateway.api_models import EvidencePage
from veyltrace_gateway.errors import ApiError
from veyltrace_gateway.settings import GatewaySettings

__all__ = ["CARD_MD", "JSON_ARTIFACTS", "run_router"]

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


def _run_dir(root: Path, run_id: str) -> Path:
    found = find_run(run_id, root)
    if found is None:
        raise ApiError(404, "run_not_found", f"no finished run {run_id!r}")
    return found


def _read(name: str, run_dir: Path) -> Any:
    try:
        return io.read(name, run_dir)
    except ArtifactMissing as exc:  # e.g. proposals when AI is off (06 §3.2)
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


def run_router(settings: GatewaySettings, runs_root: Path) -> APIRouter:
    """The artifact routes of 06 §3.2 for runs under `runs_root`."""
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

    return router
