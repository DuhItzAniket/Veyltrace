"""Typed view of `config/causalith.yaml` (05-causalith §4), validated once per run.

Why typed: every threshold is a named config key (AGENTS §5), and a malformed value should fail as
a ConfigError before the graph is built. Sections arrive with the code that reads them (O-05a: edges;
O-05b: node_kinds, graph; O-05c: logs; entry.* is parsed by `veyltrace_causalith.entry`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from veyltrace_causalith.graph import EdgeRules, KindRules
from veyltrace_core.errors import ConfigError

__all__ = ["CausalithConfig", "GraphConfig", "LogsConfig", "causalith_config"]


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


def _patterns(section: Mapping[str, Any], key: str, where: str) -> tuple[re.Pattern[str], ...]:
    value: object = section.get(key)
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"{where}.{key} must be a list of regular expressions, got {value!r}"
        raise ConfigError(msg)
    out: list[re.Pattern[str]] = []
    for item in cast("Sequence[object]", value):
        if not isinstance(item, str) or not item:
            msg = f"{where}.{key} must hold non-empty strings, got {item!r}"
            raise ConfigError(msg)
        try:
            out.append(re.compile(item))
        except re.error as exc:
            msg = f"{where}.{key}: invalid regular expression {item!r}: {exc}"
            raise ConfigError(msg) from exc
    return tuple(out)


@dataclass(frozen=True)
class GraphConfig:
    """`graph.*` (05 §3.1)."""

    include_external: bool
    external_min_calls: int


@dataclass(frozen=True)
class LogsConfig:
    """`logs.*` (05 §3.4): mentions a (speaker, target) pair needs to become an edge."""

    min_mentions: int


@dataclass(frozen=True)
class CausalithConfig:
    """The validated Causalith section."""

    kinds: KindRules
    graph: GraphConfig
    edges: EdgeRules
    logs: LogsConfig


def causalith_config(section: Mapping[str, Any]) -> CausalithConfig:
    """Validate the Causalith config section (`ctx.config`)."""
    nk = _mapping(section, "node_kinds", "causalith")
    gr = _mapping(section, "graph", "causalith")
    ed = _mapping(section, "edges", "causalith")
    include: object = gr.get("include_external")
    if not isinstance(include, bool):
        msg = f"causalith.graph.include_external must be true or false, got {include!r}"
        raise ConfigError(msg)
    where = "causalith.node_kinds"
    return CausalithConfig(
        kinds=KindRules(
            db=_patterns(nk, "db_patterns", where),
            cache=_patterns(nk, "cache_patterns", where),
            queue=_patterns(nk, "queue_patterns", where),
        ),
        graph=GraphConfig(
            include_external=include, external_min_calls=_count(gr, "external_min_calls", "causalith.graph")
        ),
        edges=EdgeRules(
            latency_ratio=_number(ed, "anom_latency_ratio", "causalith.edges"),
            latency_min_ms=_number(ed, "anom_latency_min_ms", "causalith.edges"),
            error_delta=_number(ed, "anom_error_delta", "causalith.edges"),
            silence_min_baseline_calls=_count(ed, "silence_min_baseline_calls", "causalith.edges"),
        ),
        logs=LogsConfig(
            min_mentions=_count(_mapping(section, "logs", "causalith"), "min_mentions", "causalith.logs")
        ),
    )
