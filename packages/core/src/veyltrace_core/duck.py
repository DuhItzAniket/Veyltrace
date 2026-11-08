"""The one way engine code opens DuckDB: an in-memory connection with project-safe settings.

DuckDB's defaults are wrong for Veyltrace (M0 lead decision 2026-11-06, reversing core_api_spec
D-25(b); critic gap "DuckDB configuration"):

- threads defaults to every core, and parallel aggregation can change float summation order;
- memory_limit defaults to 80 % of RAM, against a 3 GB per-case budget (02 §9);
- an in-memory database spills to ".tmp" in the current directory, i.e. into the repo, which
  marks the work tree dirty and changes run_id;
- extension autoinstall/autoload are on: a latent network path inside engines 1-7;
- TimeZone and Calendar come from the OS (ICU, built into the wheel), so any TIMESTAMPTZ
  expression (to_timestamp, date_trunc, time_bucket, strftime) gives different values on an IST
  laptop than on UTC CI.

So connect() reads `<engine>.duckdb.threads` and `<engine>.duckdb.memory_limit` from the
engine's own config section, spills to `<run_dir>/.duck-tmp` (never a run output), and turns
extension autoinstall and autoload off, then pins TimeZone to UTC and Calendar to gregorian
(`SESSION_SETTINGS`; they are ICU options, which DuckDB only accepts by SET after the connection
exists, not in the connect config). The isolation test bans `duckdb.connect` in engine code
outside this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import duckdb

from veyltrace_core.errors import ConfigError

__all__ = [
    "DEFAULT_MEMORY_LIMIT",
    "DEFAULT_THREADS",
    "SECTION",
    "SESSION_SETTINGS",
    "TEMP_DIRNAME",
    "DuckSettings",
    "connect",
    "settings",
]

#: Config subsection connect() reads: `<engine>.duckdb.*`.
SECTION = "duckdb"
#: Defaults when the engine's YAML sets no value (M0 lead decision 2026-11-06): one thread for
#: deterministic aggregates; 2 GB keeps one engine inside the 3 GB per-case budget (02 §9).
DEFAULT_THREADS = 1
DEFAULT_MEMORY_LIMIT = "2GB"
#: Spill directory inside the run dir; excluded from run_manifest.outputs and git-ignored.
TEMP_DIRNAME = ".duck-tmp"
#: ICU session settings applied right after connecting: every artefact time is UTC epoch ns
#: (03 §1), so DuckDB's local-time functions must not depend on the host time zone.
SESSION_SETTINGS: tuple[tuple[str, str], ...] = (("TimeZone", "UTC"), ("Calendar", "gregorian"))

_KEYS = frozenset({"threads", "memory_limit"})
# DuckDB size syntax: a number and a unit, e.g. "1GB", "1.5GB", "512MiB".
_MEMORY_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?\s*(?:B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)")


type DuckSettings = dict[str, str | bool | int | float | list[str]]


def settings(cfg: Mapping[str, Any], run_dir: Path) -> DuckSettings:
    """Return the DuckDB config dict connect() uses for an engine section and run directory.

    Raises ConfigError for unknown `duckdb.*` keys or invalid values, so a misspelt key is never
    silently ignored.
    """
    raw: object = cfg.get(SECTION, {})
    if not isinstance(raw, Mapping):
        msg = f"{SECTION} must be a mapping, got {type(raw).__name__}"
        raise ConfigError(msg)
    section = cast(Mapping[object, object], raw)
    unknown = sorted(str(k) for k in section if k not in _KEYS)
    if unknown:
        msg = f"unknown {SECTION} keys {unknown}; allowed: {sorted(_KEYS)}"
        raise ConfigError(msg)
    threads = section.get("threads", DEFAULT_THREADS)
    memory_limit = section.get("memory_limit", DEFAULT_MEMORY_LIMIT)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        msg = f"{SECTION}.threads must be an int >= 1, got {threads!r}"
        raise ConfigError(msg)
    if not isinstance(memory_limit, str) or _MEMORY_RE.fullmatch(memory_limit) is None:
        msg = f"{SECTION}.memory_limit must be a size such as '2GB', got {memory_limit!r}"
        raise ConfigError(msg)
    return {
        "threads": threads,
        "memory_limit": memory_limit,
        "temp_directory": (Path(run_dir).absolute() / TEMP_DIRNAME).as_posix(),
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    }


def connect(cfg: Mapping[str, Any], run_dir: Path) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB connection configured for one engine and run (see module doc).

    `cfg` is the engine's own config section (ctx.config, an EngineConfig mapping). The caller
    closes the connection (use it as a context manager).
    """
    config = settings(cfg, run_dir)
    try:
        con = duckdb.connect(database=":memory:", config=config)
    except duckdb.Error as exc:
        msg = f"DuckDB rejected the {SECTION} settings {config}: {exc}"
        raise ConfigError(msg) from exc
    try:
        for name, value in SESSION_SETTINGS:
            con.execute(f"SET {name} = '{value}'")  # constants above, never user input
    except duckdb.Error as exc:
        con.close()
        msg = f"DuckDB rejected the session settings {SESSION_SETTINGS}: {exc}"
        raise ConfigError(msg) from exc
    return con
