"""Typed view of `config/anomara.yaml` (03-anomara §4), validated once per run.

Why typed: every detector threshold is a named config key (AGENTS §5), and a malformed value
should fail as a ConfigError before any series is scored, not as a TypeError deep in numpy.
Sections arrive with the code that reads them (O-04c: grid).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from veyltrace_core.errors import ConfigError

__all__ = ["NS_PER_S", "AnomaraConfig", "GridConfig", "anomara_config"]

NS_PER_S = 1_000_000_000


def _mapping(section: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value: object = section.get(key)
    if not isinstance(value, Mapping):
        msg = f"{where}.{key} must be a mapping"
        raise ConfigError(msg)
    return cast("Mapping[str, Any]", value)


def _count(section: Mapping[str, Any], key: str, where: str) -> int:
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{where}.{key} must be an integer >= 1, got {value!r}"
        raise ConfigError(msg)
    return value


@dataclass(frozen=True)
class GridConfig:
    """`grid.*`: the step of bucketed (traces, logs) series and the fallback step."""

    bucket_ns: int


@dataclass(frozen=True)
class AnomaraConfig:
    """The validated Anomara section."""

    grid: GridConfig


def anomara_config(section: Mapping[str, Any]) -> AnomaraConfig:
    """Validate the Anomara config section (`ctx.config`, or the EngineConfig core passes)."""
    grid = _mapping(section, "grid", "anomara")
    return AnomaraConfig(grid=GridConfig(bucket_ns=_count(grid, "bucket_s", "anomara.grid") * NS_PER_S))
