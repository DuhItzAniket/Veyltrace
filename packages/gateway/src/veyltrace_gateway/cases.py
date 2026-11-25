"""Dataset and case routes (06 §3.2; X-04): what the console can choose a run from.

Why discovery instead of a configured list: which datasets exist depends on the laptop (what was
fetched, what was run), so a dataset is known when a registered adapter accepts its name and it is
either an adapter's literal name (synth), a dataset folder under the runs root, or a fetched dataset
(its index file `${VEYLTRACE_DATA}/index/<dataset>.json`, 01 §2; only the file name is read here,
the adapter reads the index itself).

Cases are the adapter's `list_cases` plus any case that already has a run. A case's `system` and
`sources` come from the case manifest of its last finished run by run id (runs with different
overrides, such as `sources.drop`, can differ), read through `veyltrace_core.io`, which always
redacts the alert hint (D-15), so no answer key, injection time or hint is ever served. A run whose
case manifest io refuses (another contract version) is passed over, with a log line, for the
newest one that reads.
"""

# No `from __future__ import annotations`: FastAPI resolves the `limit` annotation, which uses the
# settings, at route creation (as in runs.py).
from pathlib import Path
from typing import Annotated, Final, cast

from fastapi import APIRouter, Query

from veyltrace_contracts.models import CaseManifest
from veyltrace_core import io, plugins
from veyltrace_core.adapters import ADAPTERS_GROUP, Adapter, find_adapter
from veyltrace_core.config import data_root
from veyltrace_core.errors import ContractValidationError, VeyltraceError
from veyltrace_core.ids import is_case_id, is_run_id
from veyltrace_core.log import get_logger
from veyltrace_core.pipeline import PARTIAL_SEPARATOR, is_finished
from veyltrace_gateway.api_models import CasePage, CaseSummary, DatasetSummary
from veyltrace_gateway.errors import ApiError
from veyltrace_gateway.settings import GatewaySettings

__all__ = ["INDEX_DIR", "case_router", "check_dataset", "known_datasets"]

#: Where fetchers write a dataset's index (01 §2): `<data root>/index/<dataset>.json`.
INDEX_DIR: Final = "index"
_GLOB_CHARS: Final = frozenset("*?[")
_LOG: Final = get_logger(__name__)


def _adapters() -> list[Adapter]:
    loaded = plugins.load(ADAPTERS_GROUP).values()
    return [cast(Adapter, obj() if isinstance(obj, type) else obj) for obj in loaded]


def known_datasets(runs_root: Path, data: Path) -> list[str]:
    """Datasets an adapter accepts that are a literal adapter name, run or fetched here, sorted."""
    names = {p for a in _adapters() for p in a.datasets if not _GLOB_CHARS & set(p)}
    if runs_root.is_dir():
        names |= {p.name for p in runs_root.iterdir() if p.is_dir()}
    names |= {p.stem for p in (data / INDEX_DIR).glob("*.json")}
    return sorted(n for n in names if find_adapter(n) is not None)


def check_dataset(dataset: str, runs_root: Path, data: Path) -> Adapter:
    adapter = find_adapter(dataset) if dataset in known_datasets(runs_root, data) else None
    if adapter is None:
        raise ApiError(404, "dataset_not_found", f"unknown dataset {dataset!r}")
    return adapter


def _runs_of(runs_root: Path, dataset: str, case_id: str) -> list[Path]:
    """Finished run dirs of one case, sorted by run id (both ids already validated)."""
    case_dir = runs_root / dataset / case_id
    if not case_dir.is_dir():
        return []
    return sorted(
        p for p in case_dir.iterdir()
        if is_run_id(p.name) and PARTIAL_SEPARATOR not in p.name and is_finished(p)
    )  # fmt: skip


def _case_ids(adapter: Adapter, dataset: str, runs_root: Path, data: Path) -> list[str]:
    try:
        listed = set(adapter.list_cases(dataset, data))
    except VeyltraceError:  # e.g. a dataset that was run but whose data is not on this laptop
        listed = set()
    run_dir = runs_root / dataset
    if run_dir.is_dir():
        listed |= {p.name for p in run_dir.iterdir() if is_case_id(p.name)}
    return sorted(listed)


def _newest_manifest(runs: list[Path]) -> CaseManifest | None:
    """The case manifest of the newest run (by run id) whose manifest reads, else None."""
    for run_dir in reversed(runs):
        try:
            return cast(CaseManifest, io.read("case_manifest", run_dir))  # hint redacted (D-15)
        except ContractValidationError as exc:
            _LOG.warning("case_manifest_unreadable", run_id=run_dir.name, error=str(exc))
    return None


def _summary(runs_root: Path, dataset: str, case_id: str) -> CaseSummary:
    runs = _runs_of(runs_root, dataset, case_id)
    manifest = _newest_manifest(runs)
    return CaseSummary(
        case_id=case_id,
        dataset=dataset,
        system=manifest.system if manifest else None,
        sources=manifest.sources if manifest else None,
        runs=[p.name for p in runs],
    )


def case_router(settings: GatewaySettings, runs_root: Path) -> APIRouter:
    """`/datasets`, `/cases` and `/cases/{dataset}/{case_id}` (06 §3.2)."""
    router = APIRouter()

    @router.get("/datasets", response_model=list[DatasetSummary])
    def list_datasets() -> list[DatasetSummary]:
        data = data_root()
        out: list[DatasetSummary] = []
        for name in known_datasets(runs_root, data):
            adapter = find_adapter(name)
            assert adapter is not None  # known_datasets keeps only names an adapter accepts
            out.append(DatasetSummary(dataset=name, cases=len(_case_ids(adapter, name, runs_root, data))))
        return out

    @router.get("/cases", response_model=CasePage)
    def list_cases(
        dataset: str,
        limit: Annotated[int, Query(ge=1, le=settings.page_limit_max)] = settings.page_limit_max,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CasePage:
        data = data_root()
        ids = _case_ids(check_dataset(dataset, runs_root, data), dataset, runs_root, data)
        page = [_summary(runs_root, dataset, c) for c in ids[offset : offset + limit]]
        return CasePage(items=page, total=len(ids), limit=limit, offset=offset)

    @router.get("/cases/{dataset}/{case_id}", response_model=CaseManifest)
    def get_case(dataset: str, case_id: str) -> CaseManifest:
        check_dataset(dataset, runs_root, data_root())
        if not is_case_id(case_id):
            raise ApiError(404, "case_not_found", f"{case_id!r} is not a case id")
        runs = _runs_of(runs_root, dataset, case_id)
        if not runs:
            raise ApiError(404, "case_not_run", f"case {case_id} has no finished run yet")
        manifest = _newest_manifest(runs)
        if manifest is None:
            raise ApiError(500, "artifact_invalid", f"no run of case {case_id} has a readable case manifest")
        return manifest

    return router
