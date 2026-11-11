"""FakeProvider: scripted selection, errors and timeouts, fixed usage, determinism (08 §7)."""

from __future__ import annotations

import pytest

from veyltrace_llm.errors import ProviderError, ProviderTimeout, ProviderUnavailable, raise_for
from veyltrace_llm.fake import DEFAULT_LATENCY_MS, DEFAULT_USAGE, FakeProvider, FakeReply
from veyltrace_llm.request import ErrorKind, LLMRequest, Message, ModelId, Usage

PARAMS = {"temperature": 0.7, "seed": 7, "max_tokens": 32}


def _req(purpose: str = "relentra.brief", text: str = "q") -> LLMRequest:
    return LLMRequest(purpose, ModelId("m"), (Message("user", text),), PARAMS)


def test_by_purpose_follows_occurrence_order() -> None:
    fake = FakeProvider({"relentra.brief": [FakeReply("a"), FakeReply("b")]})
    assert [fake.complete(_req()).content for _ in range(2)] == ["a", "b"]
    third = fake.complete(_req())
    assert third.error is not None and third.error.kind == "unscripted"
    assert len(fake.calls) == 3


def test_by_key_wins_over_purpose_and_counts_per_key() -> None:
    special = _req(text="special")
    fake = FakeProvider(
        {"relentra.brief": [FakeReply("p1"), FakeReply("p2")]}, by_key={special.key: [FakeReply("k1")]}
    )
    assert fake.complete(special).content == "k1"
    # The purpose counter advanced too, so the next plain call gets the second purpose reply.
    assert fake.complete(_req()).content == "p2"
    # The key script is used up; the purpose script is too: unscripted.
    assert fake.complete(special).error is not None


def test_default_reply_and_responder() -> None:
    assert FakeProvider(default=FakeReply("d")).complete(_req("causivra.narrate")).content == "d"
    echo = FakeProvider(default=lambda r: FakeReply(r.messages[-1].content.upper()))
    assert echo.complete(_req(text="hi")).content == "HI"


def test_usage_and_latency_are_fixed_unless_scripted() -> None:
    plain = FakeProvider(default=FakeReply("x")).complete(_req())
    assert plain.usage == DEFAULT_USAGE and plain.latency_ms == DEFAULT_LATENCY_MS
    assert plain.runtime.provider == "fake"
    custom = FakeProvider(default=FakeReply("x", usage=Usage(9, 8), latency_ms=1234.5)).complete(_req())
    assert (custom.usage, custom.latency_ms) == (Usage(9, 8), 1234.5)


def test_json_reply_is_canonical_text() -> None:
    reply = FakeReply.json({"b": [1, 2.5], "a": "é"})
    assert reply.content == '{"a":"é","b":[1,2.5]}'


@pytest.mark.parametrize(
    ("kind", "exc"),
    [("connection", ProviderUnavailable), ("timeout", ProviderTimeout), ("http", ProviderError)],
)
def test_errors_and_timeouts_are_outcomes(kind: ErrorKind, exc: type[ProviderError]) -> None:
    fake = FakeProvider({"relentra.brief": [FakeReply.failure(kind)]})
    outcome = fake.complete(_req())
    assert outcome.content is None and outcome.error is not None and outcome.error.kind == kind
    assert outcome.usage == Usage(0, 0)
    with pytest.raises(exc):
        raise_for(outcome.error)


def test_reply_needs_exactly_one_of_content_and_error() -> None:
    with pytest.raises(ValueError):
        FakeReply()
    with pytest.raises(ValueError):
        FakeReply("x", error="timeout")


def test_two_fakes_with_the_same_calls_agree() -> None:
    script = {"relentra.brief": [FakeReply("a"), FakeReply.failure("timeout"), FakeReply("c")]}
    runs = []
    for _ in range(2):
        fake = FakeProvider(script)
        runs.append([fake.complete(_req(text=str(i))).as_json() for i in range(4)])
    assert runs[0] == runs[1]
