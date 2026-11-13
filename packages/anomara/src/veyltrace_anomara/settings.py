"""Typed view of `config/anomara.yaml` (03-anomara §4), validated once per run.

Why typed: every detector threshold is a named config key (AGENTS §5), and a malformed value
should fail as a ConfigError before any series is scored, not as a TypeError deep in numpy.
Sections arrive with the code that reads them (O-04c: grid; O-04d: robust_z; O-04e: nsigma, silence).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from veyltrace_core.errors import ConfigError

__all__ = [
    "ANY_UNIT",
    "NS_PER_S",
    "AnomaraConfig",
    "GridConfig",
    "NSigmaConfig",
    "RobustZConfig",
    "SilenceConfig",
    "anomara_config",
]

NS_PER_S = 1_000_000_000
#: `robust_z.epsilon.<family>` key matching any unit not listed for that family (03-anomara §3.2).
ANY_UNIT = "*"
#: Family whose ε applies to (family, unit) pairs the table does not list (03-anomara §3.2).
FALLBACK_FAMILY = "other"


def _mapping(section: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value: object = section.get(key)
    if not isinstance(value, Mapping):
        msg = f"{where}.{key} must be a mapping"
        raise ConfigError(msg)
    return cast("Mapping[str, Any]", value)


def _number(section: Mapping[str, Any], key: str, where: str, *, positive: bool = False) -> float:
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        msg = f"{where}.{key} must be a finite number, got {value!r}"
        raise ConfigError(msg)
    if value < 0 or (positive and value == 0):
        msg = f"{where}.{key} must be {'> 0' if positive else '>= 0'}, got {value!r}"
        raise ConfigError(msg)
    return float(value)


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
class RobustZConfig:
    """`robust_z.*` (03-anomara §3.2)."""

    mad_factor: float
    iqr_divisor: float
    eta: float
    epsilon: Mapping[str, Mapping[str, float]]
    persist_steps: int
    threshold: float
    min_baseline_steps: int

    def epsilon_for(self, family: str, unit: str | None) -> float:
        """ε(family, unit): the listed unit, else the family's `*`, else the `other` family's `*`."""
        table = self.epsilon.get(family, {})
        if unit is not None and unit in table:
            return table[unit]
        return table.get(ANY_UNIT, self.epsilon[FALLBACK_FAMILY][ANY_UNIT])


@dataclass(frozen=True)
class NSigmaConfig:
    """`nsigma.*` (03-anomara §3.3)."""

    threshold: float


@dataclass(frozen=True)
class SilenceConfig:
    """`silence.*` (03-anomara §3.5); `min_gap_ns` is `min_gap_s` in ns."""

    min_gap_ns: int
    min_steps: int
    zero_signals: frozenset[str]
    max_baseline_zero_share: float
    min_baseline_coverage: float
    service_metric_share: float


@dataclass(frozen=True)
class AnomaraConfig:
    """The validated Anomara section."""

    grid: GridConfig
    robust_z: RobustZConfig
    nsigma: NSigmaConfig
    silence: SilenceConfig


def _epsilon(section: Mapping[str, Any]) -> Mapping[str, Mapping[str, float]]:
    raw = _mapping(section, "epsilon", "anomara.robust_z")
    table: dict[str, dict[str, float]] = {}
    for family in sorted(raw):
        units = _mapping(raw, family, "anomara.robust_z.epsilon")
        where = f"anomara.robust_z.epsilon.{family}"
        table[family] = {unit: _number(units, unit, where, positive=True) for unit in sorted(units)}
    if ANY_UNIT not in table.get(FALLBACK_FAMILY, {}):
        msg = f"anomara.robust_z.epsilon.{FALLBACK_FAMILY} must set {ANY_UNIT!r} (the last fallback)"
        raise ConfigError(msg)
    return table


def _robust_z(section: Mapping[str, Any]) -> RobustZConfig:
    rz = _mapping(section, "robust_z", "anomara")
    where = "anomara.robust_z"
    return RobustZConfig(
        mad_factor=_number(rz, "mad_factor", where, positive=True),
        iqr_divisor=_number(rz, "iqr_divisor", where, positive=True),
        eta=_number(rz, "eta", where),
        epsilon=_epsilon(rz),
        persist_steps=_count(rz, "persist_steps", where),
        threshold=_number(rz, "threshold", where, positive=True),
        min_baseline_steps=_count(rz, "min_baseline_steps", where),
    )


def _share(section: Mapping[str, Any], key: str, where: str) -> float:
    value = _number(section, key, where)
    if value > 1.0:
        msg = f"{where}.{key} must be a share in [0, 1], got {value!r}"
        raise ConfigError(msg)
    return value


def _silence(section: Mapping[str, Any]) -> SilenceConfig:
    sc = _mapping(section, "silence", "anomara")
    where = "anomara.silence"
    signals: object = sc.get("zero_signals")
    if isinstance(signals, str) or not isinstance(signals, list | tuple):
        msg = f"{where}.zero_signals must be a list of signal names, got {signals!r}"
        raise ConfigError(msg)
    names = cast("list[object] | tuple[object, ...]", signals)
    if not all(isinstance(n, str) and n for n in names):
        msg = f"{where}.zero_signals must hold non-empty strings, got {signals!r}"
        raise ConfigError(msg)
    return SilenceConfig(
        min_gap_ns=_count(sc, "min_gap_s", where) * NS_PER_S,
        min_steps=_count(sc, "min_steps", where),
        zero_signals=frozenset(cast("list[str]", list(names))),
        max_baseline_zero_share=_share(sc, "max_baseline_zero_share", where),
        min_baseline_coverage=_share(sc, "min_baseline_coverage", where),
        service_metric_share=_share(sc, "service_metric_share", where),
    )


def anomara_config(section: Mapping[str, Any]) -> AnomaraConfig:
    """Validate the Anomara config section (`ctx.config`, or the EngineConfig core passes)."""
    grid = _mapping(section, "grid", "anomara")
    ns = _mapping(section, "nsigma", "anomara")
    return AnomaraConfig(
        grid=GridConfig(bucket_ns=_count(grid, "bucket_s", "anomara.grid") * NS_PER_S),
        robust_z=_robust_z(section),
        nsigma=NSigmaConfig(threshold=_number(ns, "threshold", "anomara.nsigma", positive=True)),
        silence=_silence(section),
    )
