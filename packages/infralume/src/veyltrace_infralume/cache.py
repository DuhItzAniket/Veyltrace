"""Infralume's convert cache `${VEYLTRACE_DATA}/cache/<dataset>/<case_id>/<key>/` (01 §3.1).

Why: converting a raw case is the expensive half of ingest (≤ 10 s per RE2 case, outside the 30 s
run budget); every later run of the case only materialises. The key hashes everything a converted
table depends on: the adapter and its revision, `scrub.rules_version` and the convert-phase config
sections, so a changed rule or config forces a fresh conversion and stale tables are never served.
The cache holds the full-span tables after normalisation and scrubbing, plus the
descriptive facts, never the hint: materialise asks the adapter for it on every run. Generated
data (synth) is never cached (`Adapter.cacheable`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

import pyarrow as pa

from veyltrace_core import io, textio
from veyltrace_core.adapters import TELEMETRY_CONTRACTS, Adapter, CanonicalCase, CaseRef, TelemetryTables
from veyltrace_core.canonical import canonical_json, normalize
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import sha256_json

__all__ = ["CACHE_DIR", "CONVERT_SECTIONS", "cache_dir", "convert_cached", "full_table"]

CACHE_DIR: Final = "cache"
#: Config sections a conversion reads (01 §4); `sources.drop` and the overlay act at materialise.
CONVERT_SECTIONS: Final = ("normalise", "rcaeval", "scrub", "status")
_META: Final = "case.json"  # written last: a cache entry without it is incomplete
_KEY_HEX: Final = 16


def full_table(contract: str, table: pa.Table) -> pa.Table:
    """`table` padded to the full contract: absent nullable columns become nulls (adapters may
    return a projection); a missing required column is a contract error."""
    schema: Any = io.arrow_schema(contract)
    columns: list[Any] = []
    for name in schema.names:
        field = schema.field(name)
        if name in table.column_names:
            columns.append(table.column(name))
        elif field.nullable:
            columns.append(pa.nulls(table.num_rows, type=field.type))
        else:
            raise ContractValidationError(contract, f"adapter table lacks required column {name!r}")
    return io.conform_table(contract, pa.Table.from_arrays(columns, schema=schema))


def cache_dir(data_root: Path, adapter: Adapter, ref: CaseRef, cfg: Mapping[str, Any]) -> Path:
    """The cache entry of `ref` for this adapter revision, scrub rules and convert config."""
    sections = {name: normalize(cfg[name]) for name in CONVERT_SECTIONS if name in cfg}
    key = sha256_json({"adapter": [adapter.name, adapter.version], "config": sections})[:_KEY_HEX]
    return Path(data_root) / CACHE_DIR / ref.dataset / ref.case_id / key


def _store(where: Path, case: CanonicalCase) -> None:
    for source, table in case.tables.items():
        contract = TELEMETRY_CONTRACTS[source]
        io.write_path(contract, full_table(contract, table), where / f"{source}.parquet")
    meta = {
        "system": case.system, "sources": dict(case.sources_present),
        "inputs": [list(i) for i in case.inputs], "adapter": [case.adapter_name, case.adapter_version],
        "scrub": list(case.scrub),
    }  # fmt: skip
    textio.write_bytes(where / _META, canonical_json(meta))


def _load(where: Path, ref: CaseRef, adapter: Adapter) -> CanonicalCase | None:
    if not (where / _META).is_file():
        return None
    meta = cast("dict[str, Any]", json.loads(textio.read_text(where / _META)))
    tables = {s: io.read_path(c, where / f"{s}.parquet") for s, c in TELEMETRY_CONTRACTS.items()}
    hint, source = adapter.alert_hint(ref)
    return CanonicalCase(
        system=meta["system"], tables=TelemetryTables(**cast("dict[str, pa.Table]", tables)),
        sources_present=meta["sources"], inputs=tuple((str(n), str(d), int(b)) for n, d, b in meta["inputs"]),
        adapter_name=str(meta["adapter"][0]), adapter_version=str(meta["adapter"][1]),
        scrub=(str(meta["scrub"][0]), int(meta["scrub"][1]), int(meta["scrub"][2])),
        t_alert_hint_ns=hint, hint_source=cast("Any", source),
    )  # fmt: skip


def convert_cached(adapter: Adapter, ref: CaseRef, cfg: Mapping[str, Any], data_root: Path) -> CanonicalCase:
    """The converted case from the cache, converting and storing it on a miss (or a bad entry)."""
    where = cache_dir(data_root, adapter, ref, cfg)
    try:
        cached = _load(where, ref, adapter)
    except (OSError, ValueError, KeyError, ContractValidationError):
        cached = None  # an unreadable entry is re-converted, never trusted
    if cached is not None:
        return cached
    case = adapter.convert(ref, cast("Any", cfg))
    _store(where, case)
    return case
