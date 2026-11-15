"""The job runner and `POST /runs` (06 §2, §3.2, §9): idempotent by run id, one worker, events."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_core import plugins
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import case_id
from veyltrace_core.testing import FIXTURE_CODE_COMMIT, repo_root
from veyltrace_gateway import jobs
from veyltrace_gateway.app import create_app
from veyltrace_gateway.jobs import JobRunner
from veyltrace_gateway.settings import settings_from

CONFIG = repo_root() / "config"
CASE = case_id("synth-01")
WAIT_S = 300  # a synth run takes seconds; the bound only stops a hung test


def _call(app: Any, method: str, url: str, body: object | None = None) -> tuple[int, bytes]:
    path, _, query = url.partition("?")
    raw = b"" if body is None else json.dumps(body).encode()
    headers = [(b"content-type", b"application/json")] if body is not None else []
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode(),
        "root_path": "", "headers": headers, "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }  # fmt: skip
    sent: list[dict[str, Any]] = []

    requests = [{"type": "http.request", "body": raw, "more_body": False}]

    async def receive() -> dict[str, Any]:
        if requests:
            return requests.pop()
        await asyncio.sleep(WAIT_S)  # the client stays connected; a streaming response must not spin
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(m for m in sent if m["type"] == "http.response.start")["status"]
    return status, b"".join(m.get("body", b"") for m in sent[1:])


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Any, JobRunner, Path]:
    root = tmp_path / "runs"
    runner = JobRunner(root, commit=FIXTURE_CODE_COMMIT, config_dir=CONFIG)
    return create_app(config_dir=CONFIG, runs=root, jobs=runner), runner, root


def test_post_runs_queues_once_and_the_planned_id_is_the_run_dir(setup: tuple[Any, JobRunner, Path]) -> None:
    app, runner, root = setup
    request = {"dataset": "synth", "case_id": CASE, "ai_mode": "off"}
    status, body = _call(app, "POST", "/api/v1/runs", request)
    first = json.loads(body)
    assert status == 202 and first["state"] in ("queued", "running")
    job = runner.get(first["run_id"])
    assert job is not None and job.finished.wait(WAIT_S) and job.state == "done", job and job.error
    (run_dir,) = root.glob(f"synth/{CASE}/*")
    assert run_dir.name == first["run_id"]  # 02 §4.1: the id is known before the run
    status, body = _call(app, "POST", "/api/v1/runs", request)
    assert status == 200 and json.loads(body)["state"] == "done"  # idempotent: no second run
    assert json.loads(_call(app, "GET", f"/api/v1/runs/{first['run_id']}")[1])["state"] == "done"
    stream = _call(app, "GET", f"/api/v1/runs/{first['run_id']}/events")[1].decode()
    kinds = [line.removeprefix("event: ") for line in stream.splitlines() if line.startswith("event: ")]
    assert kinds[0] == "started" and kinds[-1] == "done" and "finished" in kinds


def test_replay_without_a_recording_is_409(setup: tuple[Any, JobRunner, Path]) -> None:
    app, _, _ = setup
    status, body = _call(
        app, "POST", "/api/v1/runs", {"dataset": "synth", "case_id": CASE, "ai_mode": "replay"}
    )
    assert (status, json.loads(body)["error"]["code"]) == (409, "no_cassette")


@pytest.mark.parametrize(
    ("request_body", "status", "code"),
    [
        ({"dataset": "nope", "case_id": CASE, "ai_mode": "off"}, 404, "dataset_not_found"),
        ({"dataset": "synth", "case_id": "../x", "ai_mode": "off"}, 404, "case_not_found"),
        ({"dataset": "synth", "case_id": CASE, "ai_mode": "on"}, 422, "invalid_request"),
        ({"dataset": "synth", "case_id": CASE}, 422, "invalid_request"),
    ],
)
def test_bad_run_requests(
    setup: tuple[Any, JobRunner, Path], request_body: dict[str, str], status: int, code: str
) -> None:
    got, body = _call(setup[0], "POST", "/api/v1/runs", request_body)
    assert (got, json.loads(body)["error"]["code"]) == (status, code)
    assert setup[1].jobs() == []


def test_a_failing_run_is_reported_and_can_be_queued_again(
    setup: tuple[Any, JobRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, runner, _ = setup

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(jobs, "run_case", broken)
    request = {"dataset": "synth", "case_id": CASE, "ai_mode": "off"}
    rid = json.loads(_call(app, "POST", "/api/v1/runs", request)[1])["run_id"]
    job = runner.get(rid)
    assert job is not None and job.finished.wait(WAIT_S)
    status = json.loads(_call(app, "GET", f"/api/v1/runs/{rid}")[1])
    assert (status["state"], status["error"]) == ("failed", "RuntimeError: disk full")
    assert [s["state"] for s in json.loads(_call(app, "GET", "/api/v1/runs")[1])] == ["failed"]
    stream = _call(app, "GET", f"/api/v1/runs/{rid}/events")[1].decode()
    assert stream.splitlines()[0] == "event: failed"
    assert runner.submit("synth", CASE, "off", rid) is not job  # a failed job may be queued again
    status, body = _call(app, "GET", "/api/v1/runs/0123456789abcdef/events")
    assert (status, json.loads(body)["error"]["code"]) == (404, "run_not_found")


@pytest.mark.parametrize(
    ("dotted", "value"), [("jobs.workers", 2), ("api.events_poll_s", 0), ("api.events_poll_s", 60)]
)
def test_job_settings_are_checked(dotted: str, value: object) -> None:
    from veyltrace_core.config import load_section_file

    body = json.loads(json.dumps(load_section_file("gateway", config_dir=CONFIG), default=dict))
    section, key = dotted.split(".")
    body[section][key] = value
    with pytest.raises(ConfigError):
        settings_from(body)


def test_replay_runs_the_causivra_command_on_the_receipt(
    setup: tuple[Any, JobRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _, root = setup
    rid = "0123456789abcdef"
    (root / "synth" / CASE / rid).mkdir(parents=True)  # find_run needs only the directory
    assert _call(app, "GET", f"/api/v1/runs/{rid}/replay")[0] == 404  # nothing requested yet
    monkeypatch.setattr(plugins, "names", lambda group: ())
    status, body = _call(app, "POST", f"/api/v1/runs/{rid}/replay")
    assert (status, json.loads(body)["error"]["code"]) == (503, "replay_unavailable")
    seen: list[list[str]] = []

    def fake_replay(argv: list[str]) -> int:
        seen.append(argv)
        return 6  # only the card narrative differs (10 §3.9)

    monkeypatch.setattr(plugins, "names", lambda group: ("replay",))
    monkeypatch.setattr(plugins, "load_one", lambda group, name: fake_replay)
    status, body = _call(app, "POST", f"/api/v1/runs/{rid}/replay")
    assert status == 202 and json.loads(body)["state"] in ("queued", "running", "done")
    job = setup[1].replay(rid)
    assert job is not None and job.finished.wait(WAIT_S)
    report = json.loads(_call(app, "GET", f"/api/v1/runs/{rid}/replay")[1])
    assert report == {
        "run_id": rid,
        "state": "done",
        "exit_code": 6,
        "meaning": "narrative_mismatch",
        "error": None,
    }
    assert seen == [[str(root / "synth" / CASE / rid / "receipt.json")]]
    assert _call(app, "POST", "/api/v1/runs/fedcba9876543210/replay")[0] == 404
