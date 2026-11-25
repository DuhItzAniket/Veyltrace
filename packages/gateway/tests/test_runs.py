"""Artifact routes (06 §3.2, §9): every route returns its contract unchanged, on a real synth run.

One AI-off synth-01 run is made per module with `run_case`; requests go through ASGI in-process.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import shutil
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
from veyltrace_gateway.settings import load_settings

CONFIG = repo_root() / "config"
OTHER_RUN = "0123456789abcdef"  # a well-formed run id no pipeline wrote
_NULL_FIELDS = ("request_sha256", "response_sha256", "tool", "args", "result_sha256", "summary", "detail")


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("gw") / "runs"
    run_case("synth", case_id("synth-01"), "off", {}, runs_root=root, code_commit=FIXTURE_CODE_COMMIT)
    return root


@pytest.fixture(scope="module")
def run_id(runs: Path) -> str:
    (run_dir,) = runs.glob("synth/*/*")
    return run_dir.name


def _get(runs: Path, url: str, **settings: int) -> tuple[int, dict[bytes, bytes], bytes]:
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

    resolved = dataclasses.replace(load_settings(CONFIG), **settings)
    app: Any = create_app(resolved, config_dir=CONFIG, runs=runs)
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


def test_ai_off_has_no_agent_trace(runs: Path, run_id: str) -> None:
    assert _error(runs, f"/api/v1/runs/{run_id}/agent-trace") == (404, "artifact_missing")


def test_agent_trace_chain_is_checked_server_side(runs: Path, run_id: str) -> None:
    source = find_run(run_id, runs)
    assert source is not None
    copy = source.parent / OTHER_RUN
    shutil.copytree(source, copy)
    trace = copy / CONTRACTS["agent_trace"].path
    with io.JsonlWriter("agent_trace", copy) as writer:  # fills seq and the hash chain (03 §9.2)
        for state in ("start", "done"):
            writer.append({"type": "state", "state": state, **dict.fromkeys(_NULL_FIELDS)})
    try:
        status, _, body = _get(runs, f"/api/v1/runs/{OTHER_RUN}/agent-trace")
        data = json.loads(body)
        assert status == 200 and data["chain_ok"] is True and data["lines"]
        lines = trace.read_text(encoding="utf-8").splitlines()
        edited = json.loads(lines[0]) | {"detail": "edited after the fact"}
        trace.write_text("\n".join([json.dumps(edited), *lines[1:]]) + "\n", encoding="utf-8", newline="\n")
        assert json.loads(_get(runs, f"/api/v1/runs/{OTHER_RUN}/agent-trace")[2])["chain_ok"] is False
    finally:
        shutil.rmtree(copy)


def test_graph_is_the_three_tables(runs: Path, run_id: str) -> None:
    run_dir = find_run(run_id, runs)
    assert run_dir is not None
    data = json.loads(_get(runs, f"/api/v1/runs/{run_id}/graph")[2])
    for part in ("nodes", "edges", "paths"):
        assert len(data[part]) == io.read_table(f"graph.{part}", run_dir).num_rows


def test_series_filters_and_thins_per_series(runs: Path, run_id: str) -> None:
    full = json.loads(_get(runs, f"/api/v1/runs/{run_id}/series")[2])
    service, signal = full[0]["service"], full[0]["signal"]
    mine = [r for r in full if (r["service"], r["signal"]) == (service, signal)]
    assert (
        json.loads(_get(runs, f"/api/v1/runs/{run_id}/series?service={service}&signal={signal}")[2]) == mine
    )
    thin = json.loads(_get(runs, f"/api/v1/runs/{run_id}/series", series_max_points=3)[2])
    for sid in {r["series_id"] for r in full}:
        points = [r for r in full if r["series_id"] == sid]
        kept = [r for r in thin if r["series_id"] == sid]
        step = -(-len(points) // 3)
        assert kept == points[::step] and len(kept) <= 3  # every n-th point, n from the length


def test_run_status_and_listing(runs: Path, run_id: str) -> None:
    status = json.loads(_get(runs, f"/api/v1/runs/{run_id}")[2])
    assert status == {
        "run_id": run_id, "dataset": "synth", "case_id": case_id("synth-01"), "ai_mode": "off",
        "state": "done", "step": 13, "step_name": "causivra.receipt", "error": None,
    }  # fmt: skip
    assert json.loads(_get(runs, "/api/v1/runs")[2]) == [status]
    assert json.loads(_get(runs, f"/api/v1/runs?dataset=synth&case_id={case_id('synth-01')}")[2]) == [status]
    assert json.loads(_get(runs, f"/api/v1/runs?case_id={case_id('synth-02')}")[2]) == []
    assert _error(runs, "/api/v1/runs?dataset=..") == (404, "dataset_not_found")
    assert _error(runs, "/api/v1/runs?case_id=*") == (404, "case_not_found")


def _copy_with_unreadable(runs: Path, run_id: str, name: str) -> Path:
    """A copy of the run as OTHER_RUN whose `name` artifact has a schema major no reader accepts
    (as a run left on the laptop by another contract version)."""
    source = find_run(run_id, runs)
    assert source is not None
    copy = source.parent / OTHER_RUN
    shutil.copytree(source, copy)
    path = io.path_of(name, copy)
    document = json.loads(path.read_text(encoding="utf-8")) | {"schema_version": "99.0.0"}
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return copy


def test_an_unreadable_artifact_is_an_enveloped_500(runs: Path, run_id: str) -> None:
    copy = _copy_with_unreadable(runs, run_id, "verdict")
    try:
        status, headers, body = _get(runs, f"/api/v1/runs/{OTHER_RUN}/verdict")
        assert (status, headers[b"content-type"]) == (500, b"application/json")
        assert json.loads(body)["error"]["code"] == "artifact_invalid"
    finally:
        shutil.rmtree(copy)


def test_the_run_list_leaves_out_a_run_whose_manifest_is_unreadable(runs: Path, run_id: str) -> None:
    good = json.loads(_get(runs, f"/api/v1/runs/{run_id}")[2])
    copy = _copy_with_unreadable(runs, run_id, "run_manifest")
    try:
        assert json.loads(_get(runs, "/api/v1/runs?dataset=synth")[2]) == [good]
        assert _error(runs, f"/api/v1/runs/{OTHER_RUN}") == (500, "artifact_invalid")
    finally:
        shutil.rmtree(copy)


def test_errors_use_the_envelope_for_unknown_routes(runs: Path) -> None:
    assert _error(runs, "/api/v1/nope") == (404, "not_found")
