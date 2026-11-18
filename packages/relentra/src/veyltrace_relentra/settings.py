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
    """The keys of 08 §4 that shape the prompt and the output of `brief` mode."""

    max_proposals: int
    max_hypotheses: int
    max_claims_per_proposal: int
    max_signal_enum: int
    schema_max_bytes: int
    exclude_fault_classes: tuple[str, ...]
    cards_k: int
    cards_k_min: int
    pool_context_n: int
    max_prompt_tokens: int
    chars_per_token: float
    include_brief: bool
    permute_slate: bool


def _get(config: Mapping[str, Any], dotted: str) -> object:
    node: object = config
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise ConfigError(f"config/relentra.yaml: missing key {dotted}")
        node = cast("Mapping[str, object]", node)[part]
    return node


def _count(config: Mapping[str, Any], dotted: str, minimum: int = 1) -> int:
    value = _get(config, dotted)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"relentra.{dotted} must be an int >= {minimum}, got {value!r}")
    return value


def _flag(config: Mapping[str, Any], dotted: str) -> bool:
    value = _get(config, dotted)
    if not isinstance(value, bool):
        raise ConfigError(f"relentra.{dotted} must be a bool, got {value!r}")
    return value


def brief_settings(config: Mapping[str, Any]) -> BriefSettings:
    """Validate the keys of `config/relentra.yaml` this module reads; every key is required."""
    excluded = _get(config, "schema.exclude_fault_classes")
    if not isinstance(excluded, list | tuple):
        raise ConfigError(f"relentra.schema.exclude_fault_classes must be a list, got {excluded!r}")
    classes = [str(c) for c in cast("list[object] | tuple[object, ...]", excluded)]
    if not set(classes) <= set(_FAULT_CLASSES):
        raise ConfigError(f"relentra.schema.exclude_fault_classes has unknown classes: {classes!r}")
    per_token = _get(config, "prompt.chars_per_token")
    if isinstance(per_token, bool) or not isinstance(per_token, int | float) or per_token <= 0:
        raise ConfigError(f"relentra.prompt.chars_per_token must be > 0, got {per_token!r}")
    settings = BriefSettings(
        max_proposals=_count(config, "brief.max_proposals"),
        max_hypotheses=_count(config, "budget.max_hypotheses"),
        max_claims_per_proposal=_count(config, "budget.max_claims_per_proposal"),
        max_signal_enum=_count(config, "schema.max_signal_enum"),
        schema_max_bytes=_count(config, "schema.max_bytes"),
        exclude_fault_classes=tuple(sorted(classes)),
        cards_k=_count(config, "cards.k"),
        cards_k_min=_count(config, "cards.k_min"),
        pool_context_n=_count(config, "cards.pool_context_n", 0),
        max_prompt_tokens=_count(config, "budget.max_prompt_tokens"),
        chars_per_token=float(per_token),
        include_brief=_flag(config, "prompt.include_brief"),
        permute_slate=_flag(config, "prompt.permute_slate"),
    )
    if settings.cards_k_min > settings.cards_k:
        raise ConfigError(f"relentra.cards.k_min {settings.cards_k_min} exceeds cards.k {settings.cards_k}")
    return settings
