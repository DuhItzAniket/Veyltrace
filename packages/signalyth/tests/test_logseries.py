"""Template counts and log series (02 §3.5 steps 6, 7 and the series table)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow as pa

from veyltrace_core import duck
from veyltrace_core.config import resolve_config
from veyltrace_signalyth.loglines import LogRules, load_lines
from veyltrace_signalyth.logseries import load_templates, log_series, template_rows
from veyltrace_signalyth.templates import distinct_messages, mine_templates, template_id

CONFIG = resolve_config({}, ai_mode="off").engine("signalyth")
RULES = LogRules.from_config(CONFIG)
S = 10**9
WINDOWS = {"baseline": (0, 20 * S), "incident": (20 * S, 40 * S)}
#: (second, service, severity, body); data range 0 s … 39 s → buckets 0, 10, 20, 30 s.
LINES: list[tuple[int, str, str, str]] = [
    (1, "pay", "INFO", "charged order 1"),
    (2, "pay", "INFO", "charged order 2"),
    (12, "pay", "INFO", "charged order 3"),
    (20, "pay", "INFO", "charged order 4"),  # at the incident start: half-open windows
    (21, "pay", "ERROR", "charge failed for order 5"),
    (22, "pay", "INFO", "charge failed for order 6\n    at com.shop.Pay.run(Pay.java:7)"),
    (23, "pay", "WARN", "charge failed for order 7"),
    (31, "pay", "INFO", ""),  # not mined, still a line
    (5, "cart", "INFO", "cart 9 holds 2 items"),
]


def _run(
    tmp_path: Path, rules: LogRules = RULES, windows: dict[str, tuple[int, int]] = WINDOWS
) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
    columns = list(zip(*LINES, strict=True))
    logs = pa.table(
        {
            "t_ns": pa.array([t * S for t in columns[0]], pa.int64()),
            "service": pa.array(columns[1]),
            "severity": pa.array(columns[2]),
            "body": pa.array(columns[3]),
        }
    )
    with duck.connect(CONFIG, tmp_path) as con:
        load_lines(con, logs, rules)
        mined, _ = mine_templates(distinct_messages(con), rules.drain)
        load_templates(con, mined)
        return template_rows(con, windows), log_series(con, rules, 0, 39 * S)


def _values(series: dict[str, list[Any]], service: str, signal: str) -> list[tuple[int, float]]:
    rows = zip(series["service"], series["signal"], series["t_ns"], series["value"], strict=True)
    return [(t // S, v) for svc, sig, t, v in rows if (svc, sig) == (service, signal)]


def test_template_counts_error_level_and_first_seen(tmp_path: Path) -> None:
    templates, _ = _run(tmp_path)
    columns = ("service", "template", "count_baseline", "count_incident", "error_level", "first_seen_ns")
    rows = {(s, t): rest for s, t, *rest in zip(*(templates[c] for c in columns), strict=True)}
    assert rows == {
        ("cart", "cart <NUM> holds <NUM> items"): [1, 0, False, 5 * S],
        ("pay", "charged order <NUM>"): [3, 1, False, 1 * S],
        ("pay", "charge failed for order <NUM>"): [0, 3, True, 21 * S],  # one ERROR line is enough
    }
    ids = dict(zip(templates["template"], templates["template_id"], strict=True))
    assert ids["charged order <NUM>"] == template_id("pay", "charged order <NUM>")
    assert templates["service"] == sorted(templates["service"])


def test_rates_are_zero_filled_on_the_whole_grid(tmp_path: Path) -> None:
    _, series = _run(tmp_path)
    assert _values(series, "pay", "log_rate") == [(0, 0.2), (10, 0.1), (20, 0.4), (30, 0.1)]
    # severity ERROR, a stack frame in the body; the WARN line is not error-level
    assert _values(series, "pay", "log_error_rate") == [(0, 0.0), (10, 0.0), (20, 0.2), (30, 0.0)]
    assert _values(series, "cart", "log_rate") == [(0, 0.1), (10, 0.0), (20, 0.0), (30, 0.0)]
    meta = set(zip(series["signal"], series["family"], series["klass"], series["unit"], strict=True))
    assert ("log_rate", "logs", "context", "1/s") in meta
    assert ("log_error_rate", "logs", "internal", "1/s") in meta


def test_template_series_need_min_count_and_respect_the_cap(tmp_path: Path) -> None:
    _, series = _run(tmp_path)
    charged, failed = (
        template_id("pay", t) for t in ("charged order <NUM>", "charge failed for order <NUM>")
    )
    assert {s for s in series["signal"] if s.startswith("tmpl:")} == {f"tmpl:{charged}", f"tmpl:{failed}"}
    assert _values(series, "pay", f"tmpl:{charged}") == [(0, 2.0), (10, 1.0), (20, 1.0), (30, 0.0)]
    columns = zip(*(series[c] for c in ("signal", "family", "klass", "unit")), strict=True)
    meta = {(f, k, u) for s, f, k, u in columns if s.startswith("tmpl:")}
    assert meta == {("logs", "internal", "count")}
    # cart's only template has 1 line < logs.min_template_count: listed in `templates`, no series
    _, capped = _run(tmp_path, replace(RULES, max_template_series_per_service=1))
    kept = {s for s in capped["signal"] if s.startswith("tmpl:")}
    assert kept == {f"tmpl:{charged}"}  # 4 lines beat 3


def test_windows_move_only_the_counts(tmp_path: Path) -> None:
    templates, series = _run(tmp_path)
    moved, moved_series = _run(tmp_path, windows={**WINDOWS, "incident": (30 * S, 40 * S)})
    assert moved_series == series
    for column in ("service", "template_id", "template", "error_level", "first_seen_ns", "count_baseline"):
        assert moved[column] == templates[column]
    assert moved["count_incident"] != templates["count_incident"]
