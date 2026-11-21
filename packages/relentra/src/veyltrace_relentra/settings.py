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
from veyltrace_core.rng import seed_int

__all__ = ["BriefSettings", "Sampler", "brief_settings", "sampler_params"]

_FAULT_CLASSES: Final[tuple[str, ...]] = get_args(models.FaultClass)


@dataclass(frozen=True)
class Sampler:
    """`sampler.*` (08 §3.8). A null value is not sent to the provider (03 §9.1)."""

    temperature: float
    top_p: float | None
    top_k: int | None
    presence_penalty: float | None
    thinking: bool | None
    seed_index: int
    max_tokens: int


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
    max_repairs: int
    sampler: Sampler


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


def _number(config: Mapping[str, Any], dotted: str, *, nullable: bool = True) -> float | None:
    value = _get(config, dotted)
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"relentra.{dotted} must be a number, got {value!r}")
    return float(value)


def _sampler(config: Mapping[str, Any]) -> Sampler:
    temperature = _number(config, "sampler.temperature", nullable=False)
    if temperature is None or temperature < 0:
        raise ConfigError(f"relentra.sampler.temperature must be >= 0, got {temperature!r}")
    top_k, thinking = _get(config, "sampler.top_k"), _get(config, "sampler.thinking")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int)):
        raise ConfigError(f"relentra.sampler.top_k must be an int or null, got {top_k!r}")
    if thinking is not None and not isinstance(thinking, bool):
        raise ConfigError(f"relentra.sampler.thinking must be a bool or null, got {thinking!r}")
    return Sampler(
        temperature=temperature,
        top_p=_number(config, "sampler.top_p"),
        top_k=top_k,
        presence_penalty=_number(config, "sampler.presence_penalty"),
        thinking=thinking,
        seed_index=_count(config, "sampler.seed_index", 0),
        max_tokens=_count(config, "sampler.max_tokens.brief"),
    )


def sampler_params(sampler: Sampler, case_id: str) -> dict[str, Any]:
    """The seven sampler parameters of a call (03 §9.1). The seed depends only on the case and
    `seed_index`, so bench sweeps seeds through config (08 §3.8)."""
    return {
        "temperature": sampler.temperature,
        "top_p": sampler.top_p,
        "top_k": sampler.top_k,
        "presence_penalty": sampler.presence_penalty,
        "thinking": sampler.thinking,
        "seed": seed_int(case_id, f"relentra.seed/{sampler.seed_index}"),
        "max_tokens": sampler.max_tokens,
    }


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
        max_repairs=_count(config, "brief.max_repairs", 0),
        sampler=_sampler(config),
    )
    if settings.cards_k_min > settings.cards_k:
        raise ConfigError(f"relentra.cards.k_min {settings.cards_k_min} exceeds cards.k {settings.cards_k}")
    return settings
