"""Typed view of `config/anomara.yaml` (03-anomara §4), validated once per run.

Why typed: every detector threshold is a named config key (AGENTS §5), and a malformed value
should fail as a ConfigError before any series is scored, not as a TypeError deep in numpy.
Sections arrive with the code that reads them (O-04c: grid; O-04d: robust_z; O-04e: nsigma,
silence; O-04f: bocpd; O-04g: onset, t_onset;
detect_alert: slo).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from veyltrace_core.errors import ConfigError

__all__ = [
    "ANY_UNIT",
    "NS_PER_S",
    "AnomaraConfig",
    "BocpdConfig",
    "GridConfig",
    "NSigmaConfig",
    "OnsetConfig",
    "RobustZConfig",
    "SilenceConfig",
    "SloConfig",
    "anomara_config",
]

NS_PER_S = 1_000_000_000
NS_PER_MS = 1_000_000
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
class BocpdConfig:
    """`bocpd.*` (03-anomara §3.4); `lam` is `bocpd.lambda` (a Python keyword), the prior is flat."""

    lam: float
    mu0: float
    kappa0: float
    alpha0: float
    beta0: float
    r_max: int
    short_run: int
    threshold: float


@dataclass(frozen=True)
class OnsetConfig:
    """`onset.bocpd_max_lead_s` and `t_onset.clamp_s` (03-anomara §3.6–3.7), in ns."""

    bocpd_max_lead_ns: int
    clamp_ns: tuple[int, int]


@dataclass(frozen=True)
class SloConfig:
    """`slo.*` (03-anomara §3.8), times in ns."""

    bucket_ns: int
    min_spans: int
    infer_client_spans: bool
    skew_tolerance_ns: int
    window_ns: int
    gap_ns: int
    k: float
    persist_steps: int
    min_baseline_points: int
    latency_pattern: re.Pattern[str]
    error_pattern: re.Pattern[str]
    counter_patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class AnomaraConfig:
    """The validated Anomara section."""

    grid: GridConfig
    robust_z: RobustZConfig
    nsigma: NSigmaConfig
    silence: SilenceConfig
    bocpd: BocpdConfig
    onset: OnsetConfig
    slo: SloConfig


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


def _bocpd(section: Mapping[str, Any]) -> BocpdConfig:
    bc = _mapping(section, "bocpd", "anomara")
    prior = _mapping(bc, "prior", "anomara.bocpd")
    where, at = "anomara.bocpd", "anomara.bocpd.prior"
    lam = _number(bc, "lambda", where, positive=True)
    if lam <= 1.0:
        msg = f"{where}.lambda must be > 1 (the hazard 1/lambda is a probability below 1), got {lam!r}"
        raise ConfigError(msg)
    mu0: object = prior.get("mu0")
    if isinstance(mu0, bool) or not isinstance(mu0, int | float) or not math.isfinite(mu0):
        msg = f"{at}.mu0 must be a finite number, got {mu0!r}"
        raise ConfigError(msg)
    short: object = bc.get("short_run")
    if isinstance(short, bool) or not isinstance(short, int) or short < 0:
        msg = f"{where}.short_run must be an integer >= 0, got {short!r}"
        raise ConfigError(msg)
    threshold = _share(bc, "threshold", where)
    if threshold == 0.0:
        msg = f"{where}.threshold must be in (0, 1], got {threshold!r}"
        raise ConfigError(msg)
    return BocpdConfig(
        lam=lam,
        mu0=float(mu0),
        kappa0=_number(prior, "kappa0", at, positive=True),
        alpha0=_number(prior, "alpha0", at, positive=True),
        beta0=_number(prior, "beta0", at, positive=True),
        r_max=_count(bc, "r_max", where),
        short_run=short,
        threshold=threshold,
    )


def _onset(section: Mapping[str, Any]) -> OnsetConfig:
    lead = _count(_mapping(section, "onset", "anomara"), "bocpd_max_lead_s", "anomara.onset")
    clamp: object = _mapping(section, "t_onset", "anomara").get("clamp_s")
    pair: list[object] = list(cast("list[object]", clamp)) if isinstance(clamp, list | tuple) else []
    if len(pair) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) for v in pair):
        msg = f"anomara.t_onset.clamp_s must be a [low_s, high_s] pair of integers, got {clamp!r}"
        raise ConfigError(msg)
    low, high = cast("int", pair[0]), cast("int", pair[1])
    if not low <= 0 <= high:
        msg = f"anomara.t_onset.clamp_s must satisfy low <= 0 <= high, got {clamp!r}"
        raise ConfigError(msg)
    return OnsetConfig(bocpd_max_lead_ns=lead * NS_PER_S, clamp_ns=(low * NS_PER_S, high * NS_PER_S))


def _names(value: object, where: str) -> list[object]:
    if isinstance(value, str) or not isinstance(value, list | tuple):
        msg = f"{where}.counter_name_patterns must be a list of regular expressions, got {value!r}"
        raise ConfigError(msg)
    return list(cast("list[object]", value))


def _regex(value: object, where: str) -> re.Pattern[str]:
    """A case-insensitive pattern, as Signalyth's metric-name rules (02-signalyth §3.2)."""
    if not isinstance(value, str) or not value:
        msg = f"{where} must be a non-empty regular expression, got {value!r}"
        raise ConfigError(msg)
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as exc:
        msg = f"{where}: invalid regular expression {value!r}: {exc}"
        raise ConfigError(msg) from exc


def _slo(section: Mapping[str, Any]) -> SloConfig:
    sc = _mapping(section, "slo", "anomara")
    where = "anomara.slo"
    infer: object = sc.get("infer_client_spans")
    if not isinstance(infer, bool):
        msg = f"{where}.infer_client_spans must be true or false, got {infer!r}"
        raise ConfigError(msg)
    skew_ms = _number(sc, "skew_tolerance_ms", where, positive=False)
    return SloConfig(
        bucket_ns=_count(sc, "bucket_s", where) * NS_PER_S,
        min_spans=_count(sc, "min_spans", where),
        infer_client_spans=infer,
        skew_tolerance_ns=round(skew_ms * NS_PER_MS),
        window_ns=_count(sc, "window_s", where) * NS_PER_S,
        gap_ns=_count(sc, "gap_s", where) * NS_PER_S,
        k=_number(sc, "k", where, positive=True),
        persist_steps=_count(sc, "persist_steps", where),
        min_baseline_points=_count(sc, "min_baseline_points", where),
        latency_pattern=_regex(sc.get("latency_metric_pattern"), f"{where}.latency_metric_pattern"),
        error_pattern=_regex(sc.get("error_metric_pattern"), f"{where}.error_metric_pattern"),
        counter_patterns=tuple(
            _regex(p, f"{where}.counter_name_patterns")
            for p in _names(sc.get("counter_name_patterns"), where)
        ),
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
        bocpd=_bocpd(section),
        onset=_onset(section),
        slo=_slo(section),
    )
