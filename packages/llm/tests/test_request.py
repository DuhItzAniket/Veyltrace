"""The canonical request and its cassette key (08 §5.2; package rule 3)."""

from __future__ import annotations

import json
from typing import Any, cast, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json
from veyltrace_core.hashing import sha256_bytes
from veyltrace_llm.request import (
    NULLABLE_PARAMS,
    PARAM_NAMES,
    CallError,
    Completion,
    LLMRequest,
    Message,
    ModelId,
    Runtime,
    Usage,
)

PARAMS: dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 20,
    "seed": 123,
    "max_tokens": 64,
    "presence_penalty": None,
    "thinking": None,
}
SCHEMA: dict[str, Any] = {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}


def _request(content: str = "hello", **kw: Any) -> LLMRequest:
    fields: dict[str, Any] = {
        "purpose": "relentra.brief",
        "model": ModelId("qwen3.5:9b"),
        "messages": (Message("system", "rules"), Message("user", content)),
        "params": PARAMS,
        "schema": SCHEMA,
    }
    fields.update(kw)
    return LLMRequest(**fields)


def test_key_is_sha256_of_the_canonical_request() -> None:
    req = _request()
    assert req.canonical() == {
        "v": 1,
        "purpose": "relentra.brief",
        "model": {"name": "qwen3.5:9b", "gguf_sha256": None},
        "messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "hello"}],
        "schema": SCHEMA,
        "params": PARAMS,
    }
    assert req.key == sha256_bytes(canonical_json(req.canonical()))


def test_crlf_is_normalised_before_hashing() -> None:
    assert _request("a\r\nb").key == _request("a\nb").key
    assert _request("a\r\nb").messages[1].content == "a\nb"


def test_key_depends_on_what_the_model_sees() -> None:
    base = _request().key
    assert _request("other").key != base
    assert _request(purpose="causivra.narrate").key != base
    assert _request(schema=None).key != base
    assert _request(params={**PARAMS, "seed": 124}).key != base
    assert _request(model=ModelId("qwen3.5:9b", "a" * 64)).key != base


def test_schema_and_params_are_private_copies() -> None:
    schema = {"type": "object"}
    req = _request(schema=schema)
    before = req.key
    schema["type"] = "array"
    assert req.key == before


@pytest.mark.parametrize(
    "kw",
    [
        {"purpose": "brief"},
        {"purpose": "Relentra.Brief"},
        {"messages": ()},
        {"params": {"temperature": 0.7, "seed": 1}},
        {"params": {**PARAMS, "stream": True}},
        {"params": {**PARAMS, "seed": 2**31 - 1}},
        {"params": {**PARAMS, "max_tokens": True}},
        {"params": {**PARAMS, "temperature": float("nan")}},
        {"params": {**PARAMS, "thinking": 0}},
        *({"params": {k: v for k, v in PARAMS.items() if k != name}} for name in sorted(PARAM_NAMES)),
        *({"params": {**PARAMS, name: None}} for name in sorted(PARAM_NAMES - NULLABLE_PARAMS)),
    ],
)
def test_invalid_requests_are_rejected(kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _request(**kw)


def test_params_follow_03_sampler_params() -> None:
    # 03 §9.1: `?` = required and nullable. A contract-valid params object builds a request, the
    # request's params validate as SamplerParams, and null is part of the key, not an omission.
    contract = models.SamplerParams.model_validate({**PARAMS, "top_k": None, "top_p": None})
    req = _request(params=contract.model_dump())
    assert models.SamplerParams(**req.params) == contract
    fields = models.SamplerParams.model_fields
    assert set(fields) == PARAM_NAMES
    assert {n for n, f in fields.items() if type(None) in get_args(f.annotation)} == NULLABLE_PARAMS
    assert _request(params={**PARAMS, "thinking": False}).key != _request().key


def test_model_and_message_validation() -> None:
    with pytest.raises(ValueError):
        ModelId("")
    with pytest.raises(ValueError):
        ModelId("m", "ABC")
    with pytest.raises(ValueError):
        Message(cast(Any, "tool"), "x")


@given(st.text(), st.text())
def test_key_is_a_pure_function_of_content(a: str, b: str) -> None:
    assert (_request(a).key == _request(b).key) == (a.replace("\r\n", "\n") == b.replace("\r\n", "\n"))


def test_completion_shapes() -> None:
    ok = Completion("{}", Usage(3, 4), 12, Runtime("ollama", "0.12.0"))
    assert ok.ok and ok.latency_ms == 12.0
    assert ok.as_json() == {
        "content": "{}",
        "error": None,
        "usage": {"tokens_in": 3, "tokens_out": 4},
        "latency_ms": 12.0,
        "runtime": {"provider": "ollama", "version": "0.12.0"},
    }
    assert ok.response_sha256 == sha256_bytes(b"{}")
    bad = Completion(None, Usage(0, 0), 5.0, Runtime("fake"), CallError("timeout", "slow"))
    assert not bad.ok
    assert bad.response_sha256 == sha256_bytes(canonical_json({"kind": "timeout", "message": "slow"}))
    with pytest.raises(ValueError):
        Completion("x", Usage(0, 0), 1.0, Runtime("fake"), CallError("timeout", "both"))


@given(st.floats(min_value=0, max_value=1e9, allow_nan=False))
def test_latency_is_stored_as_canonical_json_writes_it(ms: float) -> None:
    # Record mode returns this object; replay reads canonical_json of it back (08 §5.1).
    latency = Completion("x", Usage(1, 1), ms, Runtime("fake")).latency_ms
    assert latency == json.loads(canonical_json({"v": ms}))["v"]
    assert Completion("x", Usage(1, 1), 0.1234567891234, Runtime("fake")).latency_ms == 0.123456789
    with pytest.raises(ValueError):
        Completion("x", Usage(0, 0), -1.0, Runtime("fake"))
    with pytest.raises(ValueError):
        Runtime("vllm")
    with pytest.raises(ValueError):
        Usage(-1, 0)
