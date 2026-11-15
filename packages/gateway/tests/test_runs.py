"""Artifact routes (06 §3.2, §9): every route returns its contract unchanged, on a real synth run.

One AI-off synth-01 run is made per module with `run_case`; requests go through ASGI in-process.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.ids import case_id
from veyltrace_core.pipeline import find_run, run_case
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root
from veyltrace_gateway.app import create_app
from veyltrace_gateway.runs import JSON_ARTIFACTS

CONFIG = repo_root() / "config"
OTHER_RUN = "0123456789abcdef"  # a well-formed run id no pipeline wrote


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("gw") / "runs"
    run_case("synth", case_id("synth-01"), "off", {}, runs_root=root, code_commit=FIXTURE_CODE_COMMIT)
    return root


@pytest.fixture(scope="module")
def run_id(runs: Path) -> str:
    (run_dir,) = runs.glob("synth/*/*")
    return run_dir.name


def _get(runs: Path, url: str) -> tuple[int, dict[bytes, bytes], bytes]:
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
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in sent[1:])


def _error(runs: Path, url: str) -> tuple[int, str]:
    status, _, body = _get(runs, url)
    return status, json.loads(body)["error"]["code"]


@pytest.mark.parametrize(("segment", "name"), sorted(JSON_ARTIFACTS.items()))
def test_json_artifacts_are_the_files_unchanged(runs: Path, run_id: str, segment: str, name: str) -> None:
    run_dir = find_run(run_id, runs)
    assert run_dir is not None
    status, headers, body = _get(runs, f"/api/v1/runs/{run_id}/{segment}")
    if not io.exists(name, run_dir):  # proposals: AI off (06 §3.2)
        assert (status, json.loads(body)["error"]["code"]) == (404, "artifact_missing")
        return
    assert status == 200 and headers[b"content-type"] == b"application/json"
    assert body == io.path_of(name, run_dir).read_bytes()
    CONTRACTS[name].model.model_validate_json(body)


def test_card_md_is_markdown(runs: Path, run_id: str) -> None:
    run_dir = find_run(run_id, runs)
    assert run_dir is not None
    status, headers, body = _get(runs, f"/api/v1/runs/{run_id}/card.md")
    assert status == 200 and headers[b"content-type"].startswith(b"text/markdown")
    assert body == (run_dir / "card.md").read_bytes()


def test_changes_and_evidence_rows_are_contract_rows(runs: Path, run_id: str) -> None:
    run_dir = find_run(run_id, runs)
    assert run_dir is not None
    for segment, name in (("changes", "changes"), ("evidence?limit=1000", "evidence")):
        status, _, body = _get(runs, f"/api/v1/runs/{run_id}/{segment}")
        data = json.loads(body)
        rows = data if isinstance(data, list) else data["items"]
        expected = io.read_table(name, run_dir).to_pylist()
        assert status == 200 and len(rows) == len(expected)
        assert [CONTRACTS[name].model.model_validate(r).model_dump() for r in rows] == [
            CONTRACTS[name].model.model_validate(r).model_dump() for r in expected
        ]


def test_evidence_filters_and_pages(runs: Path, run_id: str) -> None:
    rows = json.loads(_get(runs, f"/api/v1/runs/{run_id}/evidence?limit=1000")[2])["items"]
    assert rows, "synth-01 has evidence"
    candidate = rows[0]["candidate"]
    page = json.loads(_get(runs, f"/api/v1/runs/{run_id}/evidence?candidate={candidate}&limit=1&offset=1")[2])
    mine = [r for r in rows if r["candidate"] == candidate]
    assert (page["total"], page["limit"], page["offset"]) == (len(mine), 1, 1)
    assert page["items"] == mine[1:2]
    default = json.loads(_get(runs, f"/api/v1/runs/{run_id}/evidence")[2])
    assert default["limit"] == 200  # config/gateway.yaml api.evidence_limit
    assert _error(runs, f"/api/v1/runs/{run_id}/evidence?limit=1001") == (422, "invalid_request")


def test_one_atom_by_id(runs: Path, run_id: str) -> None:
    first = json.loads(_get(runs, f"/api/v1/runs/{run_id}/evidence?limit=1")[2])["items"][0]
    status, _, body = _get(runs, f"/api/v1/runs/{run_id}/evidence/{first['atom_id']}")
    assert status == 200 and json.loads(body) == first
    assert _error(runs, f"/api/v1/runs/{run_id}/evidence/Eabcdefabcd") == (404, "atom_not_found")
    assert _error(runs, f"/api/v1/runs/{run_id}/evidence/..%2Fverdict") == (404, "atom_not_found")


@pytest.mark.parametrize("bad", ["0123", "0123456789ABCDEF", "..", "..%2F..%2Fsynth", OTHER_RUN])
def test_unknown_or_malformed_run_ids_are_404(runs: Path, bad: str) -> None:
    assert _error(runs, f"/api/v1/runs/{bad}/verdict") == (404, "run_not_found")


def test_errors_use_the_envelope_for_unknown_routes(runs: Path) -> None:
    assert _error(runs, "/api/v1/nope") == (404, "not_found")
