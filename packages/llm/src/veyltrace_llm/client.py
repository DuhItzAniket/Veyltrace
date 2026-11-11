"""`LLMClient`: one run's access to the model, in the run's AI mode (02 §5.2; 08 §5.2).

- `off`: every call raises `AIDisabled`.
- `record`: the provider answers; every outcome, errors included, is appended to the cassette
  before it is returned.
- `replay`: the cassette answers and a miss raises `CassetteMiss`; no provider is ever built, so
  no socket opens.

`call_json` is the constrained call engines use: the JSON schema goes to the runtime for
constrained decoding and into the cassette key; the content is parsed as JSON here, and the caller
re-validates it against its schema and models (Relentra and Causivra package rules).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veyltrace_core.ids import AI_MODES, AIMode
from veyltrace_llm.cassette import Cassette
from veyltrace_llm.errors import AIDisabled, raise_for
from veyltrace_llm.providers import Provider, provider_for
from veyltrace_llm.request import Completion, LLMRequest, Message
from veyltrace_llm.settings import LLMSettings

__all__ = ["JsonReply", "LLMClient"]


@dataclass(frozen=True)
class JsonReply:
    """A successful constrained call: the raw completion and its content parsed as JSON.

    `value` is None and `parse_error` says why when the content is not valid JSON; a model that
    ignores its grammar is the caller's validation failure (repair or salvage), not a provider error.
    """

    request: LLMRequest
    completion: Completion
    value: Any
    parse_error: str | None

    @property
    def key(self) -> str:
        return self.request.key


def _reject_constant(token: str) -> object:
    """NaN, Infinity and -Infinity are not JSON (RFC 8259); json.loads would accept them."""
    raise ValueError(f"{token} is not a JSON value")


class LLMClient:
    """Calls in one AI mode; `cassette_dir` is required unless the mode is off."""

    def __init__(
        self,
        settings: LLMSettings,
        mode: AIMode,
        cassette_dir: Path | None = None,
        *,
        provider: Provider | None = None,
        force_record: bool = False,
    ) -> None:
        if mode not in AI_MODES:
            raise ValueError(f"ai mode must be one of {AI_MODES}, got {mode!r}")
        self.settings = settings
        self.mode: AIMode = mode
        self._provider: Provider | None = None
        self._cassette: Cassette | None = None
        if mode == "off":
            return
        if cassette_dir is None:
            raise ValueError(f"ai mode {mode!r} needs a cassette directory")
        if mode == "record":
            self._provider = provider if provider is not None else provider_for(settings)
            self._cassette = Cassette(
                cassette_dir, "record", force_record=force_record, recorded_with=settings.audit()
            )
        else:
            self._cassette = Cassette(cassette_dir, "replay")

    def complete(self, request: LLMRequest) -> Completion:
        """One call; the outcome may be an error (recorded, not raised)."""
        if self.mode == "off" or self._cassette is None:
            raise AIDisabled(f"ai mode is off: refusing the {request.purpose} call")
        if self._provider is None:
            return self._cassette.lookup(request)
        completion = self._provider.complete(request)
        self._cassette.record(request, completion)
        return completion

    def call_json(
        self,
        purpose: str,
        messages: Sequence[Message],
        schema: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> JsonReply:
        """A JSON-schema constrained call. Provider errors raise ProviderError (with the recorded
        completion attached, for budgets); invalid JSON is returned, not raised."""
        request = LLMRequest(purpose, self.settings.model, tuple(messages), params, schema)
        completion = self.complete(request)
        if completion.error is not None:
            raise_for(completion.error, completion)
        try:
            value = json.loads(completion.content or "", parse_constant=_reject_constant)
            return JsonReply(request, completion, value, None)
        except ValueError as exc:
            return JsonReply(request, completion, None, f"content is not JSON: {exc}")
