"""The `otlp_live` dataset adapter (entry point `veyltrace.adapters:otlp_live`; 01 §3.3).

A live case is a gateway snapshot (06 §3.4; layout agreed on #24):
`${VEYLTRACE_DATA}/live/<snapshot_id>/{metrics,logs,spans,events}.parquet` in canonical shape, plus
`snapshot.json` = `{snapshot_id, t_trigger_ns, trigger}`. The snapshot id is the canonical case
key, and the gateway lists the case in `index/live.json`. The tables were normalised and scrubbed
by the OTLP converter (§3.9) before they were buffered; both rule sets are applied again here, so
nothing reaches a run that Infralume's rules of this run would not let through. They are
idempotent, so a clean snapshot comes back unchanged. The trigger time is the alert hint
(`hint_source = live`). Metric keys are unique in a snapshot (the core writer refuses repeats),
so there are no equal points left to combine.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import numpy as np
import pyarrow as pa

from veyltrace_core import io, textio
from veyltrace_core.adapters import TELEMETRY_CONTRACTS, CanonicalCase, CaseRef, TelemetryTables
from veyltrace_core.errors import CaseRejected, ContractValidationError, UsageError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.ids import is_case_id
from veyltrace_infralume.index import read_index, resolve_entry
from veyltrace_infralume.names import NameRules
from veyltrace_infralume.scrub import Scrubber, ScrubRules

if TYPE_CHECKING:
    from veyltrace_core.config import EngineConfig

__all__ = ["DATASET", "SNAPSHOT_FILE", "OtlpLiveAdapter", "reapply"]

DATASET: Final = "live"
SNAPSHOT_FILE: Final = "snapshot.json"
#: `case_manifest.system` and the alias set of a live case: a snapshot does not name its system (#24).
_SYSTEM: Final = "other"
_SNAPSHOT_ID: Final = re.compile(r"[0-9a-f]{32}")  # 06 §3.4: first 32 hex of a SHA-256
#: Table → its `case_manifest.sources` name (03 §2.1: `traces`, not `spans`).
_SOURCE: Final = {"metrics": "metrics", "logs": "logs", "spans": "traces", "events": "events"}
#: Per table: the name columns (the first is the service) and the free-text columns.
_NAMES: Final = {s: ("service", "component") for s in ("metrics", "logs", "spans")} | {"events": ("entity",)}
_TEXT: Final = {"metrics": ("name",), "logs": ("body",), "spans": ("operation",), "events": ()}


def reapply(table: pa.Table, source: str, rules: NameRules, scrub: Scrubber) -> pa.Table:
    """`table` with name normalisation (01 §3.4) and scrubbing (§3.6) applied again; rows of
    dropped containers, fault-tool services and chaos events are removed and counted."""
    if table.num_rows == 0:
        return table
    keep = np.ones(table.num_rows, dtype=bool)
    columns: dict[str, Any] = {name: table.column(name) for name in table.column_names}
    for position, name in enumerate(_NAMES[source]):
        values = cast("list[str | None]", table.column(name).to_pylist())
        named = {v: rules.normalise(v) for v in sorted({v for v in values if v is not None})}
        out: list[str | None] = []
        for row, value in enumerate(values):
            found = None if value is None else named[value]
            keep[row] &= value is None or found is not None
            # A service column takes the service; a component or an entity keeps its own name.
            out.append(None if found is None else found.service if position == 0 else found.component)
        columns[name] = pa.array(out, pa.string())
    for name in _TEXT[source]:
        columns[name] = scrub.text_column(table.column(name))
    if source == "events":
        kinds = cast("list[str]", table.column("kind").to_pylist())
        details = cast("list[str]", table.column("detail_json").to_pylist())
        cleaned = [
            scrub.event_detail(k, json.loads(d)) if ok else None
            for k, d, ok in zip(kinds, details, keep, strict=True)
        ]
        keep &= np.array([d is not None for d in cleaned], dtype=bool)
        columns["detail_json"] = pa.array(cleaned, pa.string())
    else:
        values = cast("list[str | None]", table.column("attrs_json").to_pylist())
        columns["attrs_json"] = pa.array(
            [scrub.attrs_json(v) if ok else v for v, ok in zip(values, keep, strict=True)], pa.string()
        )
        scrub.dropped_rows += int((~keep).sum())  # event_detail counts its own drops
    kept = pa.Table.from_arrays(list(columns.values()), names=list(columns)).filter(pa.array(keep))
    return scrub.drop_rows(kept.cast(table.schema), _NAMES[source])


def _trigger_ns(folder: Path, snapshot_id: str) -> int:
    """`t_trigger_ns` of the snapshot in `folder`; a missing, unreadable or foreign `snapshot.json`
    rejects the case (01 §6), naming the file."""
    path = folder / SNAPSHOT_FILE
    try:
        meta: object = json.loads(textio.read_text(path))
    except (OSError, ValueError) as exc:
        raise CaseRejected("invalid_capture", f"{SNAPSHOT_FILE}: {type(exc).__name__}") from None
    fields = cast("dict[str, object]", meta) if isinstance(meta, dict) else {}
    trigger = fields.get("t_trigger_ns")
    if fields.get("snapshot_id") != snapshot_id or isinstance(trigger, bool) or not isinstance(trigger, int):
        raise CaseRejected(
            "invalid_capture", f"{SNAPSHOT_FILE}: needs this snapshot's id and an integer t_trigger_ns"
        )
    return trigger


@dataclass(frozen=True)
class OtlpLiveAdapter:
    """Adapter protocol implementation for the dataset `live` (Adapter, core)."""

    name: str = "otlp_live"
    version: str = "1"  # per-adapter revision (D-21): bump when converted tables change
    datasets: tuple[str, ...] = (DATASET,)
    cacheable: bool = True  # a snapshot id is derived from its content, so a cache entry never goes stale

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        """A case id, or a snapshot id (the canonical key), via the index the gateway writes."""
        if dataset != DATASET:
            raise UsageError(f"unknown live dataset {dataset!r}; expected {DATASET!r}")
        if not is_case_id(case) and _SNAPSHOT_ID.fullmatch(case) is None:
            raise UsageError(f"{case!r} is neither a 12-hex case id nor a 32-hex snapshot id")
        case_id = case if is_case_id(case) else make_case_id(case)
        location = resolve_entry(data_root, dataset, case_id)
        if make_case_id(location.name) != case_id:
            raise UsageError(f"the {dataset} index points {case_id} at another snapshot")
        return CaseRef(dataset=dataset, case_id=case_id, canonical_key=location.name, location=location)

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        """Every snapshot's case id, sorted."""
        if dataset != DATASET:
            raise UsageError(f"unknown live dataset {dataset!r}; expected {DATASET!r}")
        return sorted(read_index(data_root, dataset))

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        """Read the snapshot's four tables and apply the name and scrub rules again (01 §3.3)."""
        if ref.location is None:
            raise UsageError(f"live case {ref.case_id} has no location")
        trigger = _trigger_ns(ref.location, ref.canonical_key)
        rules = NameRules.from_config(cfg, _SYSTEM)
        scrub = Scrubber(ScrubRules.from_config(cfg), (ref.canonical_key,))
        tables: dict[str, pa.Table] = {}
        used: list[tuple[str, Path]] = []
        for source, contract in TELEMETRY_CONTRACTS.items():
            path = ref.location / f"{source}.parquet"
            if not path.is_file():  # 01 §6: a missing source is an empty one
                continue
            try:
                raw = cast("pa.Table", io.read_path(contract, path, validate=True))
            except (ContractValidationError, pa.ArrowException) as exc:
                raise CaseRejected("invalid_capture", f"{path.name}: {exc}") from None
            tables[source] = reapply(raw, source, rules, scrub)
            if tables[source].num_rows:
                used.append((f"{_SOURCE[source]}/{path.name}", path))
        bundle = TelemetryTables.from_tables(**tables)
        present = {_SOURCE[source]: table.num_rows > 0 for source, table in bundle.items()}
        if not any(present.values()):
            raise CaseRejected("no_telemetry", f"snapshot of case {ref.case_id} has no rows")
        return CanonicalCase(
            system=_SYSTEM,
            tables=bundle,
            sources_present=present,
            inputs=tuple(sorted((name, sha256_file(path), path.stat().st_size) for name, path in used)),
            adapter_name=self.name,
            adapter_version=self.version,
            scrub=scrub.counts,
            t_alert_hint_ns=trigger,
            hint_source="live",
        )

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        """The snapshot's trigger time in ns, `live` (01 §3.7)."""
        if ref.location is None:
            return None, "none"
        return _trigger_ns(ref.location, ref.canonical_key), "live"
