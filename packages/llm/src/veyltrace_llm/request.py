"""Canonical LLM requests and provider outcomes (08 §5.2).

Why: the cassette key must depend only on what the model sees (purpose, model identity, messages
with LF line endings, schema, sampler params), never on which runtime served the call, so a call
recorded on Ollama replays on any machine (package rule 3). `LLMRequest.key` is that key.
`Completion` is one provider outcome: content or an error, with usage, recorded latency and the
runtime that produced it; errors are outcomes too, so replay reproduces them (package rule 6).

Pure data and hashing: no clock, no network, no imports beyond core's canonical JSON.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal, cast, get_args

from veyltrace_core.canonical import canonical_json, normalize
from veyltrace_core.hashing import is_sha256, sha256_bytes

__all__ = [
    "ERROR_KINDS",
    "NULLABLE_PARAMS",
    "PARAM_NAMES",
    "PROVIDERS",
    "REQUEST_VERSION",
    "REQUIRED_PARAMS",
    "CallError",
    "Completion",
    "ErrorKind",
    "LLMRequest",
    "Message",
    "ModelId",
    "Runtime",
    "Usage",
]

#: Version field `v` of the canonical request (08 §5.2). Bump only with a re-record of every cassette.
REQUEST_VERSION: Final = 1
#: Provider kinds of config/llm.yaml `provider` (08 §4; 03 §9.1 proposals.model.provider).
PROVIDERS: Final = ("ollama", "llamacpp", "openai_compat", "fake")
Role = Literal["system", "user", "assistant"]
ROLES: Final[tuple[str, ...]] = get_args(Role)
#: Sampler parameters of every request (08 §5.2 canonical request; 03 §9.1 model.params). In 03,
#: `?` means required and nullable: all seven keys are always present, and the key covers all seven.
PARAM_NAMES: Final = frozenset(
    {"temperature", "top_p", "top_k", "presence_penalty", "seed", "max_tokens", "thinking"}
)
REQUIRED_PARAMS: Final = PARAM_NAMES
#: The `?` params of 03 §9.1 SamplerParams: null means "not sent", so the runtime's default applies.
NULLABLE_PARAMS: Final = frozenset({"top_p", "top_k", "presence_penalty", "thinking"})
_INT_PARAMS: Final = frozenset({"top_k", "seed", "max_tokens"})
#: 03 §9.1: seed is an integer in [0, 2^31 - 1).
SEED_LIMIT: Final = 2**31 - 1
#: Dotted lowercase purpose, e.g. relentra.brief, relentra.investigate.pick, causivra.narrate.
_PURPOSE_RE: Final = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")

#: Why a call produced no content. `connection`, `timeout`, `http` (non-2xx status) and
#: `bad_response` (unreadable provider envelope) come from HTTP providers; `unscripted` only from
#: FakeProvider (no scripted reply for the request).
ErrorKind = Literal["connection", "timeout", "http", "bad_response", "unscripted"]
ERROR_KINDS: Final[tuple[str, ...]] = get_args(ErrorKind)


#: Any run of CRs before a LF is one line break (D1 (a) on #227). Idempotent, so normalising
#: twice keeps the key: "a\r\r\nb" becomes "a\nb", not "a\r\nb".
_CRLF_RE: Final = re.compile(r"\r+\n")


def _lf(text: str) -> str:
    """CR…CRLF → LF, so a Windows checkout hashes prompts identically (08 §3.5)."""
    return _CRLF_RE.sub("\n", text)


def _freeze(value: Any) -> Any:
    """A read-only view of plain JSON: mappings become MappingProxyType, lists tuples, at every depth."""
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in cast(dict[str, Any], value).items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in cast(list[Any], value))
    return value


def _thaw(value: Any) -> Any:
    """The inverse of _freeze: a fresh plain-JSON copy the caller may change."""
    if isinstance(value, MappingProxyType):
        return {k: _thaw(v) for k, v in cast(Mapping[str, Any], value).items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in cast(tuple[Any, ...], value)]
    return value


@dataclass(frozen=True)
class Message:
    """One chat message; `content` is stored with LF line endings."""

    role: Role
    content: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            msg = f"message role must be one of {ROLES}, got {self.role!r}"
            raise ValueError(msg)
        if not isinstance(self.content, str):
            msg = f"message content must be a string, got {type(self.content).__name__}"
            raise TypeError(msg)
        object.__setattr__(self, "content", _lf(self.content))

    def as_json(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ModelId:
    """The model identity that enters the key: name and, once pinned, the GGUF SHA-256 (08 §4)."""

    name: str
    gguf_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            msg = "model name must be non-empty"
            raise ValueError(msg)
        if self.gguf_sha256 is not None and not is_sha256(self.gguf_sha256):
            msg = f"gguf_sha256 must be a lowercase 64-hex sha256, got {self.gguf_sha256!r}"
            raise ValueError(msg)

    def as_json(self) -> dict[str, str | None]:
        return {"name": self.name, "gguf_sha256": self.gguf_sha256}


def _check_params(params: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(params) - PARAM_NAMES)
    if unknown:
        msg = f"unknown sampler params {unknown}; expected a subset of {sorted(PARAM_NAMES)}"
        raise ValueError(msg)
    missing = sorted(REQUIRED_PARAMS - set(params))
    if missing:
        msg = f"sampler params {missing} are required, null where 03 §9.1 allows it (model.params)"
        raise ValueError(msg)
    out: dict[str, Any] = {}
    for name in sorted(params):
        value: object = params[name]
        if value is None:
            ok = name in NULLABLE_PARAMS
        elif name == "thinking":
            ok = isinstance(value, bool)
        elif name in _INT_PARAMS:
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else:
            ok = isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        if not ok:
            msg = f"sampler param {name}={value!r} has the wrong type"
            raise ValueError(msg)
        out[name] = value
    if cast(int, out["seed"]) >= SEED_LIMIT:
        msg = f"seed must be in [0, 2^31 - 1), got {out['seed']}"
        raise ValueError(msg)
    return out


@dataclass(frozen=True)
class LLMRequest:
    """The canonical request (08 §5.2). Provider kind, URL, timeouts and thread counts are not
    part of it: they are runtime settings, recorded in the cassette entry for audit only."""

    purpose: str
    model: ModelId
    messages: tuple[Message, ...]
    params: Mapping[str, Any]
    schema: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if _PURPOSE_RE.fullmatch(self.purpose) is None:
            msg = f"purpose must be dotted lowercase (e.g. relentra.brief), got {self.purpose!r}"
            raise ValueError(msg)
        messages = tuple(cast(Sequence[Message], self.messages))
        if not messages:
            msg = "a request needs at least one message"
            raise ValueError(msg)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "params", MappingProxyType(_check_params(self.params)))
        if self.schema is not None:
            # A deep read-only copy of the plain JSON: rejects non-JSON values early, and no edit of
            # the caller's dict, or of this view at any depth, can move the key.
            object.__setattr__(self, "schema", _freeze(normalize(dict(self.schema))))

    def schema_json(self) -> dict[str, Any] | None:
        """A fresh plain-dict copy of the schema, for a provider body (editing it changes nothing)."""
        return None if self.schema is None else cast(dict[str, Any], _thaw(self.schema))

    def canonical(self) -> dict[str, Any]:
        """The JSON object whose canonical bytes are hashed into the key."""
        return {
            "v": REQUEST_VERSION,
            "purpose": self.purpose,
            "model": self.model.as_json(),
            "messages": [m.as_json() for m in self.messages],
            "schema": self.schema_json(),
            "params": dict(self.params),
        }

    @property
    def key(self) -> str:
        """Cassette key: SHA-256 of canonical_json(canonical()) (package rule 3)."""
        return sha256_bytes(canonical_json(self.canonical()))


@dataclass(frozen=True)
class Usage:
    """Provider-reported token counts (08 §2.2 budget_used sums them)."""

    tokens_in: int
    tokens_out: int

    def __post_init__(self) -> None:
        for name in ("tokens_in", "tokens_out"):
            value: object = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                msg = f"{name} must be a non-negative int, got {value!r}"
                raise ValueError(msg)

    def as_json(self) -> dict[str, int]:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out}


@dataclass(frozen=True)
class Runtime:
    """Which runtime produced a completion; audit only, never part of the key (08 §5.2)."""

    provider: str
    version: str | None = None

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            msg = f"runtime provider must be one of {PROVIDERS}, got {self.provider!r}"
            raise ValueError(msg)

    def as_json(self) -> dict[str, str | None]:
        return {"provider": self.provider, "version": self.version}


@dataclass(frozen=True)
class CallError:
    """A provider failure as recorded in the cassette."""

    kind: ErrorKind
    message: str

    def __post_init__(self) -> None:
        if self.kind not in ERROR_KINDS:
            msg = f"error kind must be one of {ERROR_KINDS}, got {self.kind!r}"
            raise ValueError(msg)

    def as_json(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message}


@dataclass(frozen=True)
class Completion:
    """One provider outcome: exactly one of `content` and `error` is set.

    `latency_ms` is measured by the provider (FakeProvider reports a fixed value) and stored in the
    cassette before the completion is returned, so budgets replay exactly (08 §5.1 rule 1). It is
    rounded here with canonical JSON's float rule (9 decimals), so the completion record mode
    returns equals the one replay reads back from the cassette.
    """

    content: str | None
    usage: Usage
    latency_ms: float
    runtime: Runtime
    error: CallError | None = field(default=None)

    def __post_init__(self) -> None:
        if (self.content is None) == (self.error is None):
            msg = "a completion has exactly one of content and error"
            raise ValueError(msg)
        latency: object = self.latency_ms
        if isinstance(latency, bool) or not isinstance(latency, int | float):
            msg = f"latency_ms must be a number, got {latency!r}"
            raise TypeError(msg)
        if not math.isfinite(latency) or latency < 0:
            msg = f"latency_ms must be finite and >= 0, got {latency!r}"
            raise ValueError(msg)
        object.__setattr__(self, "latency_ms", cast(float, normalize(float(latency))))

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_json(self) -> dict[str, Any]:
        """The cassette `responses[]` entry (08 §5.2 layout); both `content` and `error` always present."""
        return {
            "content": self.content,
            "error": None if self.error is None else self.error.as_json(),
            "usage": self.usage.as_json(),
            "latency_ms": self.latency_ms,
            "runtime": self.runtime.as_json(),
        }

    @property
    def response_sha256(self) -> str:
        """agent_trace `response_sha256`: SHA-256 of the content, or of canonical_json of the
        error object (08 §5.3)."""
        if self.error is not None:
            return sha256_bytes(canonical_json(self.error.as_json()))
        return sha256_bytes(cast(str, self.content).encode("utf-8"))
