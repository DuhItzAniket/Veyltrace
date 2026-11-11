"""FakeProvider: a deterministic, scripted LLM for tests and the AI-on determinism arm (08 §7).

Why: Relentra, Causivra and the gateway must be testable without a model (package rule 8; CI never
needs a running model). A script maps requests to replies:

1. `by_key`: the n-th call with a given cassette key gets the n-th reply listed for that key;
2. `by_purpose`: otherwise the n-th call with a given purpose gets the n-th reply for that purpose;
3. `default`: otherwise one fixed reply, or a function of the request;
4. otherwise the call fails with an `unscripted` error, which (like every provider error) is an
   outcome, so a run with an unscripted fake still finishes and still replays.

A reply is content or an error (`connection`, `timeout`, …) with fixed usage and latency, so budgets
computed from recorded latency are exact in tests. Occurrence counters live in the instance and
depend only on call order, so two runs with the same calls get the same replies.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from veyltrace_core.canonical import JSONLike, canonical_json_str
from veyltrace_llm.request import CallError, Completion, ErrorKind, LLMRequest, Runtime, Usage

__all__ = ["DEFAULT_LATENCY_MS", "DEFAULT_USAGE", "FAKE_RUNTIME", "FakeProvider", "FakeReply"]

#: Usage every fake reply reports unless the script says otherwise (test-only, a priori: small
#: fixed numbers, so budget sums in tests are exact).
DEFAULT_USAGE: Final = Usage(tokens_in=100, tokens_out=50)
#: Recorded latency of every fake reply unless scripted (test-only, a priori).
DEFAULT_LATENCY_MS: Final = 10.0
FAKE_RUNTIME: Final = Runtime(provider="fake", version=None)


@dataclass(frozen=True)
class FakeReply:
    """One scripted outcome: `content` (model text) or `error` (a recorded provider failure)."""

    content: str | None = None
    error: ErrorKind | None = None
    message: str = ""
    usage: Usage = DEFAULT_USAGE
    latency_ms: float = DEFAULT_LATENCY_MS

    def __post_init__(self) -> None:
        if (self.content is None) == (self.error is None):
            msg = "a FakeReply has exactly one of content and error"
            raise ValueError(msg)

    @classmethod
    def json(
        cls, value: JSONLike, *, usage: Usage = DEFAULT_USAGE, latency_ms: float = DEFAULT_LATENCY_MS
    ) -> FakeReply:
        """A reply whose content is `value` as canonical JSON text."""
        return cls(content=canonical_json_str(value), usage=usage, latency_ms=latency_ms)

    @classmethod
    def failure(
        cls, kind: ErrorKind, message: str = "", *, latency_ms: float = DEFAULT_LATENCY_MS
    ) -> FakeReply:
        """A provider error outcome, e.g. `FakeReply.failure("timeout")`; it reports no tokens."""
        text = message or f"fake {kind}"
        return cls(error=kind, message=text, usage=Usage(0, 0), latency_ms=latency_ms)

    def completion(self) -> Completion:
        error = None if self.error is None else CallError(kind=self.error, message=self.message)
        return Completion(
            content=self.content,
            usage=self.usage,
            latency_ms=self.latency_ms,
            runtime=FAKE_RUNTIME,
            error=error,
        )


type Responder = Callable[[LLMRequest], FakeReply]


class FakeProvider:
    """Scripted provider; `calls` lists every request it served, in order."""

    kind: Final = "fake"

    def __init__(
        self,
        by_purpose: Mapping[str, Sequence[FakeReply]] | None = None,
        *,
        by_key: Mapping[str, Sequence[FakeReply]] | None = None,
        default: FakeReply | Responder | None = None,
    ) -> None:
        self._by_purpose = {p: tuple(r) for p, r in (by_purpose or {}).items()}
        self._by_key = {k: tuple(r) for k, r in (by_key or {}).items()}
        self._default = default
        self._seen_purpose: Counter[str] = Counter()
        self._seen_key: Counter[str] = Counter()
        self.calls: list[LLMRequest] = []

    def _pick(self, request: LLMRequest, key_n: int, purpose_n: int) -> FakeReply:
        keyed = self._by_key.get(request.key, ())
        if key_n < len(keyed):
            return keyed[key_n]
        scripted = self._by_purpose.get(request.purpose, ())
        if purpose_n < len(scripted):
            return scripted[purpose_n]
        if isinstance(self._default, FakeReply):
            return self._default
        if self._default is not None:
            return self._default(request)
        detail = f"no scripted reply for purpose {request.purpose!r} (call {purpose_n + 1})"
        return FakeReply.failure("unscripted", detail, latency_ms=0.0)

    def complete(self, request: LLMRequest) -> Completion:
        """Return the scripted outcome for `request` (never raises for a provider failure)."""
        key = request.key
        key_n, purpose_n = self._seen_key[key], self._seen_purpose[request.purpose]
        self._seen_key[key] += 1
        self._seen_purpose[request.purpose] += 1
        self.calls.append(request)
        return self._pick(request, key_n, purpose_n).completion()
