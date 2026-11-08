"""log: structured events on stderr, no timestamps, compatible with pytest log capture."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from veyltrace_core.log import NAMESPACE, configure, get_logger

TIME_KEYS = {"time", "timestamp", "ts", "asctime", "created", "msecs", "host", "hostname", "user"}


@pytest.fixture(autouse=True)
def _reset_namespace_logger() -> Iterator[None]:
    root = logging.getLogger(NAMESPACE)
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _stderr_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    captured = capsys.readouterr()
    assert captured.out == ""  # never stdout: the CLI may print results there
    return [line for line in captured.err.splitlines() if line]


def test_json_lines_on_stderr_without_timestamps(capsys: pytest.CaptureFixture[str]) -> None:
    configure(level="info", fmt="json")
    log = get_logger("veyltrace_signalyth.api")
    log.info("drain3_fallback", templates=12, ratio=0.1234567891234, path=Path("a/b"))
    lines = _stderr_lines(capsys)
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {
        "event": "drain3_fallback",
        "level": "info",
        "logger": "veyltrace.signalyth.api",
        "path": str(Path("a/b")),  # non-JSON values are logged as str
        "ratio": 0.123456789,
        "templates": 12,
    }
    assert not TIME_KEYS & set(record)
    assert lines[0] == json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_text_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure(level="debug", fmt="text")
    get_logger("core.pipeline").debug("step_started", step="alert", index=1)
    get_logger("core.pipeline").info("plain")
    assert _stderr_lines(capsys) == [
        'debug veyltrace.core.pipeline step_started index=1 step="alert"',
        "info veyltrace.core.pipeline plain",
    ]


def test_level_filtering(capsys: pytest.CaptureFixture[str]) -> None:
    configure(level="warning")
    log = get_logger("causync")
    assert not log.is_enabled("info")
    log.info("hidden")
    log.warning("shown")
    assert [json.loads(line)["event"] for line in _stderr_lines(capsys)] == ["shown"]


def test_bind_and_reserved_keys(capsys: pytest.CaptureFixture[str]) -> None:
    configure()
    log = get_logger("faultloom").bind(case_id="59e0d31bcc42", step="faultloom")
    log.info("atoms_built", n=3, level="custom", event="clash")
    record = json.loads(_stderr_lines(capsys)[0])
    assert record["case_id"] == "59e0d31bcc42"
    assert record["step"] == "faultloom"
    assert record["event"] == "atoms_built"
    assert record["level"] == "info"
    assert record["field.level"] == "custom"
    assert record["field.event"] == "clash"


def test_error_with_exception(capsys: pytest.CaptureFixture[str]) -> None:
    configure()
    get_logger("core").error("step_failed", exc=ValueError("bad window"), step="alert")
    record = json.loads(_stderr_lines(capsys)[0])
    assert record["error"] == "ValueError: bad window"
    assert record["level"] == "error"


def test_configure_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    configure()
    configure()
    get_logger("core").info("once")
    assert len(_stderr_lines(capsys)) == 1


def test_logger_names_share_the_namespace() -> None:
    assert get_logger("veyltrace_core.hashing").name == "veyltrace.core.hashing"
    assert get_logger("signalyth").name == "veyltrace.signalyth"
    assert get_logger("veyltrace.bench").name == "veyltrace.bench"
    assert get_logger("veyltrace").name == "veyltrace"


def test_records_reach_caplog(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=NAMESPACE):
        get_logger("anomara").info("onsets", n=2)
    assert [r.getMessage() for r in caplog.records] == ["onsets"]
    assert caplog.records[0].name == "veyltrace.anomara"
