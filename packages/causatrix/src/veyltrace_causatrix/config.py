"""Causatrix configuration: every key of 07 §4 plus the core values Causatrix shares (07 §2.1).

Why one frozen value: `rank()` and `classify()` are pure functions of (evidence, graph, sources,
config), and Causentra calls them with the same object for trial T9, so the section is read and
validated once. Every key is declared in `config/causatrix.yaml` with its source; a bad value is a
ConfigError naming the key, so a mistyped ablation override fails before any ranking.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast, get_args

from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError

__all__ = [
    "ENGINE",
    "FAMILIES",
    "FUSION_METHODS",
    "PRISM_COMBINE",
    "CausatrixConfig",
    "config_from",
]

ENGINE: Final = "causatrix"
#: slate.fusion.method values (03 §8; 07 §9: rrf is the default, the others are ablations).
FUSION_METHODS: Final[tuple[str, ...]] = ("rrf", "combsum_minmax", "borda")
#: prism_m.combine values (07 §3.2: add is PRISM's default, conj its alternative form).
PRISM_COMBINE: Final[tuple[str, ...]] = ("add", "conj")
#: The signal families indicator_map must cover, one entry each (03 §1 `family`; 07 §3.6).
FAMILIES: Final[tuple[str, ...]] = get_args(models.Family)
_INDICATORS: Final[frozenset[str]] = frozenset(get_args(models.Indicator))
#: Ranker names are module names under veyltrace_causatrix.rankers (lower snake case).
_RANKER_NAME: Final = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class CausatrixConfig:
    """The effective causatrix section (07 §4) and the shared core values (07 §2.1).

    `rankers` is `rankers.enabled` sorted by name; `weights` pairs each enabled ranker with its
    `rrf.weights` entry; `indicator_map` pairs every family with its RCAEval indicator.
    """

    k: int
    rankers: tuple[str, ...]
    method: str
    rrf_k: int
    weights: tuple[tuple[str, float], ...]
    gate: bool
    abstain_on_constant: bool
    prism_combine: str
    silence_z: float
    damping: float
    iterations: int
    self_loop: bool
    change_min_proximity: float
    edge_gap_min_ms: float
    tail_ratio: float
    indicator_map: tuple[tuple[str, str], ...]
    k_anom: float
    include_external: bool

    @property
    def fusion_k(self) -> int | None:
        """slate.fusion.k: the RRF constant for method rrf, null for methods without one (03 §8)."""
        return self.rrf_k if self.method == "rrf" else None

    def weight(self, ranker: str) -> float:
        """The fusion weight of an enabled ranker (`rrf.weights.<ranker>`)."""
        return dict(self.weights)[ranker]

    def indicator(self, family: str) -> str:
        """The RCAEval indicator of a signal family (07 §3.6 `indicator_map`)."""
        return dict(self.indicator_map)[family]


def _get(section: Mapping[str, Any], name: str, dotted: str) -> Any:
    """`section[a][b]…` for dotted `a.b…`; ConfigError naming `<name>.<dotted>` if absent."""
    node: Any = section
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            msg = f"{name}.{dotted}: no such config key (add it to config/{name}.yaml)"
            raise ConfigError(msg)
        node = cast(Mapping[str, Any], node)[part]
    return node


def _int(value: object, key: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        msg = f"{key} must be an integer >= {minimum}, got {value!r}"
        raise ConfigError(msg)
    return value


def _number(value: object, key: str, low: float = -math.inf, high: float = math.inf) -> float:
    """A finite number in [low, high]."""
    ok = not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)
    if not ok or not low <= float(cast(float, value)) <= high:
        msg = f"{key} must be a finite number in [{low}, {high}], got {value!r}"
        raise ConfigError(msg)
    return float(cast(float, value))


def _bool(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        msg = f"{key} must be a boolean, got {value!r}"
        raise ConfigError(msg)
    return value


def _choice(value: object, key: str, allowed: Sequence[str]) -> str:
    if value not in allowed:
        msg = f"{key} must be one of {tuple(allowed)}, got {value!r}"
        raise ConfigError(msg)
    return str(value)


def _mapping(value: object, key: str) -> Mapping[str, object]:
    """`value` as a string-keyed mapping; ConfigError naming `key` when it is not one."""
    if not isinstance(value, Mapping):
        msg = f"{key} must be a mapping, got {value!r}"
        raise ConfigError(msg)
    return cast(Mapping[str, object], value)


def _rankers(value: object) -> tuple[str, ...]:
    key = "causatrix.rankers.enabled"
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"{key} must be a list of ranker names, got {value!r}"
        raise ConfigError(msg)
    names = cast(Sequence[object], value)
    if not all(isinstance(n, str) and _RANKER_NAME.match(n) for n in names):
        msg = f"{key} must hold lower snake-case ranker names, got {list(names)!r}"
        raise ConfigError(msg)
    found = tuple(sorted(cast(Sequence[str], names)))
    if len(set(found)) != len(found):
        msg = f"{key} lists a ranker twice: {list(found)!r}"
        raise ConfigError(msg)
    return found


def _indicator_map(value: object) -> tuple[tuple[str, str], ...]:
    key = "causatrix.indicator_map"
    raw = _mapping(value, key)
    if set(raw) != set(FAMILIES):
        msg = f"{key} must map exactly the families {sorted(FAMILIES)}, got {sorted(raw)!r}"
        raise ConfigError(msg)
    for family in FAMILIES:
        _choice(raw[family], f"{key}.{family}", sorted(_INDICATORS))
    return tuple((family, str(raw[family])) for family in sorted(FAMILIES))


def _weights(value: object, rankers: tuple[str, ...]) -> tuple[tuple[str, float], ...]:
    """Every `rrf.weights` entry is validated, also for rankers an ablation leaves out (07 §9)."""
    key = "causatrix.rrf.weights"
    raw = _mapping(value, key)
    if not all(_RANKER_NAME.match(str(name)) for name in raw):
        msg = f"{key} must be keyed by lower snake-case ranker names, got {sorted(map(str, raw))!r}"
        raise ConfigError(msg)
    checked = {r: _number(raw[r], f"{key}.{r}", 0.0) for r in sorted(raw)}
    missing = [r for r in rankers if r not in checked]
    if missing:
        msg = f"{key} has no weight for enabled ranker(s) {missing}"
        raise ConfigError(msg)
    return tuple((r, checked[r]) for r in rankers)


def config_from(cfg: Mapping[str, Any], core: Mapping[str, Any]) -> CausatrixConfig:
    """Validate the causatrix section `cfg` (ctx.config) and the `core` section (ctx.config.core)."""

    def get(dotted: str) -> Any:
        return _get(cfg, ENGINE, dotted)

    def key(dotted: str) -> str:
        return f"{ENGINE}.{dotted}"

    rankers = _rankers(get("rankers.enabled"))
    return CausatrixConfig(
        k=_int(get("slate.k"), key("slate.k"), 1),
        rankers=rankers,
        method=_choice(get("fusion.method"), key("fusion.method"), FUSION_METHODS),
        rrf_k=_int(get("rrf.k"), key("rrf.k"), 1),
        weights=_weights(get("rrf.weights"), rankers),
        gate=_bool(get("rrf.gate"), key("rrf.gate")),
        abstain_on_constant=_bool(get("abstain_on_constant"), key("abstain_on_constant")),
        prism_combine=_choice(get("prism_m.combine"), key("prism_m.combine"), PRISM_COMBINE),
        silence_z=_number(get("prism_m.silence_z"), key("prism_m.silence_z"), 0.0),
        damping=_number(get("graph_walk.damping"), key("graph_walk.damping"), 0.0, 1.0),
        iterations=_int(get("graph_walk.iterations"), key("graph_walk.iterations"), 1),
        self_loop=_bool(get("graph_walk.self_loop"), key("graph_walk.self_loop")),
        change_min_proximity=_number(
            get("mode.change_min_proximity"), key("mode.change_min_proximity"), 0.0, 1.0
        ),
        edge_gap_min_ms=_number(get("mode.edge_gap_min_ms"), key("mode.edge_gap_min_ms")),
        tail_ratio=_number(get("mode.tail_ratio"), key("mode.tail_ratio"), 0.0),
        indicator_map=_indicator_map(get("indicator_map")),
        k_anom=_number(_get(core, "core", "thresholds.anomaly_z"), "core.thresholds.anomaly_z"),
        include_external=_bool(
            _get(core, "core", "universe.include_external"), "core.universe.include_external"
        ),
    )
