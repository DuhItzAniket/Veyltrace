"""Causentra configuration: the 09 §4 keys of the v1 decision, validated once per run.

Values are fixed a priori in `config/causentra.yaml` (02 §6.9); predicate weights are only read.
A bad or missing value is a ConfigError naming the key."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from veyltrace_contracts.predicates import PREDICATES
from veyltrace_core.errors import ConfigError

ENGINE: Final = "causentra"
#: Trial ids T1…T10 (03 §10 `trials[].id`).
_TRIAL_ID: Final = re.compile(r"^T([1-9]|10)$")
#: factors.* keys in Factors field order (09 §4).
FACTOR_KEYS: Final = (
    "pass",
    "untestable_mandatory",
    "fail_mandatory",
    "untestable_supporting",
    "fail_supporting",
)
#: The NO_FAULT statistic is defined on robust_z atoms only (09 §3.8: score_norm = log1p(score)).
NO_FAULT_DETECTORS: Final = ("robust_z",)


@dataclass(frozen=True)
class Factors:
    """Trial factors in V (09 §3.5): pass; mandatory untestable / failed; supporting untestable / failed."""

    passed: float
    untestable_mandatory: float
    fail_mandatory: float
    untestable_supporting: float
    fail_supporting: float


@dataclass(frozen=True)
class CausentraConfig:
    """The effective causentra keys of R-10 (09 §4) and core's k_anom."""

    alpha: float
    factors: Factors
    mandatory: tuple[str, ...]
    disabled: tuple[str, ...]
    clip_low: float
    clip_high: float
    weights: tuple[tuple[str, float], ...]
    proposals_max: int
    c_high: float
    c_med: float
    likely_max_set: int
    t2_min_fraction: float
    t3_min_path_fraction: float
    uncalibrated_q_hat: float
    default_tau: float
    asks_max: int
    k_anom: float

    def weight(self, predicate: str) -> float:
        """`predicates.<name>.weight` (03 §7 default weights)."""
        return dict(self.weights)[predicate]


def _get(section: Mapping[str, Any], name: str, dotted: str) -> Any:
    node: Any = section
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            msg = f"{name}.{dotted}: no such config key (add it to config/{name}.yaml)"
            raise ConfigError(msg)
        node = cast(Mapping[str, Any], node)[part]
    return node


def _number(value: object, key: str, low: float = -math.inf, high: float = math.inf) -> float:
    ok = not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)
    if not ok or not low <= float(cast(float, value)) <= high:
        msg = f"{key} must be a finite number in [{low}, {high}], got {value!r}"
        raise ConfigError(msg)
    return float(cast(float, value))


def _int(value: object, key: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        msg = f"{key} must be an integer >= {minimum}, got {value!r}"
        raise ConfigError(msg)
    return value


def _trials(value: object, key: str) -> tuple[str, ...]:
    items = list(cast(Sequence[object], value)) if isinstance(value, list | tuple) else None
    ids = [t for t in items or [] if isinstance(t, str) and _TRIAL_ID.match(t)]
    if items is None or len(ids) != len(items) or len(set(ids)) != len(ids):
        msg = f"{key} must be a list of distinct trial ids T1…T10, got {value!r}"
        raise ConfigError(msg)
    return tuple(sorted(ids, key=lambda t: int(t[1:])))


def config_from(cfg: Mapping[str, Any], core: Mapping[str, Any]) -> CausentraConfig:
    """Validate the causentra section `cfg` (ctx.config) and core's `thresholds.anomaly_z`."""

    def get(dotted: str) -> Any:
        return _get(cfg, ENGINE, dotted)

    def num(dotted: str, low: float = -math.inf, high: float = math.inf) -> float:
        return _number(get(dotted), f"{ENGINE}.{dotted}", low, high)

    def factor(name: str) -> float:
        return num(f"factors.{name}", 0.0, 1.0)

    detector = get("no_fault.detector")
    if detector not in NO_FAULT_DETECTORS:
        msg = f"causentra.no_fault.detector must be one of {NO_FAULT_DETECTORS} (09 §3.8), got {detector!r}"
        raise ConfigError(msg)
    weights = tuple(
        (p.name, num(f"predicates.{p.name}.weight", 0.0)) for p in sorted(PREDICATES, key=lambda p: p.name)
    )
    return CausentraConfig(
        alpha=num("alpha", 0.0, 1.0),
        factors=Factors(*(factor(n) for n in FACTOR_KEYS)),
        mandatory=_trials(get("mandatory"), "causentra.mandatory"),
        disabled=_trials(get("trials.disabled"), "causentra.trials.disabled"),
        clip_low=num("claims.clip_low", -1.0, 0.0),
        clip_high=num("claims.clip_high", 0.0),
        weights=weights,
        proposals_max=_int(get("proposals.max"), "causentra.proposals.max", 0),
        c_high=num("status.c_high", 0.0, 1.0),
        c_med=num("status.c_med", 0.0, 1.0),
        likely_max_set=_int(get("status.likely_max_set"), "causentra.status.likely_max_set", 1),
        t2_min_fraction=num("trials.T2.min_fraction", 0.0, 1.0),
        t3_min_path_fraction=num("trials.T3.min_path_anomalous_fraction", 0.0, 1.0),
        uncalibrated_q_hat=num("calibration.uncalibrated_q_hat", 0.0),
        default_tau=num("no_fault.default_tau", 0.0),
        asks_max=_int(get("asks.max"), "causentra.asks.max", 0),
        k_anom=_number(_get(core, "core", "thresholds.anomaly_z"), "core.thresholds.anomaly_z"),
    )
