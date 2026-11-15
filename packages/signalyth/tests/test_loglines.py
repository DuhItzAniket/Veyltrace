"""Log lines (02 §3.5 steps 1, 2, 7): first line, masking order, error lexicon."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest

from veyltrace_core import duck
from veyltrace_core.config import resolve_config
from veyltrace_signalyth.loglines import LogRules, load_lines

CONFIG = resolve_config({}, ai_mode="off").engine("signalyth")
RULES = LogRules.from_config(CONFIG)


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with duck.connect(CONFIG, tmp_path) as connection:
        yield connection


def _lines(
    con: duckdb.DuckDBPyConnection, bodies: list[str], severity: str | None = "INFO", rules: LogRules = RULES
) -> list[tuple[Any, ...]]:
    logs = pa.table(
        {
            "t_ns": pa.array(range(len(bodies)), pa.int64()),
            "service": pa.array(["svc"] * len(bodies)),
            "severity": pa.array([severity] * len(bodies), pa.string()),
            "body": pa.array(bodies),
        }
    )
    load_lines(con, logs, rules)
    return con.execute("SELECT masked, error FROM lines ORDER BY t_ns").fetchall()


def test_config_keys() -> None:
    assert RULES.bucket_ns == 10 * 10**9
    assert RULES.first_line_max_chars == 512
    assert [token for _, token in RULES.mask_patterns] == [
        "<UUID>",
        "<IP>",
        "<HEX>",
        "<TS>",
        "<DUR>",
        "<NUM>",
    ]
    assert (RULES.drain.sim_th, RULES.drain.depth, RULES.drain.max_children) == (0.4, 4, 100)
    assert (RULES.min_template_count, RULES.max_template_series_per_service) == (3, 200)


@pytest.mark.parametrize(
    ("body", "masked"),
    [
        ("id 123e4567-e89b-12d3-a456-426614174000 done", "id <UUID> done"),  # not <HEX>-<NUM>-...
        ("dial 10.0.3.17:8080 failed", "dial <IP> failed"),
        ("peer 10.0.3.17", "peer <IP>"),
        ("span 4bf92f3577b34da6 closed", "span <HEX> closed"),
        ("at 2026-11-04T10:15:30.123Z start", "at <TS> start"),
        ("at 2026-11-04 10:15:30+05:30 start", "at <TS> start"),
        ("took 512ms", "took <DUR>"),
        ("waited 1.5s for lock", "waited <DUR> for lock"),
        ("listed 12 items for query 7", "listed <NUM> items for query <NUM>"),
        ("ratio 0.25 ok", "ratio <NUM> ok"),
        ("svc1 called cart2 v3", "svc1 called cart2 v3"),  # word-bounded: names stay intact
        ("GET http://catalog:3550/items 21ms", "GET http://catalog:<NUM>/items <DUR>"),
        ("cache stats hits=812 misses=7", "cache stats hits=<NUM> misses=<NUM>"),
    ],
)
def test_masking_in_fixed_order(con: duckdb.DuckDBPyConnection, body: str, masked: str) -> None:
    assert _lines(con, [body])[0][0] == masked


def test_first_non_empty_line_is_mined(con: duckdb.DuckDBPyConnection) -> None:
    bodies = ["\n  \n  boom in order 4  \n    at com.shop.Pay.validate(Pay.java:42)", "", " \n\t", "x" * 600]
    masked = [row[0] for row in _lines(con, bodies)]
    assert masked[0] == "boom in order <NUM>"
    assert masked[1] is None  # an empty body is not mined (02 §6)
    assert masked[2] is None
    assert masked[3] == "x" * 512  # logs.first_line_max_chars


def test_truncation_comes_before_masking(con: duckdb.DuckDBPyConnection) -> None:
    short = LogRules.from_config({**CONFIG, "logs": {**CONFIG["logs"], "first_line_max_chars": 8}})
    assert _lines(con, ["order 123456"], rules=short)[0][0] == "order <NUM>"  # "order 12" was masked


@pytest.mark.parametrize(
    "body",
    [
        "ERROR could not charge",
        "FATAL: out of memory",
        "CardValidationException: invalid token",
        "Traceback (most recent call last):",
        "panic: runtime error",
        "rpc failed: DEADLINE_EXCEEDED",
        "upstream UNAVAILABLE",
        "connection Refused by peer",
        "request timed out",
        "read Timeout after retry",
        "upstream answered status=503",
        "HTTP 500 from cart",
        "all good\n    at com.shop.Pay.validate(Pay.java:42)",  # the lexicon reads the full body
        "goroutine 17 [running]:",
        "Exception in thread main",
    ],
)
def test_lexicon_matches(con: duckdb.DuckDBPyConnection, body: str) -> None:
    assert _lines(con, [body])[0][1] is True


@pytest.mark.parametrize(
    "body",
    [
        "took 512ms",  # a bare 5xx number is not an error
        "GET /healthz 200",
        "status 200 in 503ms",
        "errors=0 warnings=2",  # the lexicon words are case-sensitive
        "timeouts configured",
        "looked at com.shop.Pay",  # a stack frame starts its own line
        "retrying charge for order 5 attempt 2",
    ],
)
def test_lexicon_false_positives(con: duckdb.DuckDBPyConnection, body: str) -> None:
    assert _lines(con, [body])[0][1] is False


@pytest.mark.parametrize(
    ("severity", "error"), [("ERROR", True), ("FATAL", True), ("WARN", False), (None, False)]
)
def test_severity_sets_the_error_level(
    con: duckdb.DuckDBPyConnection, severity: str | None, error: bool
) -> None:
    assert _lines(con, ["charge gave up for order 9"], severity=severity)[0][1] is error
