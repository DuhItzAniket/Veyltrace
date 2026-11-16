"""The cassette files themselves: layout, determinism, strict lookup, integrity (08 §5.2; rules 3–5)."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import CassetteMiss as CoreCassetteMiss
from veyltrace_llm.cassette import INDEX_FILE, Cassette, CassetteMiss, CassetteNotEmpty
from veyltrace_llm.fake import FakeReply
from veyltrace_llm.request import Completion, LLMRequest, Message, ModelId, Runtime, Usage

PARAMS = {
    "temperature": 0.7,
    "seed": 3,
    "max_tokens": 16,
    "top_p": None,
    "top_k": None,
    "presence_penalty": None,
    "thinking": None,
}
AUDIT = {"provider": "ollama", "base_url": "http://127.0.0.1:11434", "timeout_s": 240.0}


def _req(text: str, purpose: str = "relentra.brief") -> LLMRequest:
    return LLMRequest(purpose, ModelId("m"), (Message("user", text),), PARAMS, {"type": "object"})


CALLS = [
    (_req("a"), FakeReply.json({"n": 1}).completion()),
    (_req("a"), FakeReply.failure("timeout").completion()),
    (_req("b", "causivra.narrate"), FakeReply("plain").completion()),
]


def _record(directory: Path) -> Cassette:
    cassette = Cassette(directory, "record", recorded_with=AUDIT)
    for request, completion in CALLS:
        cassette.record(request, completion)
    return cassette


def _bytes(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_recording_twice_gives_identical_bytes(tmp_path: Path) -> None:
    _record(tmp_path / "x")
    _record(tmp_path / "y")
    assert _bytes(tmp_path / "x") == _bytes(tmp_path / "y")


def test_layout_index_and_entries(tmp_path: Path) -> None:
    _record(tmp_path)
    a, b = _req("a").key, _req("b", "causivra.narrate").key
    assert sorted(_bytes(tmp_path)) == sorted([f"{a}.json", f"{b}.json", INDEX_FILE])
    index = json.loads((tmp_path / INDEX_FILE).read_bytes())
    assert index == sorted(
        [{"key": a, "purpose": "relentra.brief", "n": 2}, {"key": b, "purpose": "causivra.narrate", "n": 1}],
        key=lambda e: e["key"],
    )
    entry = json.loads((tmp_path / f"{a}.json").read_bytes())
    assert entry["key"] == a and entry["request"] == _req("a").canonical() and entry["recorded_with"] == AUDIT
    assert [r["error"] for r in entry["responses"]] == [None, {"kind": "timeout", "message": "fake timeout"}]
    assert (tmp_path / f"{a}.json").read_bytes() == canonical_json(entry)  # canonical, no timestamps


def test_replay_returns_occurrences_in_order(tmp_path: Path) -> None:
    _record(tmp_path)
    replay = Cassette(tmp_path, "replay")
    assert [replay.lookup(r) for r, _ in CALLS] == [c for _, c in CALLS]


def test_a_recorded_completion_replays_unchanged(tmp_path: Path) -> None:
    # perf_counter latencies have more than 9 decimals; record and replay must still agree (08 §5.1).
    measured = Completion("x", Usage(1, 2), 1234.5678901234567, Runtime("ollama", "0.12.0"))
    Cassette(tmp_path, "record", recorded_with=AUDIT).record(_req("lat"), measured)
    assert Cassette(tmp_path, "replay").lookup(_req("lat")) == measured


def test_strict_misses(tmp_path: Path) -> None:
    _record(tmp_path)
    replay = Cassette(tmp_path, "replay")
    with pytest.raises(CassetteMiss) as unknown:
        replay.lookup(_req("never"))
    assert isinstance(unknown.value, CoreCassetteMiss) and unknown.value.key == _req("never").key
    replay.lookup(_req("b", "causivra.narrate"))
    with pytest.raises(CassetteMiss, match="occurrence 2"):
        replay.lookup(_req("b", "causivra.narrate"))


def test_missing_directory_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(CassetteMiss):
        Cassette(tmp_path / "absent", "replay").lookup(_req("a"))


@pytest.mark.parametrize("damage", ["edit_request", "not_json", "bad_response"])
def test_damaged_entries_are_misses(tmp_path: Path, damage: str) -> None:
    _record(tmp_path)
    path = tmp_path / f"{_req('a').key}.json"
    raw = json.loads(path.read_bytes())
    if damage == "edit_request":
        raw["request"]["messages"][0]["content"] = "edited"
        path.write_bytes(canonical_json(raw))
    elif damage == "not_json":
        path.write_bytes(b"{")
    else:
        raw["responses"][0] = {"content": "x"}
        path.write_bytes(canonical_json(raw))
    with pytest.raises(CassetteMiss):
        Cassette(tmp_path, "replay").lookup(_req("a"))


def test_record_refuses_a_non_empty_directory_unless_forced(tmp_path: Path) -> None:
    _record(tmp_path)
    with pytest.raises(CassetteNotEmpty, match="--force-record"):
        Cassette(tmp_path, "record")
    forced = Cassette(tmp_path, "record", force_record=True)
    forced.record(*CALLS[2])
    assert len(json.loads((tmp_path / INDEX_FILE).read_bytes())) == 1


def test_force_refuses_foreign_subdirectories(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    with pytest.raises(CassetteNotEmpty):
        Cassette(tmp_path, "record", force_record=True)


def test_a_refused_force_record_deletes_nothing(tmp_path: Path) -> None:
    _record(tmp_path)
    (tmp_path / "zz-nested").mkdir()  # sorts after every cassette file
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(CassetteNotEmpty, match="zz-nested"):
        Cassette(tmp_path, "record", force_record=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_mode_guards_and_pickling(tmp_path: Path) -> None:
    record = Cassette(tmp_path / "r", "record")
    with pytest.raises(ValueError):
        record.lookup(_req("a"))
    with pytest.raises(ValueError):
        Cassette(tmp_path, "replay").record(*CALLS[0])
    miss = pickle.loads(pickle.dumps(CassetteMiss("k" * 64, "why")))
    assert (miss.key, miss.detail) == ("k" * 64, "why")
