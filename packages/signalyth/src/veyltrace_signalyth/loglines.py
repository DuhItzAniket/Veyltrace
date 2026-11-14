"""Log lines (02 §3.5 steps 1, 2 and 7): the text a template is mined from, and the error level.

Each log row becomes one line: the first non-empty line of its body, truncated and masked in the
fixed order of `logs.mask_patterns`, plus whether the row is error-level (severity ERROR/FATAL or
the full body matches `logs.error_lexicon`). All of it is DuckDB SQL over the `lines` table, so
every pattern is RE2 and behaves the same on every machine. Nothing here reads `alert.json`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

import duckdb
import pyarrow as pa

__all__ = ["LOG_COLUMNS", "DrainRules", "LogRules", "load_lines"]

NS: Final = 1_000_000_000
LOG_COLUMNS: Final = ("t_ns", "service", "severity", "body")
#: Severities that make a line error-level whatever its text (02 §3.5 step 7; 03 §2.3).
ERROR_SEVERITIES: Final = ("ERROR", "FATAL")
#: From the first non-whitespace character of the body to the end of that line.
_FIRST_LINE: Final = r"\S[^\r\n]*"


@dataclass(frozen=True)
class DrainRules:
    """`logs.drain.*` (02 §4): fixed a priori, never tuned per dataset."""

    sim_th: float
    depth: int
    max_children: int


@dataclass(frozen=True)
class LogRules:
    """`logs.*` and `buckets.logs_s` (02 §4). `mask_patterns` are (RE2 pattern, token) pairs."""

    bucket_ns: int
    first_line_max_chars: int
    mask_patterns: tuple[tuple[str, str], ...]
    error_lexicon: tuple[str, ...]
    drain: DrainRules
    min_template_count: int
    max_template_series_per_service: int

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> LogRules:
        section = cast("Mapping[str, Any]", cfg["logs"])
        drain = cast("Mapping[str, Any]", section["drain"])
        masks = cast("Sequence[Mapping[str, Any]]", section["mask_patterns"])
        return cls(
            bucket_ns=int(cast("Mapping[str, Any]", cfg["buckets"])["logs_s"]) * NS,
            first_line_max_chars=int(section["first_line_max_chars"]),
            mask_patterns=tuple((str(m["pattern"]), str(m["token"])) for m in masks),
            error_lexicon=tuple(str(p) for p in section["error_lexicon"]),
            drain=DrainRules(float(drain["sim_th"]), int(drain["depth"]), int(drain["max_children"])),
            min_template_count=int(section["min_template_count"]),
            max_template_series_per_service=int(section["max_template_series_per_service"]),
        )


def _lit(text: str) -> str:
    """`text` as a SQL string literal (patterns come from config, never from telemetry)."""
    return "'" + text.replace("'", "''") + "'"


def _masked_sql(rules: LogRules) -> str:
    """SQL for the masked first line of `body`; NULL when the body has no non-empty line."""
    line = f"regexp_replace(regexp_extract(body, {_lit(_FIRST_LINE)}), {_lit(r'\s+$')}, '')"
    expr = f"left({line}, {rules.first_line_max_chars})"
    for pattern, token in rules.mask_patterns:
        expr = f"regexp_replace({expr}, {_lit(pattern)}, {_lit(token)}, 'g')"
    return f"nullif({expr}, '')"


def _error_sql(rules: LogRules) -> str:
    """SQL for the error level of a row: its severity, or the lexicon on the full body."""
    severities = ", ".join(_lit(s) for s in ERROR_SEVERITIES)
    tests = [f"coalesce(severity IN ({severities}), false)"]
    tests += [f"regexp_matches(body, {_lit(p)})" for p in rules.error_lexicon]
    return " OR ".join(tests)


def load_lines(con: duckdb.DuckDBPyConnection, logs: pa.Table, rules: LogRules) -> None:
    """Create the table `lines(service, t_ns, masked, error)`, one row per row of `logs` (columns
    LOG_COLUMNS). `masked` is NULL for an empty body: such a row is not mined but still counts in
    `log_rate` (02 §6)."""
    con.register("logs_in", logs)
    con.execute(
        "CREATE OR REPLACE TEMP TABLE lines AS "  # config patterns as literals, see _lit
        f"SELECT service, t_ns, {_masked_sql(rules)} AS masked, ({_error_sql(rules)}) AS error FROM logs_in"
    )
    con.unregister("logs_in")
