"""Provider selection from `config/llm.yaml` (08 §4 `provider`).

A provider turns a canonical request into one `Completion` and never raises for a provider failure:
connection errors, timeouts and bad responses come back as error outcomes, so the cassette records
them (package rule 6) and nothing retries behind the caller's back.
"""

from __future__ import annotations

from typing import Protocol

from veyltrace_core.errors import ConfigError
from veyltrace_llm.fake import FakeProvider
from veyltrace_llm.request import Completion, LLMRequest
from veyltrace_llm.settings import LLMSettings

__all__ = ["Provider", "provider_for"]


class Provider(Protocol):
    """What the client needs from a provider."""

    def complete(self, request: LLMRequest) -> Completion: ...


def provider_for(settings: LLMSettings) -> Provider:
    """The provider named by `llm.provider`. `fake` is an unscripted FakeProvider: every call is a
    recorded `unscripted` error, which a run treats like a model that is down."""
    if settings.provider == "fake":
        return FakeProvider()
    raise ConfigError(
        f"llm.provider {settings.provider!r} is not available yet (HTTP providers arrive in X-01c)"
    )
