"""Typed view of `config/causalith.yaml` (05-causalith §4), validated once per run.

Why typed: every threshold is a named config key (AGENTS §5), and a malformed value should fail as
a ConfigError before the graph is built. Sections arrive with the code that reads them (O-05a: edges;
entry.* is parsed by `veyltrace_causalith.entry`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from veyltrace_causalith.graph import EdgeRules
from veyltrace_core.errors import ConfigError

__all__ = ["CausalithConfig", "causalith_config"]


def _mapping(section: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value: object = section.get(key)
    if not isinstance(value, Mapping):
        msg = f"{where}.{key} must be a mapping"
        raise ConfigError(msg)
    return cast("Mapping[str, Any]", value)


def _number(section: Mapping[str, Any], key: str, where: str) -> float:
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        msg = f"{where}.{key} must be a finite number >= 0, got {value!r}"
        raise ConfigError(msg)
    return float(value)


def _count(section: Mapping[str, Any], key: str, where: str) -> int:
    value: object = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{where}.{key} must be an integer >= 1, got {value!r}"
        raise ConfigError(msg)
    return value


@dataclass(frozen=True)
class CausalithConfig:
    """The validated Causalith section."""

    edges: EdgeRules


def causalith_config(section: Mapping[str, Any]) -> CausalithConfig:
    """Validate the Causalith config section (`ctx.config`)."""
    ed = _mapping(section, "edges", "causalith")
    where = "causalith.edges"
    return CausalithConfig(
        edges=EdgeRules(
            latency_ratio=_number(ed, "anom_latency_ratio", where),
            latency_min_ms=_number(ed, "anom_latency_min_ms", where),
            error_delta=_number(ed, "anom_error_delta", where),
            silence_min_baseline_calls=_count(ed, "silence_min_baseline_calls", where),
        ),
    )
