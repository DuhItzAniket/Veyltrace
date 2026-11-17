"""Engine entry point of Infralume (registered as `veyltrace.engines:infralume`; 01 §3.1).

Pipeline step 0: resolve the case through its dataset adapter, convert it (through the cache when
the adapter allows), then materialise it into the run directory: drop the sources named in
`sources.drop` (dropped and absent sources look the same: zero rows, `false`), merge the events
overlay named by `events.overlay_path`, blank the hint under the detected protocol, and write
`case_manifest` and the four telemetry tables over the full available span. Core's alert step
reads the hint and chooses the windows; Infralume never reads `alert.shift_s`. Never imports the
fetcher (the network exemption is `veyltrace_infralume.fetch`).
"""

from __future__ import annotations

from typing import Any, Final, cast

import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.adapters import SOURCE_NAMES, TELEMETRY_CONTRACTS, CanonicalCase, adapter_for
from veyltrace_core.config import data_root
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import CaseRejected, ConfigError, ContractValidationError
from veyltrace_core.log import get_logger
from veyltrace_infralume.cache import convert_cached, full_table
from veyltrace_infralume.names import NameRules
from veyltrace_infralume.overlay import load_overlay
from veyltrace_infralume.scrub import Scrubber, ScrubRules, folder_tokens

__all__ = ["run"]

_log = get_logger(__name__)
_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as core's io.py)
#: Telemetry table attribute → its `sources` key (03 §2.1: spans are the `traces` source).
SOURCE_OF: Final = {"metrics": "metrics", "logs": "logs", "spans": "traces", "events": "events"}
#: Time columns of each table for data_start/data_end (01 §3.8: span start and end included).
_TIME_COLUMNS: Final = {
    "metrics": ("t_ns",),
    "logs": ("t_ns",),
    "spans": ("start_ns", "end_ns"),
    "events": ("t_ns",),
}


def _dropped(ctx: RunContext) -> frozenset[str]:
    drop = frozenset(str(s) for s in cast("list[Any]", ctx.config["sources"]["drop"]))
    if unknown := sorted(drop - set(SOURCE_NAMES)):
        raise ConfigError(
            f"infralume.sources.drop names unknown sources {unknown}; known: {list(SOURCE_NAMES)}"
        )
    return drop


def _materialise(
    ctx: RunContext, case: CanonicalCase, tokens: tuple[str, ...]
) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Write the manifest and the tables (dropped sources as zero rows, overlay events merged);
    returns the outputs and the row count of each table as written, so a dropped source reports
    0 rows. `tokens` are the case's folder tokens, scrubbed from overlay details."""
    drop = _dropped(ctx)
    tables = {s: t if SOURCE_OF[s] not in drop else t.slice(0, 0) for s, t in case.tables.items()}
    present = {s: bool(case.sources_present[s]) and s not in drop for s in SOURCE_NAMES}
    inputs, scrubbed = list(case.inputs), case.scrub
    overlay = ctx.config["events"]["overlay_path"]
    if overlay is not None and "events" not in drop:  # dropping events drops the overlay with them
        scrub = Scrubber(ScrubRules.from_config(ctx.config), tokens)
        extra, entry = load_overlay(str(overlay), NameRules.from_config(ctx.config, case.system), scrub)
        tables["events"] = pa.concat_tables(
            [full_table(TELEMETRY_CONTRACTS["events"], tables["events"]), extra]
        )
        present["events"] = present["events"] or extra.num_rows > 0
        inputs = sorted([*inputs, entry])
        scrubbed = (scrubbed[0], scrubbed[1] + scrub.dropped_attributes, scrubbed[2] + scrub.dropped_rows)
    bounds: list[tuple[int, int]] = []
    for source, table in tables.items():
        if table.num_rows:
            first, last = _TIME_COLUMNS[source][0], _TIME_COLUMNS[source][-1]
            bounds.append(
                (int(_pc.min(table.column(first)).as_py()), int(_pc.max(table.column(last)).as_py()))
            )
    if not bounds:
        raise CaseRejected("no_telemetry", f"case {ctx.case_id} has no rows in any non-dropped source")
    start, end = min(b[0] for b in bounds), max(b[1] for b in bounds)
    hint, hint_source = case.t_alert_hint_ns, case.hint_source
    if str(ctx.config.core["alert"]["protocol"]) == "detected":
        hint, hint_source = None, "none"  # 03 §2.1: the injection time never reaches detected runs
    elif hint is not None and not start <= hint <= end:
        _log.warning("infralume.hint_outside_span", case_id=ctx.case_id)  # the alert step decides (01 §6)
    services: set[str] = set()
    for source in ("metrics", "logs", "spans"):
        services.update(cast("list[str]", tables[source].column("service").to_pylist()))
    manifest: dict[str, Any] = {
        "schema_version": CONTRACTS["case_manifest"].version, "case_id": ctx.case_id, "dataset": ctx.dataset,
        "system": case.system, "t_alert_hint_ns": hint, "hint_source": hint_source,
        "data_start_ns": start, "data_end_ns": end, "sources": present,
        "services": sorted(services),  # str order is code-point order, which is UTF-8 byte order
        "inputs": [{"name": n, "sha256": d, "bytes": b}
                   for n, d, b in inputs if n.split("/")[0] not in drop],
        "adapter": {"name": case.adapter_name, "version": case.adapter_version},
        "scrub": dict(zip(("rules_version", "dropped_attributes", "dropped_rows"), scrubbed, strict=True)),
    }  # fmt: skip
    out = [("case_manifest", ctx.write("case_manifest", manifest))]
    for source, table in tables.items():
        contract = TELEMETRY_CONTRACTS[source]
        out.append((contract, ctx.write(contract, full_table(contract, table))))
    return out, {f"rows_{source}": table.num_rows for source, table in tables.items()}


def run(ctx: RunContext) -> EngineResult:
    """Ingest the run's case into `case_manifest.json` and `telemetry/*.parquet` (01 §2)."""
    adapter = adapter_for(ctx.dataset)
    root = data_root()
    ref = adapter.resolve(ctx.dataset, ctx.case_id, root)
    if ref.case_id != ctx.case_id:
        raise ContractValidationError(
            "case_manifest", f"{adapter.name} resolved {ctx.case_id} to {ref.case_id}"
        )
    case = (
        convert_cached(adapter, ref, ctx.config, root)
        if adapter.cacheable
        else adapter.convert(ref, ctx.config)
    )
    rel = ""
    if ref.location is not None:
        inside = ref.location.is_relative_to(root)
        rel = ref.location.relative_to(root).as_posix() if inside else ref.location.name
    outputs, rows = _materialise(ctx, case, folder_tokens(ref.canonical_key, rel))
    return EngineResult(engine="infralume", status="ok", outputs=tuple(sorted(outputs)), metrics=rows)
