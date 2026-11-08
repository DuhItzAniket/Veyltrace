"""SHA-256 helpers: artefact hashes, self-hashes, manifest hashes and the agent_trace hash chain.

All hashes are lowercase 64-hex SHA-256 without a prefix (03 §1). JSON values are always hashed
through canonical_json, never through ad-hoc `json.dumps`, so a value has exactly one hash.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.canonical import JSONLike, canonical_json
from veyltrace_core.errors import ChainBroken, ContractValidationError

__all__ = [
    "FILE_CHUNK_BYTES",
    "FRACTION_SEPARATOR",
    "GENESIS_HASH",
    "chain_hash",
    "fraction",
    "is_sha256",
    "manifest_hash",
    "self_hash",
    "self_hash_fields",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
    "sha256_text_lf",
    "verify_chain",
    "verify_self_hash",
]

#: Read size for streamed file hashing (core_api_spec §1: 1 MiB chunks).
FILE_CHUNK_BYTES = 1 << 20
#: prev_hash of the first agent_trace line (03 §9.2).
GENESIS_HASH = "0" * 64
#: Joins the parts of a hash-keyed selection; ASCII unit separator, which never occurs in ids.
FRACTION_SEPARATOR = "\x1f"
# fraction() maps the first 16 hex (64 bits) of a hash onto [0, 1) (core_api_spec §1).
_FRACTION_HEX = 16
_FRACTION_DENOMINATOR = 2**64
# The largest float below 1.0: n / 2**64 rounds up to exactly 1.0 for the top 2**10 values of n.
_FRACTION_MAX = math.nextafter(1.0, 0.0)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def is_sha256(value: object) -> bool:
    """True if `value` is a lowercase 64-hex SHA-256 string (03 §1 Hashes)."""
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: str, what: str) -> None:
    if not is_sha256(value):
        msg = f"{what} must be a lowercase 64-hex sha256, got {value!r}"
        raise ValueError(msg)


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase 64-hex SHA-256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: JSONLike) -> str:
    """Return the SHA-256 of canonical_json(obj)."""
    return sha256_bytes(canonical_json(obj))


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file's bytes, read in FILE_CHUNK_BYTES chunks so large Parquet files
    never sit in memory whole."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(FILE_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text_lf(path: Path) -> str:
    """Return the SHA-256 of a text file after CRLF -> LF.

    Prompts, briefs and uv.lock are hashed this way so that a CRLF checkout on Windows hashes the
    same as LF on Linux (08 §3.5). Lone CR is left alone.
    """
    return sha256_bytes(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def _as_mapping(obj: Mapping[str, Any] | BaseModel) -> Mapping[str, Any]:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json", by_alias=True)
    return obj


def self_hash_fields(contract: str) -> tuple[str, frozenset[str]]:
    """Return (hash field, every excluded field incl. the hash field) for a self-hashed contract.

    The rule comes from the generated registry (x-veyltrace.self_hash): verdict excludes
    verdict_hash and run_id, card excludes card_hash (02 §6.9; 03 §10, §11.1).
    """
    info = CONTRACTS.get(contract)
    if info is None:
        msg = f"unknown contract {contract!r}"
        raise KeyError(msg)
    if info.self_hash is None:
        msg = f"contract {contract!r} has no self-hash rule"
        raise ValueError(msg)
    return info.self_hash.field, frozenset((info.self_hash.field, *info.self_hash.exclude))


def self_hash(contract: str, obj: Mapping[str, Any] | BaseModel) -> str:
    """Return the self-hash of a contract object: sha256_json of the object without the hash field
    and the contract's excluded fields (verdict_hash, card_hash)."""
    _, excluded = self_hash_fields(contract)
    data = _as_mapping(obj)
    return sha256_json({k: v for k, v in data.items() if k not in excluded})


def verify_self_hash(contract: str, obj: Mapping[str, Any] | BaseModel) -> None:
    """Raise ContractValidationError unless the object's hash field equals its self-hash."""
    field, _ = self_hash_fields(contract)
    data = _as_mapping(obj)
    stored = data.get(field)
    expected = self_hash(contract, data)
    if stored != expected:
        raise ContractValidationError(contract, f"{field} is {stored!r}, expected {expected}")


def manifest_hash(entries: Iterable[tuple[str, str]]) -> str:
    """Return one hash over a set of named files: sha256_json of [{"name", "sha256"}] sorted by name.

    Used for cassette_sha256, prompt_sha256 and schema_sha256 (08 §5.2; 10 §3.9). Names are POSIX
    relative paths, so the hash is the same on every OS; duplicates are rejected as ambiguous.
    """
    items: dict[str, str] = {}
    for name, digest in entries:
        if not name or "\\" in name or name.startswith("/") or ":" in name.split("/", 1)[0]:
            msg = f"manifest entry names are relative POSIX paths, got {name!r}"
            raise ValueError(msg)
        if ".." in name.split("/"):
            msg = f"manifest entry names may not contain '..', got {name!r}"
            raise ValueError(msg)
        _require_sha256(digest, f"sha256 of manifest entry {name!r}")
        if name in items:
            msg = f"duplicate manifest entry {name!r}"
            raise ValueError(msg)
        items[name] = digest
    return sha256_json([{"name": name, "sha256": items[name]} for name in sorted(items)])


def chain_hash(prev_hash: str, line: Mapping[str, Any] | BaseModel) -> str:
    """Return an agent_trace line's line_hash: SHA-256 over the ASCII hex of prev_hash followed by
    canonical_json(line without line_hash) (03 §9.2)."""
    _require_sha256(prev_hash, "prev_hash")
    data = _as_mapping(line)
    body = {k: v for k, v in data.items() if k != "line_hash"}
    return sha256_bytes(prev_hash.encode("ascii") + canonical_json(body))


def verify_chain(
    lines: Sequence[Mapping[str, Any] | BaseModel],
    *,
    start_seq: int = 0,
    start_hash: str = GENESIS_HASH,
) -> str | None:
    """Verify an agent_trace hash chain and return its head (the last line_hash), or None if empty.

    Each line must have `seq` = its position (from `start_seq`), `prev_hash` = the previous line's
    hash (`start_hash` for the first) and `line_hash` = chain_hash(prev_hash, line). The defaults
    verify a whole trace; `start_seq`/`start_hash` verify a fragment. Raises ChainBroken(seq) at
    the first bad line (10-causivra §3: the chain is verified before the receipt uses it).
    """
    _require_sha256(start_hash, "start_hash")
    prev = start_hash
    for offset, raw in enumerate(lines):
        seq = start_seq + offset
        line = _as_mapping(raw)
        got_seq = line.get("seq")
        if isinstance(got_seq, bool) or got_seq != seq:
            raise ChainBroken(seq, f"seq is {got_seq!r}")
        if line.get("prev_hash") != prev:
            raise ChainBroken(seq, "prev_hash does not match the previous line_hash")
        expected = chain_hash(prev, line)
        if line.get("line_hash") != expected:
            raise ChainBroken(seq, "line_hash does not match the line content")
        prev = expected
    return prev if lines else None


def fraction(*parts: str) -> float:
    """Map `parts` to a stable pseudo-uniform number in [0, 1): the shared hash-keyed selection.

    Signalyth's keep_fraction uses fraction(case_id, trace_id) and the CP cap uses the same rule
    (02 §3.3; core_api_spec D-18): keep an item iff fraction(...) < share. The parts are joined
    with FRACTION_SEPARATOR, so a part containing it is rejected (it would make keys ambiguous).
    """
    if not parts:
        msg = "fraction() needs at least one part"
        raise ValueError(msg)
    for part in parts:
        if FRACTION_SEPARATOR in part:
            msg = f"fraction() parts may not contain the separator \\x1f, got {part!r}"
            raise ValueError(msg)
    try:
        key = FRACTION_SEPARATOR.join(parts).encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogates have no UTF-8 form, so no stable key
        msg = f"fraction() parts must be valid Unicode text (no lone surrogates): {exc}"
        raise ValueError(msg) from exc
    digest = sha256_bytes(key)
    return min(int(digest[:_FRACTION_HEX], 16) / _FRACTION_DENOMINATOR, _FRACTION_MAX)
