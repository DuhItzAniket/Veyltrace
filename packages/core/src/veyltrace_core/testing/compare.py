"""Golden comparison by canonical content, never by file bytes.

Why: fixtures are refreshed on the team's Windows laptops and compared on Linux CI, and Parquet
bytes depend on the writer build, so a byte comparison of Parquet fails for equal data (core_api_spec
D-16; critic gap "01 §7 / 06 §7 contradict D-16"). `assert_golden` is therefore the only golden
comparator. It reduces a value to "content lines":

- JSON contracts: the canonical object (io.prepare applied to raw mappings, so stamping and x-sort
  ordering match the writer), rendered with sorted keys and floats rounded to 9 decimals;
- JSONL contracts: one canonical line per record, in file order (agent_trace order is the chain);
- Parquet contracts: the Arrow schema (names, types, nullability), the `veyltrace.schema` metadata
  when the value carries it, then one canonical row per line, sorted by the contract key and then
  by the whole row, with floats rounded to 9 decimals.

Equal content lines means equal golden; the same lines hash to `content_sha256`, which the
upstream-lock staleness check uses.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import pyarrow as pa
from pydantic import BaseModel

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.canonical import JSONValue, canonical_json_str, normalize
from veyltrace_core.hashing import sha256_bytes
from veyltrace_core.testing.fixtures import golden

__all__ = ["MAX_DIFF_LINES", "SCHEMA_METADATA_KEY", "assert_golden", "content_lines", "content_sha256"]

#: Changed lines shown on a mismatch (core_api_spec §13: "first 50 differing rows").
MAX_DIFF_LINES: Final = 50
#: Parquet key-value metadata naming the contract and version (03 §1).
SCHEMA_METADATA_KEY: Final = b"veyltrace.schema"
_JSON_INDENT: Final = 1


def _pretty(value: JSONValue) -> list[str]:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=_JSON_INDENT)
    return text.split("\n")


def _as_json_model(contract: str, value: object) -> JSONValue:
    if isinstance(value, Path):
        value = io.read_path_unredacted(contract, value)
    if isinstance(value, Mapping):
        value = io.prepare(contract, cast("Mapping[str, Any]", value))
    if not isinstance(value, BaseModel):
        msg = f"{contract}: expected a model, a mapping or a path, got {type(value).__name__}"
        raise TypeError(msg)
    return normalize(value)


def _jsonl_lines(contract: str, value: object) -> list[str]:
    if isinstance(value, Path):
        value = io.read_path_unredacted(contract, value)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"{contract}: expected a list of lines or a path, got {type(value).__name__}"
        raise TypeError(msg)
    return [canonical_json_str(normalize(line)) for line in cast("Sequence[object]", value)]


def _type_str(dtype: pa.DataType) -> str:
    """Arrow type text without list child names: Parquet round trips rename a list's child from
    "item" to "element", which is not a content difference."""
    if pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
        child: pa.Field[Any] = dtype.value_field
        nullability = "" if child.nullable else " not null"
        return f"list<{_type_str(child.type)}{nullability}>"
    return str(dtype)


def _schema_lines(table: pa.Table) -> list[str]:
    fields: list[pa.Field[Any]] = list(table.schema)
    lines = [f"field {f.name}: {_type_str(f.type)} {'null' if f.nullable else 'not null'}" for f in fields]
    metadata = table.schema.metadata or {}
    if SCHEMA_METADATA_KEY in metadata:
        lines.append(f"metadata {SCHEMA_METADATA_KEY.decode()}: {metadata[SCHEMA_METADATA_KEY].decode()}")
    return lines


def _table_lines(contract: str, value: object) -> list[str]:
    if isinstance(value, Path):
        value = io.read_path_unredacted(contract, value)
    if not isinstance(value, pa.Table):
        msg = f"{contract}: expected a pyarrow Table or a path, got {type(value).__name__}"
        raise TypeError(msg)
    key = CONTRACTS[contract].key
    rows: list[tuple[str, str]] = []
    for row in value.to_pylist():
        canonical = canonical_json_str(normalize(row))
        rows.append((canonical_json_str(normalize([row.get(k) for k in key])), canonical))
    rows.sort()
    return [*_schema_lines(value), *(f"row {line}" for _, line in rows)]


def content_lines(contract: str, value: object) -> list[str]:
    """The canonical content of `value` (a model, mapping, table, line list or file path)."""
    kind = CONTRACTS[contract].kind
    if kind == "json":
        return _pretty(_as_json_model(contract, value))
    if kind == "jsonl":
        return _jsonl_lines(contract, value)
    if kind == "parquet":
        return _table_lines(contract, value)
    msg = f"contract {contract!r} of kind {kind!r} has no golden comparison"
    raise ValueError(msg)


def content_sha256(contract: str, value: object) -> str:
    """SHA-256 of the canonical content lines (LF-joined): equal for equal data on any OS."""
    return sha256_bytes("\n".join(content_lines(contract, value)).encode("utf-8"))


def _strip_metadata_if_absent(actual: list[str], expected: list[str]) -> list[str]:
    """Drop the expected metadata line when the actual table carries none (built in memory)."""
    prefix = f"metadata {SCHEMA_METADATA_KEY.decode()}:"
    if any(line.startswith(prefix) for line in actual):
        return expected
    return [line for line in expected if not line.startswith(prefix)]


def _diff(expected: list[str], actual: list[str]) -> str:
    out: list[str] = []
    changed = 0
    for line in difflib.unified_diff(expected, actual, "golden", "actual", lineterm="", n=1):
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            changed += 1
            if changed > MAX_DIFF_LINES:
                out.append(f"... (diff truncated after {MAX_DIFF_LINES} changed lines)")
                break
        out.append(line)
    return "\n".join(out)


def assert_golden(
    actual: object, contract: str, case: str, *, variant: str | None = None, phase: str | None = None
) -> None:
    """Assert `actual` equals the golden fixture of `contract` for `case` in canonical content.

    `actual` may be what io.read returns, a raw mapping (JSON contracts; validated and ordered
    like the writer would), an in-memory pyarrow Table, or a path to a written file. On mismatch
    the AssertionError carries a unified diff of at most MAX_DIFF_LINES changed lines.
    """
    expected_lines = content_lines(contract, golden(contract, case, variant=variant, phase=phase))
    actual_lines = content_lines(contract, actual)
    if CONTRACTS[contract].kind == "parquet":
        expected_lines = _strip_metadata_if_absent(actual_lines, expected_lines)
    if actual_lines != expected_lines:
        where = case if variant is None else f"{case}@{variant}"
        where += "" if phase is None else f" ({phase})"
        msg = (
            f"{contract} differs from its golden fixture for {where}:\n{_diff(expected_lines, actual_lines)}"
        )
        raise AssertionError(msg)
