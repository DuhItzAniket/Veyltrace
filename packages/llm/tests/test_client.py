"""LLMClient in its three AI modes over the cassette (08 §5.2, §7 `veyltrace_llm` row; #18 acceptance).

A "session" is a fixed sequence of calls. Recording it twice gives byte-identical cassette files;
replaying it from the cassette, with no provider and no network, gives byte-identical outcomes.
"""

from __future__ import annotations

import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import CassetteMiss as CoreCassetteMiss
from veyltrace_core.testing import repo_root
from veyltrace_llm.cassette import INDEX_FILE, CassetteMiss
from veyltrace_llm.client import LLMClient
from veyltrace_llm.errors import AIDisabled, ProviderError, ProviderTimeout
from veyltrace_llm.fake import FakeProvider, FakeReply
from veyltrace_llm.request import Message
from veyltrace_llm.settings import LLMSettings, settings_from

PARAMS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "seed": 11, "max_tokens": 64}
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
SCRIPT = {
    "relentra.brief": [FakeReply.json({"ok": True}), FakeReply("not json"), FakeReply.json({"ok": False})],
    "causivra.narrate": [FakeReply.failure("timeout"), FakeReply.json({"ok": True})],
}


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in cast(Mapping[str, Any], value).items()}
    return value


def _settings(**changes: Any) -> LLMSettings:
    section = _thaw(load_section_file("llm", config_dir=repo_root() / "config"))
    section.update(changes)
    return settings_from(section, env={})


def _session(client: LLMClient) -> list[bytes]:
    """The fixed call sequence; each outcome rendered as canonical bytes."""
    out: list[bytes] = []
    calls = [
        ("relentra.brief", "a"),
        ("relentra.brief", "a"),
        ("causivra.narrate", "b"),
        ("relentra.brief", "c"),
    ]
    calls.append(("causivra.narrate", "b"))
    for purpose, text in calls:
        try:
            reply = client.call_json(purpose, [Message("user", text)], SCHEMA, PARAMS)
            out.append(
                canonical_json([reply.key, reply.completion.as_json(), reply.value, reply.parse_error])
            )
        except ProviderTimeout as exc:
            assert exc.completion is not None
            out.append(canonical_json(["timeout", exc.completion.as_json()]))
    return out


def _files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("replay opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_replay_of_a_recorded_session_is_byte_identical(tmp_path: Path, no_network: None) -> None:
    recorded = _session(
        LLMClient(_settings(), "record", tmp_path / "cassette", provider=FakeProvider(SCRIPT))
    )
    replayed = _session(LLMClient(_settings(), "replay", tmp_path / "cassette"))
    assert replayed == recorded


def test_recording_twice_gives_identical_cassette_bytes(tmp_path: Path) -> None:
    for name in ("a", "b"):
        _session(LLMClient(_settings(), "record", tmp_path / name, provider=FakeProvider(SCRIPT)))
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


def test_unrecorded_key_and_occurrence_miss(tmp_path: Path, no_network: None) -> None:
    _session(LLMClient(_settings(), "record", tmp_path, provider=FakeProvider(SCRIPT)))
    replay = LLMClient(_settings(), "replay", tmp_path)
    with pytest.raises(CassetteMiss) as miss:
        replay.call_json("relentra.brief", [Message("user", "never asked")], SCHEMA, PARAMS)
    assert isinstance(miss.value, CoreCassetteMiss)  # core maps it to exit 3 / replay exit 2
    replay.call_json("relentra.brief", [Message("user", "c")], SCHEMA, PARAMS)
    with pytest.raises(CassetteMiss, match="occurrence 2"):
        replay.call_json("relentra.brief", [Message("user", "c")], SCHEMA, PARAMS)


def test_errors_replay_as_the_same_errors(tmp_path: Path) -> None:
    record = LLMClient(_settings(), "record", tmp_path, provider=FakeProvider(SCRIPT))
    with pytest.raises(ProviderTimeout) as recorded:
        record.call_json("causivra.narrate", [Message("user", "b")], SCHEMA, PARAMS)
    replay = LLMClient(_settings(), "replay", tmp_path)
    with pytest.raises(ProviderTimeout) as replayed:
        replay.call_json("causivra.narrate", [Message("user", "b")], SCHEMA, PARAMS)
    assert recorded.value.completion == replayed.value.completion


def test_key_does_not_depend_on_runtime_settings(tmp_path: Path, no_network: None) -> None:
    _session(LLMClient(_settings(), "record", tmp_path, provider=FakeProvider(SCRIPT)))
    other = _settings(base_url="http://localhost:8080", provider="llamacpp")
    assert _session(LLMClient(other, "replay", tmp_path))  # same keys, no miss


def test_crlf_prompt_replays_an_lf_recording(tmp_path: Path) -> None:
    record = LLMClient(
        _settings(), "record", tmp_path, provider=FakeProvider(default=FakeReply.json({"ok": True}))
    )
    record.call_json("relentra.brief", [Message("user", "line1\nline2")], SCHEMA, PARAMS)
    replay = LLMClient(_settings(), "replay", tmp_path)
    assert replay.call_json("relentra.brief", [Message("user", "line1\r\nline2")], SCHEMA, PARAMS).value == {
        "ok": True
    }


def test_off_refuses_every_call(tmp_path: Path) -> None:
    with pytest.raises(AIDisabled):
        LLMClient(_settings(), "off").call_json("relentra.brief", [Message("user", "x")], SCHEMA, PARAMS)
    assert not any(tmp_path.iterdir())


def test_invalid_json_is_returned_not_raised(tmp_path: Path) -> None:
    client = LLMClient(_settings(), "record", tmp_path, provider=FakeProvider(default=FakeReply("{oops")))
    reply = client.call_json("relentra.brief", [Message("user", "x")], SCHEMA, PARAMS)
    assert reply.value is None and reply.parse_error is not None


def test_unscripted_fake_from_config_is_a_recorded_error(tmp_path: Path) -> None:
    client = LLMClient(_settings(provider="fake"), "record", tmp_path)
    with pytest.raises(ProviderError) as exc:
        client.call_json("relentra.brief", [Message("user", "x")], SCHEMA, PARAMS)
    assert exc.value.error.kind == "unscripted"
    assert (tmp_path / INDEX_FILE).is_file()
