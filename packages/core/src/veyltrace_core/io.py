"""Contract I/O: the only way engines read and write run-directory artefacts (core_api_spec §6).

Everything is driven by the generated registry `veyltrace_contracts.registry.CONTRACTS` (kind,
version, path, key, unique, self-hash rule, Pydantic model, Arrow schema) and by the JSON Schemas
themselves (`veyltrace_core.schemacheck`). Writers never let invalid or unordered data reach a
file (packages/core/AGENTS.md Never 5):

- **JSON** (`prepare`): normalise to plain JSON, stamp `schema_version` (a different supplied
  value is an error), validate against the JSON Schema *and* the Pydantic model, require the
  model to keep every value unchanged (an int given for a float field would change the bytes a
  producer may already have hashed), validate every `x-sort` order without re-sorting it
  (CONVENTIONS §3.4; lead decision §2.7), verify the self-hash (verdict, card). Bytes are
  `canonical_json(obj) + b"\\n"` (D-11).
- **JSONL** (`JsonlWriter`, agent_trace): every line is validated like a JSON document; for
  hash-chained contracts the writer fills or checks `seq`, `prev_hash` and `line_hash` (03 §9.2).
- **Parquet / CSV**: the Arrow schema must equal the contract's exactly (types, nullability,
  column order); required columns hold no nulls; NaN/±inf are rejected in every float column
  (D-12); every row is checked against the JSON Schema (vectorised); duplicate keys are rejected
  for unique contracts; rows are totally sorted (key columns, then every other column in schema
  order, nulls first, strings by UTF-8 bytes, list columns by their canonical JSON). `-0.0` is
  written as `0.0`, as in canonical JSON, so equal rows have equal bytes.
- Parquet bytes are stable within one environment: fixed writer options (`PARQUET_OPTIONS`),
  fixed row groups and chunking, metadata `veyltrace.schema = <name>/<version>` only, and they
  depend neither on the input row order nor on the destination path (03 §1 Parquet hashes).
- Every write is atomic (`textio.write_bytes`: `<path>.tmp-<pid>`, fsync, os.replace), so a
  reader in another process sees the old file or the new one, never a torn one.

Readers check the contract version (same major; before M1 the exact minor, `ALLOW_OLDER_MINOR`)
and the Arrow schema, return typed objects (a Pydantic model for JSON, `pa.Table` for Parquet and
CSV, a list of line models for JSONL), and run the full writer checks only with `validate=True`.

Locking a run directory is `veyltrace_core.locks.PathLock` (re-exported here as `PathLock`).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from io import StringIO
from pathlib import Path, PurePosixPath
from types import MappingProxyType, TracebackType
from typing import Any, Final, Self, cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import BaseModel, ValidationError

from veyltrace_contracts.models import CaseManifest
from veyltrace_contracts.registry import CONTRACTS, ContractInfo
from veyltrace_core import schemacheck, textio
from veyltrace_core.canonical import canonical_json, canonical_json_str, normalize
from veyltrace_core.errors import ArtifactMissing, ContractValidationError
from veyltrace_core.hashing import GENESIS_HASH, chain_hash, sha256_bytes, verify_chain, verify_self_hash
from veyltrace_core.hint import HINT_CONTRACT, redact_hint
from veyltrace_core.locks import LockHeld, PathLock

__all__ = [
    "ALLOW_OLDER_MINOR",
    "CSV_LIST_SEPARATOR",
    "PARQUET_OPTIONS",
    "ROW_GROUP_ROWS",
    "SCHEMA_METADATA_KEY",
    "TELEMETRY",
    "JsonlWriter",
    "LockHeld",
    "PathLock",
    "TelemetryTables",
    "arrow_schema",
    "conform_table",
    "contract_info",
    "empty_table",
    "encode",
    "exists",
    "is_run_dir_contract",
    "path_of",
    "prepare",
    "read",
    "read_lines",
    "read_model",
    "read_path",
    "read_path_unredacted",
    "read_table",
    "read_unredacted",
    "version_compatible",
    "write",
    "write_path",
    "write_text",
]

# pyarrow-stubs declares the compute kernels as overloads with Unknown parts, which pyright strict
# rejects at every call; calls go through this Any alias and results are typed where they are used.
_pc: Any = pc
_pq: Any = pq  # same reason for pyarrow.parquet (write_table and ParquetFile carry Unknown parts)


def _fields(schema: pa.Schema) -> list[pa.Field[Any]]:
    """The schema's fields, typed (pyarrow-stubs leaves Field's type parameter Unknown)."""
    loose: Any = schema
    return [cast("pa.Field[Any]", loose.field(i)) for i in range(len(schema.names))]


def _field(schema: pa.Schema, name: str) -> pa.Field[Any]:
    loose: Any = schema
    return cast("pa.Field[Any]", loose.field(name))


def _same_field(a: pa.Field[Any], b: pa.Field[Any]) -> bool:
    """Name, type and nullability equal (field metadata ignored)."""
    loose: Any = a
    return bool(loose.equals(b))


#: Parquet file metadata key holding `<name>/<major.minor.patch>` (03 §1 Versioning).
SCHEMA_METADATA_KEY: Final = b"veyltrace.schema"
#: Rows per Parquet row group and per Arrow chunk before writing (core_api_spec §6).
ROW_GROUP_ROWS: Final = 1_048_576
#: Fixed pyarrow writer options (core_api_spec §6 PARQUET_OPTIONS). Explicit even where they equal
#: pyarrow's defaults, so a default change cannot silently change artefact bytes. Parquet holds no
#: timestamps; its `created_by` names the pyarrow version, which is pinned per environment.
PARQUET_OPTIONS: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "compression": "zstd",
        "compression_level": 3,
        "use_dictionary": True,
        "write_statistics": True,
        "data_page_version": "2.0",
        "version": "2.6",
        "row_group_size": ROW_GROUP_ROWS,
        "store_schema": True,
        "use_compliant_nested_type": True,
        "write_page_index": False,
        "write_page_checksum": False,
    }
)
#: Reader version rule (core_api_spec §6, critic gap "version rule"). Before M1 a file must have
#: the reader's exact major.minor; from M1 on the lead flips this to accept an older minor of the
#: same major. Readers already handle that case: absent nullable Parquet columns and JSON fields
#: of an older-minor file read as null, absent non-null ones are refused (tests flip this flag).
ALLOW_OLDER_MINOR: Final = False
#: CSV encoding of list columns and booleans (03 §13.2: lists `;`-joined, booleans 0/1, missing
#: values empty).
CSV_LIST_SEPARATOR: Final = ";"
CSV_TRUE: Final = "1"
CSV_FALSE: Final = "0"
#: TelemetryTables field → contract.
TELEMETRY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "metrics": "telemetry.metrics",
        "logs": "telemetry.logs",
        "spans": "telemetry.spans",
        "events": "telemetry.events",
    }
)

_VERSION_RE: Final = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
# Contract paths outside a run directory: placeholders (`<family_id>`, `${VEYLTRACE_DATA}`) or
# repo-relative locations (03 §1 catalog: calibration, predicates, bench_result, answer_key).
_NON_RUN_DIR_ROOTS: Final = frozenset({"bench", "config", "contracts"})
_CHAIN_FIELDS: Final = frozenset({"seq", "prev_hash", "line_hash"})
# Strict CSV number grammars (JSON's), so " 1", "1_000", "nan" or "inf" never parse.
_CSV_INT_RE: Final = re.compile(r"-?(0|[1-9][0-9]*)")
_CSV_FLOAT_RE: Final = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_SORT_PREFIX: Final = "k"


# --------------------------------------------------------------------------------------------
# Registry lookups and paths


def contract_info(name: str) -> ContractInfo:
    """The registry entry of contract `name` (ContractValidationError for an unknown name)."""
    info = CONTRACTS.get(name)
    if info is None:
        raise ContractValidationError(name, f"unknown contract; known: {', '.join(sorted(CONTRACTS))}")
    return info


def is_run_dir_contract(name: str) -> bool:
    """True if the contract lives in a run directory (its registry path is run-dir relative)."""
    path = contract_info(name).path
    if "<" in path or "$" in path:
        return False
    return PurePosixPath(path).parts[0] not in _NON_RUN_DIR_ROOTS


def path_of(name: str, run_dir: Path) -> Path:
    """The path of contract `name` inside `run_dir` (02 §4.1); other contracts use read_path/write_path."""
    if not is_run_dir_contract(name):
        msg = f"{contract_info(name).path} is not a run-directory path; use read_path/write_path"
        raise ContractValidationError(name, msg)
    return Path(run_dir).joinpath(*PurePosixPath(contract_info(name).path).parts)


def exists(name: str, run_dir: Path) -> bool:
    """True if contract `name` is present in `run_dir` (optional inputs: proposals, agent_trace)."""
    return path_of(name, run_dir).is_file()


def arrow_schema(name: str) -> pa.Schema:
    """The Arrow schema of table contract `name`, with metadata `veyltrace.schema`."""
    schema = contract_info(name).arrow_schema
    if schema is None:
        raise ContractValidationError(name, "not a table contract (no Arrow schema)")
    return schema


def empty_table(name: str) -> pa.Table:
    """A typed zero-row table of contract `name` (an absent telemetry source, a stub output)."""
    return arrow_schema(name).empty_table()


def _json_properties(name: str) -> Mapping[str, object]:
    return cast("Mapping[str, object]", schemacheck.contract_schema(name).get("properties", {}))


def _has_schema_version(name: str) -> bool:
    return "schema_version" in _json_properties(name)


def _is_chained(name: str) -> bool:
    return set(_json_properties(name)) >= _CHAIN_FIELDS


# --------------------------------------------------------------------------------------------
# Versions


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.fullmatch(text)
    if match is None:
        return None
    return (int(match[1]), int(match[2]), int(match[3]))


def version_compatible(file_version: str, reader_version: str) -> bool:
    """True if a file of `file_version` may be read by code built for `reader_version`."""
    found, mine = _parse_version(file_version), _parse_version(reader_version)
    if found is None or mine is None or found[0] != mine[0]:
        return False
    return found[1] == mine[1] or (ALLOW_OLDER_MINOR and found[1] < mine[1])


def _is_older_minor(name: str, found: object) -> bool:
    """True if a readable file was written under an older minor of the contract (only possible
    once ALLOW_OLDER_MINOR is on): its additive fields are absent and read as null."""
    if not isinstance(found, str):
        return False
    file_v, reader_v = _parse_version(found), _parse_version(contract_info(name).version)
    return (
        file_v is not None
        and reader_v is not None
        and version_compatible(found, contract_info(name).version)
        and file_v[1] < reader_v[1]
    )


def _check_version(name: str, found: object, where: Path) -> None:
    version = contract_info(name).version
    if not isinstance(found, str) or not version_compatible(found, version):
        msg = f"{where.as_posix()}: schema version {found!r} is not readable by {name}/{version}"
        raise ContractValidationError(name, msg)


# --------------------------------------------------------------------------------------------
# JSON documents and lines


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            msg = f"duplicate key {key!r}"
            raise ValueError(msg)
        out[key] = value
    return out


def _reject_constant(token: str) -> object:
    msg = f"{token} is not JSON"
    raise ValueError(msg)


def _loads(name: str, text: str, where: str) -> object:
    """Strict JSON parsing: no NaN/Infinity tokens, no duplicate keys."""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except ValueError as exc:  # JSONDecodeError is a ValueError
        raise ContractValidationError(name, f"{where}: invalid JSON: {exc}") from None


def _decode(name: str, raw: bytes, where: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractValidationError(name, f"{where}: not UTF-8: {exc}") from None


def _non_finite_pointer(value: object, pointer: str = "") -> tuple[str, float] | None:
    """The JSON pointer and value of the first NaN/±inf float in `value`, in key order."""
    if isinstance(value, float):
        return None if math.isfinite(value) else (pointer or "/", value)
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        for key in sorted(mapping, key=str):
            found = _non_finite_pointer(mapping[key], f"{pointer}/{key}")
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for i, item in enumerate(cast("Sequence[object]", value)):
            found = _non_finite_pointer(item, f"{pointer}/{i}")
            if found is not None:
                return found
    return None


def _plain_object(name: str, data: object) -> dict[str, Any]:
    """`data` (a Mapping, or a model of this contract) as a normalised plain JSON object.

    NaN and ±inf are rejected here, before `normalize` would turn them into null: in a nullable
    field null has its own meaning (verdict.confidence.q_hat null documents +inf), so a NaN from a
    producer bug must not be written as a valid-looking value (D-12 for JSON). Producers write
    null themselves where the schema defines it.
    """
    model = contract_info(name).model
    if isinstance(data, BaseModel):
        if not isinstance(data, model):
            msg = f"got a {type(data).__name__}, expected a {model.__name__} or a mapping"
            raise ContractValidationError(name, msg)
        data = data.model_dump(mode="json", by_alias=True)
    if not isinstance(data, Mapping):
        raise ContractValidationError(
            name, f"expected a mapping or {model.__name__}, got {type(data).__name__}"
        )
    bad = _non_finite_pointer(cast("object", data))
    if bad is not None:
        pointer, value = bad
        msg = f"{value!r} (NaN/inf) is not allowed at {pointer}; write null only where the schema defines it"
        raise ContractValidationError(name, msg)
    try:
        plain = normalize(cast("Mapping[str, Any]", data))
    except TypeError as exc:
        raise ContractValidationError(name, f"not JSON-serialisable: {exc}") from None
    return cast("dict[str, Any]", plain)


def _model_validate(name: str, obj: object, where: str = "") -> BaseModel:
    try:
        return contract_info(name).model.model_validate(obj)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = "/" + "/".join(str(p) for p in first["loc"])
        more = f" (+{exc.error_count() - 1} more)" if exc.error_count() > 1 else ""
        raise ContractValidationError(
            name, f"{where}model violation at {loc}: {first['msg']}{more}"
        ) from None


def _first_difference(a: object, b: object, path: str = "") -> str:
    """The JSON path where two plain JSON values first differ (for error messages)."""
    if isinstance(a, dict) and isinstance(b, dict):
        da, db = cast("dict[str, object]", a), cast("dict[str, object]", b)
        for key in sorted(set(da) | set(db)):
            if (
                key not in da
                or key not in db
                or canonical_json(cast("Any", da[key])) != canonical_json(cast("Any", db[key]))
            ):
                return _first_difference(da.get(key), db.get(key), f"{path}/{key}")
    if isinstance(a, list) and isinstance(b, list):
        la, lb = cast("list[object]", a), cast("list[object]", b)
        for i, (x, y) in enumerate(zip(la, lb, strict=False)):
            if canonical_json(cast("Any", x)) != canonical_json(cast("Any", y)):
                return _first_difference(x, y, f"{path}/{i}")
    return f"{path or '/'} ({a!r} -> {b!r})"


def _checked_model(name: str, obj: dict[str, Any], where: str = "") -> tuple[BaseModel, dict[str, Any]]:
    """Schema + model validation, value preservation and x-sort orders; returns (model, dump)."""
    schemacheck.validate_json_schema(name, obj, where=where)
    model = _model_validate(name, obj, where)
    dumped = cast("dict[str, Any]", normalize(model.model_dump(mode="json", by_alias=True)))
    if canonical_json(dumped) != canonical_json(obj):
        msg = f"{where}the model changes a value at {_first_difference(obj, dumped)}; pass the typed value"
        raise ContractValidationError(name, msg)
    try:
        schemacheck.check_orders(name, dumped)
    except ContractValidationError as exc:
        raise ContractValidationError(name, f"{where}{exc.detail}") from None
    return model, dumped


def _require_kind(name: str, *kinds: str) -> ContractInfo:
    info = contract_info(name)
    if info.kind not in kinds:
        raise ContractValidationError(name, f"is a {info.kind} contract, expected {' or '.join(kinds)}")
    return info


def prepare(name: str, data: Mapping[str, Any] | BaseModel) -> BaseModel:
    """Validate a JSON contract document and return its model, ready to write.

    Stamps `schema_version` when absent; checks the JSON Schema, the model, the x-sort orders
    (validated, never re-sorted) and the self-hash. Raises ContractValidationError.
    """
    info = _require_kind(name, "json")
    obj = _plain_object(name, data)
    if _has_schema_version(name):
        supplied = obj.setdefault("schema_version", info.version)
        if supplied != info.version:
            msg = f"schema_version {supplied!r} differs from the writer's {info.version!r}"
            raise ContractValidationError(name, msg)
    model, dumped = _checked_model(name, obj)
    if info.self_hash is not None:
        verify_self_hash(name, dumped)
    return model


def _line_bytes(model: BaseModel) -> bytes:
    return canonical_json(model) + b"\n"


class JsonlWriter:
    """Streams a JSONL contract (agent_trace) line by line into its run directory.

    Each `append` validates the line, writes `canonical_json(line) + "\\n"` and flushes, all to
    `<path>.tmp-<pid>`; `close` publishes the file atomically and returns its sha256, and `abort`
    discards it. For hash-chained contracts (03 §9.2) the writer fills `seq`, `prev_hash` and
    `line_hash` when they are absent or null, and rejects supplied values that differ from the
    chain. As a context manager it closes on success and aborts on an exception.
    """

    def __init__(self, name: str, run_dir: Path) -> None:
        self._open(name, path_of(name, run_dir))

    @classmethod
    def at_path(cls, name: str, path: Path) -> JsonlWriter:
        """A writer for a JSONL contract at an explicit path (fixtures, snapshots)."""
        writer = cls.__new__(cls)
        writer._open(name, Path(path))
        return writer

    def _open(self, name: str, path: Path) -> None:
        _require_kind(name, "jsonl")
        self.name = name
        self.path = path
        self._chained = _is_chained(name)
        self._digest = hashlib.sha256()
        self._count = 0
        self._head = GENESIS_HASH
        self._out = textio.AtomicTextWriter(path)
        self._sha: str | None = None

    @property
    def count(self) -> int:
        """Lines written so far."""
        return self._count

    @property
    def head(self) -> str | None:
        """The last line_hash of a chained contract (None before the first line)."""
        return self._head if self._chained and self._count else None

    def append(self, line: Mapping[str, Any] | BaseModel) -> None:
        """Validate one line and write it (see class doc)."""
        if self._out.closed:
            raise ContractValidationError(self.name, f"writer for {self.path.as_posix()} is closed")
        where = f"line {self._count}: "
        obj = _plain_object(self.name, line)
        if self._chained:
            self._chain(obj, where)
        model, _ = _checked_model(self.name, obj, where)
        data = _line_bytes(model)
        self._out.write(data.decode("utf-8"))
        self._out.flush()
        self._digest.update(data)
        self._count += 1
        if self._chained:
            self._head = str(obj["line_hash"])

    def _chain(self, obj: dict[str, Any], where: str) -> None:
        for key, expected in (("seq", self._count), ("prev_hash", self._head)):
            if obj.get(key) is None:
                obj[key] = expected
            elif obj[key] != expected or isinstance(obj[key], bool):
                msg = f"{where}{key} is {obj[key]!r}, the chain needs {expected!r}"
                raise ContractValidationError(self.name, msg)
        computed = chain_hash(self._head, obj)
        given = obj.get("line_hash")
        if given is None:
            obj["line_hash"] = computed
        elif given != computed:
            raise ContractValidationError(self.name, f"{where}line_hash {given!r} != chain hash {computed!r}")

    def close(self) -> str:
        """Publish the file atomically and return its sha256 (an empty trace is an empty file)."""
        if self._sha is None:
            self._out.commit()
            self._sha = self._digest.hexdigest()
        return self._sha

    def abort(self) -> None:
        """Discard everything written; the target is left as it was."""
        self._out.abort()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
        else:
            self.abort()


# --------------------------------------------------------------------------------------------
# Tables


def _describe(field: pa.Field[Any]) -> str:
    return f"{field.type}{'' if field.nullable else ' not null'}"


def _schema_difference(actual: pa.Schema, expected: pa.Schema) -> str:
    if actual.names != expected.names:
        return f"columns {actual.names} != contract columns {expected.names}"
    for got, want in zip(_fields(actual), _fields(expected), strict=True):
        if not _same_field(got, want):
            return f"column {want.name!r} is {_describe(got)}, contract has {_describe(want)}"
    return "schemas differ"


def conform_table(name: str, table: pa.Table) -> pa.Table:
    """Reorder and safely cast a producer's table to the contract schema (DuckDB output, tables
    built without `schema=`). Never needed for tables built with `schema=arrow_schema(name)`.
    Raises ContractValidationError for missing or extra columns or a lossy cast."""
    expected = arrow_schema(name)
    if sorted(table.column_names) != sorted(expected.names):
        msg = f"columns {sorted(table.column_names)} != contract columns {sorted(expected.names)}"
        raise ContractValidationError(name, msg)
    try:
        arrays = [table.column(f.name).cast(f.type, safe=True) for f in _fields(expected)]
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as exc:
        raise ContractValidationError(name, f"cannot cast to the contract schema: {exc}") from None
    return pa.Table.from_arrays(arrays, schema=expected)


def _row_object(name: str, row: object) -> dict[str, Any]:
    """One table row as a dict, values untouched: no float rounding and no NaN → null (rows
    and an equivalent pa.Table must give the same bytes, and NaN must reach the D-12 check)."""
    model = contract_info(name).model
    if isinstance(row, BaseModel):
        if not isinstance(row, model):
            msg = f"got a {type(row).__name__}, expected a {model.__name__} or a mapping"
            raise ContractValidationError(name, msg)
        return row.model_dump(mode="python", by_alias=True)
    if not isinstance(row, Mapping):
        raise ContractValidationError(
            name, f"expected a mapping or {model.__name__}, got {type(row).__name__}"
        )
    return dict(cast("Mapping[str, Any]", row))


def _as_table(name: str, data: object) -> pa.Table:
    expected = arrow_schema(name)
    if isinstance(data, pa.RecordBatch):
        data = pa.Table.from_batches([data])
    if isinstance(data, pa.Table):
        if not data.schema.equals(expected, check_metadata=False):
            hint = "; build it with schema=io.arrow_schema(name) or pass it through io.conform_table"
            raise ContractValidationError(name, _schema_difference(data.schema, expected) + hint)
        return pa.Table.from_arrays(data.columns, schema=expected)  # contract field defs and metadata
    if isinstance(data, str | bytes | Mapping) or not isinstance(data, Sequence):
        kind = type(cast("object", data)).__name__
        msg = f"expected a pyarrow Table, a RecordBatch or a sequence of rows, got {kind}"
        raise ContractValidationError(name, msg)
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(cast("Sequence[object]", data)):
        obj = _row_object(name, row)
        if set(obj) != set(expected.names):
            msg = f"row {i}: keys {sorted(obj)} != contract columns {sorted(expected.names)}"
            raise ContractValidationError(name, msg)
        rows.append(obj)
    try:
        return pa.Table.from_pylist(rows, schema=expected)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, OverflowError) as exc:
        raise ContractValidationError(name, f"rows do not fit the Arrow schema: {exc}") from None


def _check_nulls_and_floats(name: str, table: pa.Table) -> None:
    for field in _fields(table.schema):
        column = table.column(field.name)
        if not field.nullable and column.null_count:
            raise ContractValidationError(
                name, f"column {field.name!r} is required but holds {column.null_count} nulls"
            )
        if pa.types.is_floating(field.type):
            bad = int(_pc.sum(_pc.invert(_pc.is_finite(column))).as_py() or 0)  # nulls are skipped
            if bad:
                raise ContractValidationError(
                    name, f"column {field.name!r} holds {bad} NaN/inf values (D-12)"
                )


def _positive_zero(table: pa.Table) -> pa.Table:
    """-0.0 → 0.0 in float columns (x + 0.0 changes nothing else for finite x): canonical JSON's
    rule, and it makes equal rows byte-equal so the sort order is total."""
    columns = [
        _pc.add(table.column(i), 0.0) if pa.types.is_floating(f.type) else table.column(i)
        for i, f in enumerate(_fields(table.schema))
    ]
    return pa.Table.from_arrays(columns, schema=table.schema)


def _sort_indices(name: str, table: pa.Table) -> pa.Array[Any]:
    """Canonical row order: key columns, then the rest in schema order; nulls first; strings by
    UTF-8 bytes (Arrow compares bytes); list columns by their canonical JSON string."""
    key = list(contract_info(name).key)
    order = key + [c for c in table.column_names if c not in key]
    sort_columns: dict[str, pa.ChunkedArray[Any] | pa.Array[Any]] = {}
    for i, column_name in enumerate(order):
        column = table.column(column_name)
        if pa.types.is_list(column.type):
            values = cast("list[list[object] | None]", column.to_pylist())
            column = pa.array(
                [None if v is None else canonical_json_str(cast("Any", v)) for v in values], type=pa.string()
            )
        sort_columns[f"{_SORT_PREFIX}{i}"] = column
    keys = [(k, "ascending", "at_start") for k in sort_columns]
    sort_table = pa.Table.from_arrays(list(sort_columns.values()), names=list(sort_columns))
    return cast("pa.Array[Any]", _pc.sort_indices(sort_table, sort_keys=keys))


def _check_unique(name: str, table: pa.Table) -> None:
    key = list(contract_info(name).key)
    if not key or table.num_rows == 0:
        return
    counts = table.select(key).group_by(key, use_threads=False).aggregate([([], "count_all")])
    duplicates = counts.filter(_pc.greater(counts.column("count_all"), 1))
    if duplicates.num_rows:
        first = cast("dict[str, object]", duplicates.select(key).slice(0, 1).to_pylist()[0])
        raise ContractValidationError(name, f"duplicate key {first} ({duplicates.num_rows} duplicated keys)")


def _rechunk(table: pa.Table) -> pa.Table:
    """One chunk per ROW_GROUP_ROWS rows, whatever the input chunking, so pages and row groups
    (and therefore bytes) depend only on the data."""
    if table.num_rows == 0:
        return table.combine_chunks()
    parts = [
        table.slice(start, ROW_GROUP_ROWS).combine_chunks()
        for start in range(0, table.num_rows, ROW_GROUP_ROWS)
    ]
    return pa.concat_tables(parts)


def _validate_table(name: str, table: pa.Table) -> None:
    _check_nulls_and_floats(name, table)
    schemacheck.check_table_rows(name, table)
    if contract_info(name).unique:
        _check_unique(name, table)


def _canonical_table(name: str, data: object) -> pa.Table:
    """Validated, canonically sorted and rechunked table with the contract's schema."""
    table = _positive_zero(_as_table(name, data))
    _validate_table(name, table)
    return _rechunk(table.take(_sort_indices(name, table)))


def _parquet_bytes(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    _pq.write_table(table, sink, **PARQUET_OPTIONS)
    return sink.getvalue().to_pybytes()


def _csv_cell(name: str, column: str, value: object, nullable: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return CSV_TRUE if value else CSV_FALSE
    if isinstance(value, float):
        return canonical_json_str(value)  # rounded to 9 decimals, shortest repr: stable on every OS
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        items = [str(v) for v in cast("list[object]", value)]
        if any(not item or CSV_LIST_SEPARATOR in item for item in items):
            raise ContractValidationError(
                name, f"column {column!r}: list item empty or containing {CSV_LIST_SEPARATOR!r}"
            )
        return CSV_LIST_SEPARATOR.join(items)
    text = str(value)
    if nullable and not text:
        raise ContractValidationError(name, f"column {column!r}: an empty string would read back as null")
    return text


def _csv_bytes(name: str, table: pa.Table) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(table.column_names)
    nullable = [f.nullable for f in _fields(table.schema)]
    columns = [cast("list[object]", table.column(i).to_pylist()) for i in range(table.num_columns)]
    for r in range(table.num_rows):
        writer.writerow(
            [
                _csv_cell(name, table.column_names[c], columns[c][r], nullable[c])
                for c in range(table.num_columns)
            ]
        )
    return buffer.getvalue().encode("utf-8")


def _csv_value(name: str, field: pa.Field[Any], cell: str, where: str) -> object:
    dtype = field.type
    if pa.types.is_list(dtype):
        return cell.split(CSV_LIST_SEPARATOR) if cell else []
    if cell == "" and (field.nullable or not pa.types.is_string(dtype)):
        return None
    if pa.types.is_boolean(dtype):
        if cell not in (CSV_TRUE, CSV_FALSE):
            raise ContractValidationError(name, f"{where}: {cell!r} is not {CSV_FALSE}/{CSV_TRUE}")
        return cell == CSV_TRUE
    if pa.types.is_integer(dtype):
        if _CSV_INT_RE.fullmatch(cell) is None:
            raise ContractValidationError(name, f"{where}: {cell!r} is not an integer")
        return int(cell)
    if pa.types.is_floating(dtype):
        if _CSV_FLOAT_RE.fullmatch(cell) is None:
            raise ContractValidationError(name, f"{where}: {cell!r} is not a number")
        return float(cell)
    return cell


def _read_csv(name: str, path: Path) -> pa.Table:
    expected = arrow_schema(name)
    text = _decode(name, textio.read_bytes(path), path.as_posix())
    rows = list(csv.reader(StringIO(text, newline=""), strict=True))
    if not rows or rows[0] != expected.names:
        found = rows[0] if rows else []
        raise ContractValidationError(
            name, f"{path.as_posix()}: header {found} != contract columns {expected.names}"
        )
    columns: list[list[object]] = [[] for _ in expected.names]
    for r, row in enumerate(rows[1:], start=1):
        if len(row) != len(expected.names):
            raise ContractValidationError(
                name, f"{path.as_posix()} line {r + 1}: {len(row)} cells, expected {len(expected.names)}"
            )
        for c, field in enumerate(_fields(expected)):
            columns[c].append(
                _csv_value(name, field, row[c], f"{path.as_posix()} line {r + 1} column {field.name!r}")
            )
    try:
        return pa.Table.from_arrays(
            [
                cast("pa.Array[Any]", pa.array(col, type=f.type))
                for col, f in zip(columns, _fields(expected), strict=True)
            ],
            schema=expected,
        )
    except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError) as exc:
        raise ContractValidationError(name, f"{path.as_posix()}: {exc}") from None


def _projected_schema(name: str, columns: Sequence[str] | None) -> pa.Schema:
    expected = arrow_schema(name)
    if columns is None:
        return expected
    if any(c not in expected.names for c in columns) or len(set(columns)) != len(columns):
        raise ContractValidationError(name, f"bad column selection {list(columns)}")
    metadata = cast("dict[bytes | str, bytes | str]", dict(expected.metadata or {}))
    return pa.schema([_field(expected, c) for c in columns], metadata=metadata)


def _absent_columns(name: str, found: pa.Schema, expected: pa.Schema, where: str) -> tuple[str, ...]:
    """The contract columns an older-minor file lacks (critic gap "version rule": additive fields
    read as null). The file's columns must be the contract's, in contract order, with the same
    types; every absent column must be nullable, since an additive field is never required."""
    present = list(found.names)
    if [c for c in expected.names if c in present] != present:
        raise ContractValidationError(name, f"{where}: {_schema_difference(found, expected)}")
    for got in _fields(found):
        want = _field(expected, got.name)
        if not _same_field(got, want):
            raise ContractValidationError(
                name, f"{where}: column {want.name!r} is {_describe(got)}, contract has {_describe(want)}"
            )
    absent = tuple(c for c in expected.names if c not in present)
    required = [c for c in absent if not _field(expected, c).nullable]
    if required:
        msg = f"{where}: older-minor file lacks non-null columns {required}"
        raise ContractValidationError(name, msg)
    return absent


def _read_parquet(name: str, path: Path, columns: Sequence[str] | None) -> pa.Table:
    """Read (only `columns`, if given) after checking the stamp and the Arrow schema. The result
    is cast to the contract schema: Parquet's compliant list encoding names the list item
    `element`, the contracts name it `item`."""
    expected = arrow_schema(name)
    projected = _projected_schema(name, columns)
    where = path.as_posix()
    try:
        with _pq.ParquetFile(path) as parquet:
            found = cast("pa.Schema", parquet.schema_arrow)
            metadata = cast("Mapping[bytes, bytes]", found.metadata or {})
            stamp = metadata.get(SCHEMA_METADATA_KEY, b"").decode("utf-8", errors="replace")
            stamped_name, _, stamped_version = stamp.rpartition("/")
            if stamped_name != name:
                raise ContractValidationError(name, f"{where}: metadata veyltrace.schema is {stamp!r}")
            _check_version(name, stamped_version, path)
            absent: tuple[str, ...] = ()
            if not found.equals(expected, check_metadata=False):
                if not _is_older_minor(name, stamped_version):
                    raise ContractValidationError(name, f"{where}: {_schema_difference(found, expected)}")
                absent = _absent_columns(name, found, expected, where)
            wanted = list(projected.names)
            selection = None if columns is None and not absent else [c for c in wanted if c not in absent]
            table = cast("pa.Table", parquet.read(columns=selection, use_pandas_metadata=False))
            for column in (c for c in wanted if c in absent):
                field = _field(expected, column)
                nulls = cast("pa.Array[Any]", pa.nulls(table.num_rows, field.type))
                table = table.append_column(field, nulls)
            return table.select(wanted).cast(projected)
    except (pa.ArrowInvalid, OSError) as exc:
        if isinstance(exc, FileNotFoundError):
            raise ArtifactMissing(name, path) from None
        raise ContractValidationError(name, f"{where}: not a readable Parquet file: {exc}") from None


def _check_sorted(name: str, table: pa.Table) -> None:
    indices = _sort_indices(name, table)
    positions = cast("list[int]", indices.to_pylist())
    if positions != list(range(table.num_rows)):
        mismatch = next(i for i, p in enumerate(positions) if p != i)
        raise ContractValidationError(
            name, f"rows are not in canonical order (first misplaced row {mismatch})"
        )


def _select(name: str, table: pa.Table, columns: Sequence[str] | None) -> pa.Table:
    if columns is None:
        return table
    unknown = [c for c in columns if c not in table.column_names]
    if unknown or len(set(columns)) != len(columns):
        raise ContractValidationError(name, f"bad column selection {list(columns)}")
    return table.select(list(columns))


# --------------------------------------------------------------------------------------------
# Public read / write


def encode(name: str, data: object) -> bytes:
    """The exact file bytes `write` would produce for `data` (JSON, Parquet or CSV contracts)."""
    info = contract_info(name)
    if info.kind == "json":
        return canonical_json(prepare(name, cast("Mapping[str, Any] | BaseModel", data))) + b"\n"
    if info.kind == "parquet":
        return _parquet_bytes(_canonical_table(name, data))
    if info.kind == "csv":
        return _csv_bytes(name, _canonical_table(name, data))
    raise ContractValidationError(name, "JSONL contracts are written line by line; use JsonlWriter")


def write_path(name: str, data: object, path: Path) -> str:
    """Validate, order and atomically write contract `name` at `path`; return the file sha256.

    For JSONL contracts `data` is a sequence of lines (written through JsonlWriter).
    """
    target = Path(path)
    if contract_info(name).kind == "jsonl":
        if isinstance(data, str | bytes | Mapping | BaseModel) or not isinstance(data, Sequence):
            raise ContractValidationError(name, "expected a sequence of lines")
        with JsonlWriter.at_path(name, target) as writer:
            for line in cast("Sequence[Mapping[str, Any] | BaseModel]", data):
                writer.append(line)
        return writer.close()
    payload = encode(name, data)
    textio.write_bytes(target, payload)
    return sha256_bytes(payload)


def write(name: str, data: object, run_dir: Path) -> str:
    """Validate, order and atomically write contract `name` into `run_dir`; return the file sha256."""
    return write_path(name, data, path_of(name, run_dir))


def _safe_relpath(relpath: str) -> PurePosixPath:
    rel = PurePosixPath(relpath)
    if (
        not relpath
        or "\\" in relpath
        or rel.is_absolute()
        or ":" in rel.parts[0]
        or any(part in ("", ".", "..") for part in relpath.split("/"))
    ):
        msg = f"{relpath!r} must be a relative POSIX path inside the run directory"
        raise ValueError(msg)
    return rel


def write_text(relpath: str, text: str, run_dir: Path) -> str:
    """Atomically write a non-contract text artefact (card.md) as UTF-8 with LF line ends (CRLF
    and lone CR become LF); return its sha256. Contract paths are refused: they go through write."""
    rel = _safe_relpath(relpath)
    claimed = sorted(n for n in CONTRACTS if is_run_dir_contract(n) and CONTRACTS[n].path == rel.as_posix())
    if claimed:
        msg = f"{relpath!r} is the path of contract {claimed[0]!r}; use io.write"
        raise ValueError(msg)
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    textio.write_bytes(Path(run_dir).joinpath(*rel.parts), data)
    return sha256_bytes(data)


def _read_json(name: str, path: Path, validate: bool) -> BaseModel:
    where = path.as_posix()
    obj = _loads(name, _decode(name, textio.read_bytes(path), where), where)
    if not isinstance(obj, dict):
        raise ContractValidationError(name, f"{where}: expected a JSON object")
    document = cast("dict[str, Any]", obj)
    original = document
    if _has_schema_version(name):
        _check_version(name, document.get("schema_version"), path)
        if _is_older_minor(name, document.get("schema_version")):
            # Additive fields absent from an older-minor file read as null (critic gap "version
            # rule") and the model sees the reader's version (the schemas pin major.minor); the
            # self-hash is the writer's, over the document as written.
            document = cast("dict[str, Any]", schemacheck.fill_absent_nullable(name, document))
            document["schema_version"] = contract_info(name).version
    if not validate:
        return _model_validate(name, document, f"{where}: ")
    model, dumped = _checked_model(name, document, f"{where}: ")
    if contract_info(name).self_hash is not None:
        verify_self_hash(name, dumped if original is document else original)
    return model


def _read_jsonl(name: str, path: Path, validate: bool) -> list[BaseModel]:
    where = path.as_posix()
    text = _decode(name, textio.read_bytes(path), where)
    if not text:
        return []
    if not text.endswith("\n") or "\r" in text:
        raise ContractValidationError(name, f"{where}: lines must be LF-terminated, without CR")
    models: list[BaseModel] = []
    for i, line in enumerate(text[:-1].split("\n")):
        line_where = f"{where} line {i}: "
        obj = _loads(name, line, line_where) if line else None
        if not isinstance(obj, dict):
            raise ContractValidationError(name, f"{line_where}expected a JSON object")
        document = cast("dict[str, Any]", obj)
        models.append(
            _checked_model(name, document, line_where)[0]
            if validate
            else _model_validate(name, document, line_where)
        )
    if validate and _is_chained(name):
        verify_chain(models)
    return models


def read_path_unredacted(
    name: str, path: Path, *, columns: Sequence[str] | None = None, validate: bool = False
) -> BaseModel | pa.Table | list[BaseModel]:
    """`read_path` without the alert-hint redaction of case_manifest. Only Infralume, core's alert
    step and core testing may call it (D-15; the isolation literal scan bans the name elsewhere)."""
    info = contract_info(name)
    source = Path(path)
    if not source.is_file():
        raise ArtifactMissing(name, source)
    if columns is not None and info.kind not in ("parquet", "csv"):
        raise ContractValidationError(name, "columns= applies to table contracts only")
    if info.kind == "json":
        return _read_json(name, source, validate)
    if info.kind == "jsonl":
        return _read_jsonl(name, source, validate)
    if info.kind == "parquet":
        table = _read_parquet(name, source, None if validate else columns)
    else:
        table = _read_csv(name, source)
    if validate:
        _validate_table(name, table)
        _check_sorted(name, table)
    return _select(name, table, columns)


def read_path(
    name: str, path: Path, *, columns: Sequence[str] | None = None, validate: bool = False
) -> BaseModel | pa.Table | list[BaseModel]:
    """Read contract `name` from `path` (see module doc). Missing file → ArtifactMissing;
    a version, schema or (with `validate`) content problem → ContractValidationError.

    case_manifest comes back with the alert hint redacted (t_alert_hint_ns null, hint_source
    "none"), whoever calls: redaction lives here so no engine can bypass it by reading through
    io instead of RunContext (02 §5.1, D-15). `validate=True` still checks the file as written.
    """
    value = read_path_unredacted(name, path, columns=columns, validate=validate)
    if name == HINT_CONTRACT and isinstance(value, CaseManifest):
        return redact_hint(value)
    return value


def read(
    name: str, run_dir: Path, *, columns: Sequence[str] | None = None, validate: bool = False
) -> BaseModel | pa.Table | list[BaseModel]:
    """Read contract `name` from `run_dir`: a model (JSON), a pa.Table (Parquet, CSV) or a list
    of line models (JSONL). case_manifest is hint-redacted (see read_path)."""
    return read_path(name, path_of(name, run_dir), columns=columns, validate=validate)


def read_unredacted(
    name: str, run_dir: Path, *, columns: Sequence[str] | None = None, validate: bool = False
) -> BaseModel | pa.Table | list[BaseModel]:
    """`read` without the alert-hint redaction (see read_path_unredacted for who may call it)."""
    return read_path_unredacted(name, path_of(name, run_dir), columns=columns, validate=validate)


def read_model[M: BaseModel](name: str, run_dir: Path, model: type[M], *, validate: bool = False) -> M:
    """`read` for a JSON contract, typed: `read_model("slate", run_dir, Slate)`."""
    _require_kind(name, "json")
    value = read(name, run_dir, validate=validate)
    if not isinstance(value, model):
        raise ContractValidationError(name, f"is read as {type(value).__name__}, not {model.__name__}")
    return value


def read_lines[M: BaseModel](name: str, run_dir: Path, model: type[M], *, validate: bool = False) -> list[M]:
    """`read` for a JSONL contract, typed: `read_lines("agent_trace", run_dir, AgentTraceLine)`."""
    _require_kind(name, "jsonl")
    if contract_info(name).model is not model:
        raise ContractValidationError(
            name, f"lines are {contract_info(name).model.__name__}, not {model.__name__}"
        )
    return cast("list[M]", read(name, run_dir, validate=validate))


def read_table(
    name: str, run_dir: Path, *, columns: Sequence[str] | None = None, validate: bool = False
) -> pa.Table:
    """`read` for a table contract, typed as pa.Table."""
    _require_kind(name, "parquet", "csv")
    return cast("pa.Table", read(name, run_dir, columns=columns, validate=validate))


# --------------------------------------------------------------------------------------------
# Telemetry bundle


def _check_projection(name: str, table: pa.Table) -> None:
    """`table` has a subset of the contract's columns, in contract order, with contract types."""
    expected = arrow_schema(name)
    positions = [expected.get_field_index(n) for n in table.column_names]
    if -1 in positions or positions != sorted(positions) or len(set(positions)) != len(positions):
        raise ContractValidationError(
            name, f"columns {table.column_names} are not a projection of {expected.names}"
        )
    for field in _fields(table.schema):
        if not _same_field(field, _field(expected, field.name)):
            raise ContractValidationError(
                name,
                f"column {field.name!r} is {field.type}, contract has {_field(expected, field.name).type}",
            )


def _empty_projection(name: str, columns: Sequence[str] | None) -> pa.Table:
    return _select(name, empty_table(name), columns)


@dataclass(frozen=True)
class TelemetryTables:
    """The four canonical telemetry tables of one case (never None: an absent source is an empty
    table, so detectors and engines need no null checks). Columns may be a projection of the
    contract's, in contract order, with the contract's types; construction checks this however
    the object is built. This is the one class: `veyltrace_core.adapters.TelemetryTables` is the
    same object (CanonicalCase, DetectAlert and engines share one type, D-1/D-2)."""

    metrics: pa.Table
    logs: pa.Table
    spans: pa.Table
    events: pa.Table

    def __post_init__(self) -> None:
        for field in fields(self):
            _check_projection(TELEMETRY[field.name], cast("pa.Table", getattr(self, field.name)))

    @classmethod
    def from_run_dir(cls, run_dir: Path, *, columns: Mapping[str, Sequence[str]] | None = None) -> Self:
        """Read telemetry/*.parquet from `run_dir`; a missing file gives an empty table.
        `columns` maps a source (metrics, logs, spans, events) to the columns to read."""
        wanted = dict(columns or {})
        unknown = sorted(set(wanted) - set(TELEMETRY))
        if unknown:
            msg = f"unknown telemetry sources {unknown}; known: {sorted(TELEMETRY)}"
            raise ValueError(msg)
        tables: dict[str, pa.Table] = {}
        for source, name in TELEMETRY.items():
            cols = wanted.get(source)
            if exists(name, run_dir):
                tables[source] = read_table(name, run_dir, columns=cols)
            else:
                tables[source] = _empty_projection(name, cols)
        return cls(**tables)

    @classmethod
    def from_tables(cls, **tables: pa.Table) -> Self:
        """Wrap in-memory tables (gateway watcher); a source not given is an empty table."""
        unknown = sorted(set(tables) - set(TELEMETRY))
        if unknown:
            msg = f"unknown telemetry sources {unknown}; known: {sorted(TELEMETRY)}"
            raise ValueError(msg)
        filled = {source: tables.get(source, empty_table(name)) for source, name in TELEMETRY.items()}
        return cls(**filled)

    def items(self) -> tuple[tuple[str, pa.Table], ...]:
        """(source, table) pairs in the fixed order metrics, logs, spans, events."""
        return tuple((source, cast("pa.Table", getattr(self, source))) for source in TELEMETRY)
