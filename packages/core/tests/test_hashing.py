"""hashing: digests, self-hashes, manifest hashes, the agent_trace chain and fraction()."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts.models import AgentTraceLine, Card, Verdict
from veyltrace_core import hashing
from veyltrace_core.errors import ChainBroken, ContractValidationError
from veyltrace_core.hashing import (
    GENESIS_HASH,
    chain_hash,
    fraction,
    is_sha256,
    manifest_hash,
    self_hash,
    self_hash_fields,
    sha256_bytes,
    sha256_file,
    sha256_json,
    sha256_text_lf,
    verify_chain,
    verify_self_hash,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples"


def _example(name: str) -> Any:
    return json.loads((EXAMPLES / f"{name}.example.json").read_bytes().decode("utf-8"))


# ----------------------------------------------------------------------------------------------
# Digests


def test_sha256_bytes_known_vectors() -> None:
    assert sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_json_hashes_canonical_bytes() -> None:
    assert sha256_json({"b": 1.0, "a": [1]}) == sha256_bytes(b'{"a":[1],"b":1.0}')


def test_is_sha256() -> None:
    assert is_sha256("a" * 64)
    assert not is_sha256("A" * 64)
    assert not is_sha256("a" * 63)
    assert not is_sha256("a" * 64 + "\n")
    assert not is_sha256(None)


@pytest.mark.parametrize("chunk", [hashing.FILE_CHUNK_BYTES, 7])
def test_sha256_file_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk: int) -> None:
    monkeypatch.setattr(hashing, "FILE_CHUNK_BYTES", chunk)
    data = bytes(range(256)) * 9000 + b"tail"  # > 2 MiB: several 1 MiB chunks plus a partial one
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_sha256_text_lf_ignores_crlf_only(tmp_path: Path) -> None:
    lf, crlf, cr = tmp_path / "lf.txt", tmp_path / "crlf.txt", tmp_path / "cr.txt"
    lf.write_bytes("a →\nb\n".encode())
    crlf.write_bytes("a →\r\nb\r\n".encode())
    cr.write_bytes("a →\rb\r".encode())
    assert sha256_text_lf(lf) == sha256_text_lf(crlf) == sha256_file(lf)
    assert sha256_text_lf(cr) != sha256_text_lf(lf)


# ----------------------------------------------------------------------------------------------
# Self-hashes (registry rule: verdict excludes verdict_hash and run_id; card excludes card_hash)


def test_self_hash_rules_come_from_the_registry() -> None:
    assert self_hash_fields("verdict") == ("verdict_hash", frozenset({"verdict_hash", "run_id"}))
    assert self_hash_fields("card") == ("card_hash", frozenset({"card_hash"}))
    with pytest.raises(KeyError):
        self_hash_fields("no_such_contract")
    with pytest.raises(ValueError, match="no self-hash rule"):
        self_hash_fields("slate")


@pytest.mark.parametrize(("contract", "field"), [("verdict", "verdict_hash"), ("card", "card_hash")])
def test_self_hash_matches_contract_examples(contract: str, field: str) -> None:
    example = _example(contract)
    assert self_hash(contract, example) == example[field]
    verify_self_hash(contract, example)


def test_self_hash_accepts_models() -> None:
    verdict = _example("verdict")
    card = _example("card")
    assert self_hash("verdict", Verdict.model_validate(verdict)) == verdict["verdict_hash"]
    assert self_hash("card", Card.model_validate(card)) == card["card_hash"]


def test_verdict_hash_ignores_run_id_but_not_content() -> None:
    verdict = _example("verdict")
    replayed = {**verdict, "run_id": "0123456789abcdef"}
    assert self_hash("verdict", replayed) == verdict["verdict_hash"]  # replay keeps the hash (D-4)
    changed = {**verdict, "case_id": "000000000000"}
    assert self_hash("verdict", changed) != verdict["verdict_hash"]
    with pytest.raises(ContractValidationError, match="verdict_hash"):
        verify_self_hash("verdict", changed)


# ----------------------------------------------------------------------------------------------
# Manifest hashes


def test_manifest_hash_definition_and_order_independence() -> None:
    a, b = "a" * 64, "b" * 64
    expected = sha256_json([{"name": "cassette/x.json", "sha256": b}, {"name": "relentra/p.md", "sha256": a}])
    assert manifest_hash([("relentra/p.md", a), ("cassette/x.json", b)]) == expected
    assert manifest_hash(reversed([("relentra/p.md", a), ("cassette/x.json", b)])) == expected
    assert manifest_hash([]) == sha256_json([])


@pytest.mark.parametrize("name", ["", "a\\b", "/abs", "C:/x", "a/../b", ".."])
def test_manifest_hash_rejects_non_posix_relative_names(name: str) -> None:
    with pytest.raises(ValueError):
        manifest_hash([(name, "a" * 64)])


def test_manifest_hash_rejects_duplicates_and_bad_digests() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        manifest_hash([("x", "a" * 64), ("x", "a" * 64)])
    with pytest.raises(ValueError, match="sha256"):
        manifest_hash([("x", "A" * 64)])


# ----------------------------------------------------------------------------------------------
# agent_trace hash chain (03 §9.2)


def _line(seq: int, prev: str, state: str) -> dict[str, Any]:
    line: dict[str, Any] = {
        "seq": seq,
        "type": "state",
        "prev_hash": prev,
        "line_hash": "",
        "request_sha256": None,
        "response_sha256": None,
        "tool": None,
        "args": None,
        "result_sha256": None,
        "summary": None,
        "state": state,
        "detail": None,
    }
    line["line_hash"] = chain_hash(prev, line)
    return line


def _chain(states: list[str]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    prev = GENESIS_HASH
    for seq, state in enumerate(states):
        line = _line(seq, prev, state)
        lines.append(line)
        prev = line["line_hash"]
    return lines


def test_chain_hash_definition() -> None:
    line = _line(0, GENESIS_HASH, "start")
    body = {k: v for k, v in line.items() if k != "line_hash"}
    expected = hashlib.sha256(GENESIS_HASH.encode("ascii") + json_bytes(body)).hexdigest()
    assert line["line_hash"] == expected
    # line_hash itself is excluded, so the stored value never feeds back into the hash
    assert chain_hash(GENESIS_HASH, {**line, "line_hash": "f" * 64}) == expected


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_chain_hash_matches_contract_example_lines() -> None:
    for line in _example("agent_trace"):
        assert chain_hash(line["prev_hash"], line) == line["line_hash"]


def test_verify_chain_example_fragment_and_models() -> None:
    lines = _example("agent_trace")
    head = verify_chain(lines, start_seq=lines[0]["seq"], start_hash=lines[0]["prev_hash"])
    assert head == lines[-1]["line_hash"]
    models = [AgentTraceLine.model_validate(line) for line in lines]
    assert verify_chain(models, start_seq=lines[0]["seq"], start_hash=lines[0]["prev_hash"]) == head
    with pytest.raises(ChainBroken) as info:
        verify_chain(lines)  # not a whole trace: seq starts at 2 and prev_hash is not genesis
    assert info.value.seq == 0


def test_verify_chain_whole_trace() -> None:
    lines = _chain(["start", "cards_built", "prompt_built", "done"])
    assert verify_chain(lines) == lines[-1]["line_hash"]
    assert verify_chain([]) is None


@pytest.mark.parametrize(
    ("index", "field", "value"),
    [
        (2, "state", "failed"),
        (1, "prev_hash", "f" * 64),
        (3, "line_hash", "f" * 64),
        (2, "seq", 7),
        (0, "seq", False),
    ],
)
def test_verify_chain_reports_first_broken_seq(index: int, field: str, value: Any) -> None:
    lines = _chain(["start", "cards_built", "prompt_built", "done"])
    lines[index] = {**lines[index], field: value}
    with pytest.raises(ChainBroken) as info:
        verify_chain(lines)
    assert info.value.seq == index


def test_verify_chain_detects_reordering_and_dropping() -> None:
    lines = _chain(["start", "cards_built", "prompt_built", "done"])
    with pytest.raises(ChainBroken) as info:
        verify_chain([lines[0], lines[2], lines[1], lines[3]])
    assert info.value.seq == 1
    with pytest.raises(ChainBroken) as info:
        verify_chain(lines[1:])
    assert info.value.seq == 0


_states = st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=12)


@given(_states, st.data())
def test_chain_property_any_mutation_breaks_at_its_seq(states: list[str], data: st.DataObject) -> None:
    lines = _chain(states)
    assert verify_chain(lines) == lines[-1]["line_hash"]
    index = data.draw(st.integers(min_value=0, max_value=len(lines) - 1))
    replacement = data.draw(st.text(max_size=12).filter(lambda s: s != states[index]))
    lines[index] = {**lines[index], "state": replacement}
    with pytest.raises(ChainBroken) as info:
        verify_chain(lines)
    assert info.value.seq == index


@given(_states)
def test_chain_property_head_is_deterministic(states: list[str]) -> None:
    assert verify_chain(_chain(states)) == verify_chain(_chain(list(states)))


# ----------------------------------------------------------------------------------------------
# fraction (hash-keyed selection, D-18)


def test_fraction_definition() -> None:
    digest = hashlib.sha256(b"59e0d31bcc42\x1ftrace-1").hexdigest()
    assert fraction("59e0d31bcc42", "trace-1") == int(digest[:16], 16) / 2**64
    assert fraction("59e0d31bcc42", "trace-1") == 0.5193699082261393  # pinned


def test_fraction_validates_parts() -> None:
    with pytest.raises(ValueError, match="at least one"):
        fraction()
    with pytest.raises(ValueError, match="separator"):
        fraction("a\x1fb")


def test_fraction_is_strictly_below_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hashing, "sha256_bytes", lambda _data: "f" * 64)
    assert fraction("x") < 1.0


@given(
    st.lists(
        st.text(alphabet=st.characters(exclude_characters="\x1f", exclude_categories=["Cs"]), max_size=10),
        min_size=1,
        max_size=4,
    )
)
def test_fraction_range(parts: list[str]) -> None:
    value = fraction(*parts)
    assert 0.0 <= value < 1.0
    assert fraction(*parts) == value


def test_fraction_rejects_lone_surrogate() -> None:
    # Regression: hypothesis found "\ud800", which raised UnicodeEncodeError instead of ValueError.
    with pytest.raises(ValueError, match="surrogate"):
        fraction("\ud800")
