"""Typed view of `config/causync.yaml` (04-causync §4), validated once per run.

Every threshold is a named config key (AGENTS §5); a malformed value fails as a ConfigError before
any telemetry is read.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from veyltrace_core.errors import ConfigError

__all__ = ["MS", "NS", "AlignConfig", "CausyncConfig", "causync_config"]

NS: Final = 1_000_000_000
MS: Final = 1_000_000


@dataclass(frozen=True)
class AlignConfig:
    """`align.*`: gates of the three offset estimators (04 §3.2, §3.3)."""

    min_pairs: int
    trace_min_offset_ns: int
    min_violation_share: float
    log_inside_share: float
    max_lag_ns: int
    min_corr: float
    min_points: int
    tolerance_step_quantile: float


@dataclass(frozen=True)
class CausyncConfig:
    """`align.*`, `changes.*` and `peer.*`."""

    align: AlignConfig
    change_kinds: frozenset[str]
    tau_ns: int
    min_replicas: int


def _section(cfg: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value: object = cfg.get(key)
    if not isinstance(value, Mapping):
        raise ConfigError(f"causync.{key} must be a mapping")
    return cast("Mapping[str, Any]", value)


def _number(section: Mapping[str, Any], where: str, key: str, *, top: float = math.inf) -> float:
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= top:
        bound = "" if math.isinf(top) else f" and <= {top:g}"
        raise ConfigError(f"causync.{where}.{key} must be a number >= 0{bound}, got {value!r}")
    return float(value)


def _count(section: Mapping[str, Any], where: str, key: str) -> int:
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"causync.{where}.{key} must be an integer >= 1, got {value!r}")
    return value


def causync_config(cfg: Mapping[str, Any]) -> CausyncConfig:
    """Parse and validate the engine's config section."""
    align, changes, peer = _section(cfg, "align"), _section(cfg, "changes"), _section(cfg, "peer")
    kinds: object = changes.get("kinds")
    if isinstance(kinds, str) or not isinstance(kinds, Sequence) or not kinds:
        raise ConfigError(f"causync.changes.kinds must be a non-empty list, got {kinds!r}")
    tau_s = _number(changes, "changes", "tau_s")
    if tau_s == 0:
        raise ConfigError("causync.changes.tau_s must be > 0")
    return CausyncConfig(
        align=AlignConfig(
            min_pairs=_count(align, "align", "min_pairs"),
            trace_min_offset_ns=round(_number(align, "align", "trace_min_offset_ms") * MS),
            min_violation_share=_number(align, "align", "min_violation_share", top=1.0),
            log_inside_share=_number(align, "align", "log_inside_share", top=1.0),
            max_lag_ns=round(_number(align, "align", "max_lag_s") * NS),
            min_corr=_number(align, "align", "min_corr", top=1.0),
            min_points=_count(align, "align", "min_points"),
            tolerance_step_quantile=_number(align, "align", "tolerance_step_quantile", top=1.0),
        ),
        change_kinds=frozenset(str(k) for k in cast("Sequence[object]", kinds)),
        tau_ns=round(tau_s * NS),
        min_replicas=_count(peer, "peer", "min_replicas"),
    )
