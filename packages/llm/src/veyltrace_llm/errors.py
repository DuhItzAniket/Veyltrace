"""Errors raised by `veyltrace_llm` (08 §5.2, §6).

Every class derives from core's `VeyltraceError`, so the pipeline and the CLI map it to an exit code
without knowing this package. A provider failure is a recorded outcome first (package rule 6) and an
exception second: `ProviderError` carries the `CallError` that the cassette stores, so replay raises
the same error the recording saw.
"""

from __future__ import annotations

from veyltrace_core.errors import VeyltraceError
from veyltrace_llm.request import CallError, Completion

__all__ = ["AIDisabled", "LLMError", "ProviderError", "ProviderTimeout", "ProviderUnavailable"]


class LLMError(VeyltraceError):
    """Base class of every `veyltrace_llm` failure."""


class AIDisabled(LLMError):
    """`ai.mode = off`: `veyltrace_llm` refuses every call (08 §5.2 modes table)."""


class ProviderError(LLMError):
    """The provider returned no usable completion; `error` is what the cassette records and
    `completion` (when known) the whole recorded outcome, whose usage and latency still count
    towards the caller's budgets (08 §5.1 rule 1)."""

    def __init__(self, error: CallError, completion: Completion | None = None) -> None:
        super().__init__(f"LLM provider error ({error.kind}): {error.message}")
        self.error = error
        self.completion = completion

    def __reduce__(self) -> tuple[type[ProviderError], tuple[CallError, Completion | None]]:
        return (type(self), (self.error, self.completion))


class ProviderUnavailable(ProviderError):
    """The provider could not be reached (connect error after `request.connect_timeout_s`)."""


class ProviderTimeout(ProviderError):
    """Generation did not finish within `request.timeout_s`."""


def raise_for(error: CallError, completion: Completion | None = None) -> None:
    """Raise the `ProviderError` subclass that matches `error.kind`."""
    if error.kind == "connection":
        raise ProviderUnavailable(error, completion)
    if error.kind == "timeout":
        raise ProviderTimeout(error, completion)
    raise ProviderError(error, completion)
