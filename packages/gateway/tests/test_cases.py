"""Dataset and case routes (06 §3.2, §9): discovery, paging, and a case manifest without the hint."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from veyltrace_core import plugins
from veyltrace_core.adapters import ADAPTERS_GROUP, Adapter
from veyltrace_core.config import DATA_ENV
from veyltrace_core.ids import case_id
from veyltrace_core.pipeline import run_case
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, SYNTH_CASES, repo_root
from veyltrace_gateway.app import create_app

if TYPE_CHECKING:
    from veyltrace_core.adapters import CanonicalCase, CaseRef
    from veyltrace_core.config import EngineConfig

CONFIG = repo_root() / "config"
RUN_CASE = case_id("synth-01")
SNAPSHOT_ID = "ab" * 16  # 32 hex, the shape of a gateway snapshot id (06 §3.4)


@dataclass(frozen=True)
class _LiveAdapter:
    """Stands in for Infralume's `otlp_live` (O-07): the dataset `live`, one case per snapshot listed
    in `index/live.json`. Only listing is needed here; reading a snapshot is Infralume's test."""

    name: str = "fake_live"
    version: str = "1"
    datasets: tuple[str, ...] = ("live",)
    cacheable: bool = False

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        raise NotImplementedError

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        index = data_root / "index" / "live.json"
        return sorted(json.loads(index.read_text(encoding="utf-8"))) if index.is_file() else []

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        raise NotImplementedError

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        raise NotImplementedError


def _datasets(obj: object) -> tuple[str, ...]:
    adapter = cast("Adapter", obj() if isinstance(obj, type) else obj)
    return adapter.datasets


def _register(monkeypatch: pytest.MonkeyPatch, *, live: bool) -> None:
    """Fix the adapter registry so these tests do not depend on what other packages install: the
    installed adapters minus any that reads `live`, plus the fake `live` adapter when `live`."""
    real = plugins.load

    def load(group: str) -> dict[str, object]:
        found = real(group)
        if group != ADAPTERS_GROUP:
            return found
        kept = {n: o for n, o in found.items() if "live" not in _datasets(o)}
        return kept | ({"fake_live": _LiveAdapter()} if live else {})

    monkeypatch.setattr(plugins, "load", load)


@pytest.fixture(autouse=True)
def adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, live=True)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("gw-cases") / "runs"
    run_case("synth", RUN_CASE, "off", {}, runs_root=root, code_commit=FIXTURE_CODE_COMMIT)
    return root


@pytest.fixture(autouse=True)
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(DATA_ENV, str(tmp_path / "data"))  # an empty data root unless a test fills it
    return tmp_path / "data"


def _get(runs: Path, url: str) -> tuple[int, Any]:
    path, _, query = url.partition("?")
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
        "root_path": "", "headers": [], "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }  # fmt: skip
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    app: Any = create_app(config_dir=CONFIG, runs=runs)
    asyncio.run(app(scope, receive, send))
    status = next(m for m in sent if m["type"] == "http.response.start")["status"]
    return status, json.loads(b"".join(m.get("body", b"") for m in sent[1:]))


def test_datasets_are_discovered(runs: Path, data: Path) -> None:
    assert _get(runs, "/api/v1/datasets") == (
        200,
        [{"dataset": "live", "cases": 0}, {"dataset": "synth", "cases": len(SYNTH_CASES)}],
    )
    (data / "index").mkdir(parents=True)
    (data / "index" / "re2-ob.json").write_text('{"aaaaaaaaaaaa": "rcaeval/hf/x"}', encoding="utf-8")
    (data / "index" / "not-a-dataset.json").write_text("{}", encoding="utf-8")  # no adapter: ignored
    assert _get(runs, "/api/v1/datasets")[1] == [
        {"dataset": "live", "cases": 0},
        {"dataset": "re2-ob", "cases": 1},
        {"dataset": "synth", "cases": len(SYNTH_CASES)},
    ]


def test_live_is_listed_with_its_adapter_and_snapshots_become_cases(runs: Path, data: Path) -> None:
    # 06 §3.2: an adapter's literal dataset name is known, so `live` is listed (0 cases) as soon
    # as `otlp_live` is installed; a "Diagnose now" snapshot in `index/live.json` is then a case.
    assert _get(runs, "/api/v1/cases?dataset=live")[1]["total"] == 0
    (data / "index").mkdir(parents=True)
    snap_case = case_id(SNAPSHOT_ID)
    index = {snap_case: f"live/{SNAPSHOT_ID}"}
    (data / "index" / "live.json").write_text(json.dumps(index), encoding="utf-8")
    assert {"dataset": "live", "cases": 1} in _get(runs, "/api/v1/datasets")[1]
    page = _get(runs, "/api/v1/cases?dataset=live")[1]
    assert [(c["case_id"], c["runs"], c["system"]) for c in page["items"]] == [(snap_case, [], None)]


def test_live_is_not_listed_without_its_adapter(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, live=False)  # main before O-07: no adapter reads `live`
    assert _get(runs, "/api/v1/datasets")[1] == [{"dataset": "synth", "cases": len(SYNTH_CASES)}]
    status, body = _get(runs, "/api/v1/cases?dataset=live")
    assert (status, body["error"]["code"]) == (404, "dataset_not_found")


def test_cases_page_with_runs_and_manifest_facts(runs: Path) -> None:
    status, page = _get(runs, "/api/v1/cases?dataset=synth")
    assert status == 200 and page["total"] == len(SYNTH_CASES)
    ids = [c["case_id"] for c in page["items"]]
    assert ids == sorted(case_id(n) for n in SYNTH_CASES)
    (ran,) = [c for c in page["items"] if c["runs"]]
    assert ran["case_id"] == RUN_CASE and ran["system"] and ran["sources"]
    assert all(c["system"] is None and c["sources"] is None for c in page["items"] if c is not ran)
    second = _get(runs, "/api/v1/cases?dataset=synth&limit=2&offset=1")[1]
    assert [c["case_id"] for c in second["items"]] == ids[1:3] and second["total"] == len(SYNTH_CASES)


def test_case_manifest_never_carries_the_hint(runs: Path) -> None:
    (run_dir,) = runs.glob(f"synth/{RUN_CASE}/*")
    on_disk = json.loads((run_dir / "case_manifest.json").read_text(encoding="utf-8"))
    assert on_disk["t_alert_hint_ns"] is not None  # synth carries an oracle hint on disk
    status, manifest = _get(runs, f"/api/v1/cases/synth/{RUN_CASE}")
    assert status == 200 and manifest["case_id"] == RUN_CASE
    assert (manifest["t_alert_hint_ns"], manifest["hint_source"]) == (None, "none")
    assert "t_alert_hint_ns" not in json.dumps(_get(runs, "/api/v1/cases?dataset=synth")[1])


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("/api/v1/cases?dataset=nope", "dataset_not_found"),
        ("/api/v1/cases?dataset=..", "dataset_not_found"),
        ("/api/v1/cases/nope/" + RUN_CASE, "dataset_not_found"),
        ("/api/v1/cases/synth/..", "case_not_found"),
        ("/api/v1/cases/synth/ZZZZZZZZZZZZ", "case_not_found"),
        ("/api/v1/cases/synth/" + case_id("synth-02"), "case_not_run"),
    ],
)
def test_unknown_or_unrun_cases_are_404(runs: Path, url: str, code: str) -> None:
    status, body = _get(runs, url)
    assert (status, body["error"]["code"]) == (404, code)


def test_an_unreadable_newest_run_leaves_the_case_facts_of_an_older_one(runs: Path) -> None:
    (run_dir,) = runs.glob(f"synth/{RUN_CASE}/*")
    newest = run_dir.parent / "ffffffffffffffff"  # sorts after every real run id
    shutil.copytree(run_dir, newest)
    path = newest / "case_manifest.json"  # as left by another contract major
    document = json.loads(path.read_text(encoding="utf-8")) | {"schema_version": "99.0.0"}
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    try:
        status, page = _get(runs, "/api/v1/cases?dataset=synth")
        (ran,) = [c for c in page["items"] if c["case_id"] == RUN_CASE]
        assert status == 200 and ran["runs"] == [run_dir.name, newest.name] and ran["system"]
        status, manifest = _get(runs, f"/api/v1/cases/synth/{RUN_CASE}")
        assert status == 200 and manifest["case_id"] == RUN_CASE
    finally:
        shutil.rmtree(newest)


def test_cases_needs_a_dataset(runs: Path) -> None:
    status, body = _get(runs, "/api/v1/cases")
    assert (status, body["error"]["code"]) == (422, "invalid_request")
