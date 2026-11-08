"""duck.connect: per-engine threads/memory, run-dir spill directory, extensions never fetched."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from veyltrace_core.duck import DEFAULT_MEMORY_LIMIT, DEFAULT_THREADS, TEMP_DIRNAME, connect, settings
from veyltrace_core.errors import ConfigError

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _setting(con: Any, name: str) -> Any:
    row = con.execute("SELECT current_setting(?)", [name]).fetchone()
    assert row is not None
    return row[0]


def test_defaults_without_a_duckdb_section(tmp_path: Path) -> None:
    cfg = settings({}, tmp_path)
    assert cfg["threads"] == DEFAULT_THREADS == 1
    assert cfg["memory_limit"] == DEFAULT_MEMORY_LIMIT == "2GB"
    assert cfg["temp_directory"] == (tmp_path.absolute() / TEMP_DIRNAME).as_posix()
    assert cfg["autoinstall_known_extensions"] is False
    assert cfg["autoload_known_extensions"] is False


def test_connection_applies_settings(tmp_path: Path) -> None:
    section = MappingProxyType({"duckdb": MappingProxyType({"threads": 2, "memory_limit": "1.5GB"})})
    with connect(section, tmp_path) as con:
        assert _setting(con, "threads") == 2
        assert _setting(con, "temp_directory") == (tmp_path.absolute() / TEMP_DIRNAME).as_posix()
        assert _setting(con, "autoinstall_known_extensions") is False
        assert _setting(con, "autoload_known_extensions") is False
        assert str(_setting(con, "memory_limit")).endswith("GiB")  # 1.5 GB shown as 1.3 GiB
        assert con.execute("SELECT 40 + 2").fetchone() == (42,)
    assert not (tmp_path / TEMP_DIRNAME).exists()  # created by DuckDB only when it spills


def test_time_zone_is_utc_whatever_the_host(tmp_path: Path) -> None:
    """TIMESTAMPTZ functions must give the same values on an IST laptop and on UTC CI."""
    with connect({}, tmp_path) as con:
        assert _setting(con, "TimeZone") == "UTC"
        assert _setting(con, "Calendar") == "gregorian"
        row = con.execute("SELECT strftime(to_timestamp(1767225600), '%H:%M')").fetchone()
        assert row == ("00:00",)
        trunc = "SELECT epoch_ns(date_trunc('hour', make_timestamptz(1767225600000000 + 1320000000)))"
        assert con.execute(trunc).fetchone() == (1767225600000000000,)


def test_in_memory_database(tmp_path: Path) -> None:
    with connect({}, tmp_path) as con:
        row = con.execute("SELECT current_database()").fetchone()
    assert row is not None
    assert row[0] == "memory"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "section",
    [
        {"duckdb": {"threads": 0}},
        {"duckdb": {"threads": True}},
        {"duckdb": {"threads": "1"}},
        {"duckdb": {"memory_limit": "lots"}},
        {"duckdb": {"memory_limit": 2}},
        {"duckdb": {"theads": 1}},
        {"duckdb": [1]},
    ],
    ids=repr,
)
def test_invalid_settings_are_config_errors(tmp_path: Path, section: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        connect(section, tmp_path)


def test_repo_engine_configs_are_accepted(tmp_path: Path) -> None:
    seen: list[str] = []
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        section = yaml.safe_load(path.read_bytes()) or {}
        if "duckdb" not in section:
            continue
        seen.append(path.stem)
        cfg = settings(section, tmp_path)
        assert cfg["threads"] == section["duckdb"]["threads"]
        assert cfg["memory_limit"] == section["duckdb"]["memory_limit"]
    # The six deterministic engines that may use DuckDB (R-02 config skeleton).
    assert seen == ["anomara", "causalith", "causync", "faultloom", "infralume", "signalyth"]
