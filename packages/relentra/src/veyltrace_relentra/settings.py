"""Typed settings of `brief` mode (08 §4), read once and checked before any model call.

Why here and not at each use: a bad value must stop the run as a ConfigError (exit 4) before the
prompt is built, never turn into a silent default. Every number comes from `config/relentra.yaml`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast, get_args

from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError

__all__ = ["BriefSettings", "brief_settings"]

_FAULT_CLASSES: Final[tuple[str, ...]] = get_args(models.FaultClass)


@dataclass(frozen=True)
class BriefSettings:
    """The keys of 08 §4 that shape the output schema of `brief` mode."""

    max_proposals: int
    max_claims_per_proposal: int
    max_signal_enum: int
    schema_max_bytes: int
    exclude_fault_classes: tuple[str, ...]


def _get(config: Mapping[str, Any], dotted: str) -> object:
    node: object = config
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise ConfigError(f"config/relentra.yaml: missing key {dotted}")
        node = cast("Mapping[str, object]", node)[part]
    return node


def _count(config: Mapping[str, Any], dotted: str) -> int:
    value = _get(config, dotted)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"relentra.{dotted} must be an int >= 1, got {value!r}")
    return value


def brief_settings(config: Mapping[str, Any]) -> BriefSettings:
    """Validate the keys of `config/relentra.yaml` this module reads; every key is required."""
    excluded = _get(config, "schema.exclude_fault_classes")
    if not isinstance(excluded, list | tuple):
        raise ConfigError(f"relentra.schema.exclude_fault_classes must be a list, got {excluded!r}")
    classes = [str(c) for c in cast("list[object] | tuple[object, ...]", excluded)]
    if not set(classes) <= set(_FAULT_CLASSES):
        raise ConfigError(f"relentra.schema.exclude_fault_classes has unknown classes: {classes!r}")
    return BriefSettings(
        max_proposals=_count(config, "brief.max_proposals"),
        max_claims_per_proposal=_count(config, "budget.max_claims_per_proposal"),
        max_signal_enum=_count(config, "schema.max_signal_enum"),
        schema_max_bytes=_count(config, "schema.max_bytes"),
        exclude_fault_classes=tuple(sorted(classes)),
    )
