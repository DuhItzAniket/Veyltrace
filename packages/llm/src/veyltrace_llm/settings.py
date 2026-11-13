"""`config/llm.yaml` as typed settings (08 §4).

Why: every engine that calls a model (Relentra, Causivra) and the gateway's health probe read the
same section, so it is validated once, here, the same way for all of them. Every key is required
(the repo file declares them all) and every bad value is a ConfigError (exit 4), including a remote
`base_url` without the opt-in (guard) and `cassette.strict = false`, which this package does not
offer: strict replay is unconditional (package rule 4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from veyltrace_core.errors import ConfigError
from veyltrace_llm.guard import Endpoint, check_base_url
from veyltrace_llm.request import PROVIDERS, ModelId

__all__ = ["LLMSettings", "settings_from"]

SECTION: Final = "llm"


@dataclass(frozen=True)
class LLMSettings:
    """The llm section. Only `model` enters the cassette key; the rest is runtime audit (08 §5.2)."""

    provider: str
    base_url: str
    endpoint: Endpoint
    model: ModelId
    fallback_name: str | None
    num_ctx: int
    num_thread: int | None
    parallel: int
    cache_prompt: bool
    connect_timeout_s: float
    timeout_s: float

    def audit(self) -> dict[str, Any]:
        """Runtime settings recorded in each cassette entry (never part of the key; no secrets)."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "num_ctx": self.num_ctx,
            "num_thread": self.num_thread,
            "parallel": self.parallel,
            "cache_prompt": self.cache_prompt,
            "connect_timeout_s": self.connect_timeout_s,
            "timeout_s": self.timeout_s,
        }


def _get(section: Mapping[str, Any], dotted: str) -> object:
    node: object = section
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise ConfigError(f"config/llm.yaml: missing key {dotted}")
        node = cast(Mapping[str, object], node)[part]
    return node


def _int(section: Mapping[str, Any], dotted: str, *, minimum: int, nullable: bool = False) -> int | None:
    value = _get(section, dotted)
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"llm.{dotted} must be an int >= {minimum}, got {value!r}")
    return value


def _seconds(section: Mapping[str, Any], dotted: str) -> float:
    value = _get(section, dotted)
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ConfigError(f"llm.{dotted} must be a positive number of seconds, got {value!r}")
    return float(value)


def _str(section: Mapping[str, Any], dotted: str, *, nullable: bool = False) -> str | None:
    value = _get(section, dotted)
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"llm.{dotted} must be a non-empty string, got {value!r}")
    return value


def settings_from(section: Mapping[str, Any], env: Mapping[str, str] | None = None) -> LLMSettings:
    """Validate the llm section (`ctx.config.section("llm")` or a loaded file)."""
    provider = _str(section, "provider")
    if provider not in PROVIDERS:
        raise ConfigError(f"llm.provider must be one of {PROVIDERS}, got {provider!r}")
    base_url = cast(str, _str(section, "base_url"))
    gguf = _str(section, "model.gguf_sha256", nullable=True)
    try:
        model = ModelId(cast(str, _str(section, "model.name")), gguf)
    except ValueError as exc:
        raise ConfigError(f"llm.model: {exc}") from exc
    cache_prompt, strict = _get(section, "runtime.cache_prompt"), _get(section, "cassette.strict")
    if not isinstance(cache_prompt, bool):
        raise ConfigError(f"llm.runtime.cache_prompt must be a bool, got {cache_prompt!r}")
    if strict is not True:
        raise ConfigError(
            f"llm.cassette.strict must be true (strict replay is unconditional), got {strict!r}"
        )
    return LLMSettings(
        provider=provider,
        base_url=base_url,
        endpoint=check_base_url(base_url, env),
        model=model,
        fallback_name=_str(section, "model.fallback_name", nullable=True),
        num_ctx=cast(int, _int(section, "runtime.num_ctx", minimum=1)),
        num_thread=_int(section, "runtime.num_thread", minimum=1, nullable=True),
        parallel=cast(int, _int(section, "runtime.parallel", minimum=1)),
        cache_prompt=cache_prompt,
        connect_timeout_s=_seconds(section, "request.connect_timeout_s"),
        timeout_s=_seconds(section, "request.timeout_s"),
    )
