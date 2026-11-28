"""The `nezha` dataset adapter (entry point `veyltrace.adapters:nezha`; 01 §3.3).

A case is one entry of a day's fault list (`nezha_layout`). The adapter reads the day's pod metric
files and the three minute files of logs and traces that exist for the fault, keeps the rows of the
case's slice, reshapes them (`nezha_tables`) and converts them with the shared `rcaeval_tables`
functions. Only allow-listed files are opened; the fault list is read for its times alone, which
give the slice bounds and the oracle hint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from veyltrace_core.adapters import CanonicalCase, CaseRef, TelemetryTables
from veyltrace_core.errors import CaseRejected, UsageError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.ids import is_case_id
from veyltrace_core.io import empty_table
from veyltrace_core.log import get_logger
from veyltrace_infralume.adapters.nezha_layout import (
    DATASETS,
    SliceRule,
    fault_times_ns,
    nezha_key,
    parse_key,
    stems_for,
    window_ns,
)
from veyltrace_infralume.adapters.nezha_tables import raw_logs, raw_metrics, raw_spans
from veyltrace_infralume.adapters.rcaeval_tables import logs_table, metrics_table, spans_table
from veyltrace_infralume.index import read_index, resolve_entry
from veyltrace_infralume.names import NameRules, strip_pod_suffix
from veyltrace_infralume.scrub import Scrubber, ScrubRules, folder_tokens
from veyltrace_infralume.status import StatusRules

if TYPE_CHECKING:
    from veyltrace_core.config import EngineConfig

__all__ = ["ForbiddenFile", "NezhaAdapter"]

_pc: Any = pc
_csv: Any = pacsv
_log = get_logger(__name__)

#: Files the adapter may open, by directory (01 §3.3). `front_service.csv`, `dependency.csv`,
#: `source_50.csv`, `destination_50.csv` and `traceid/` are not read.
_ALLOWED: Final = {
    "metric": re.compile(r"[a-z0-9][a-z0-9.-]*_metric\.csv"),
    "log": re.compile(r"\d{2}_\d{2}_log\.csv"),
    "trace": re.compile(r"\d{2}_\d{2}_trace\.csv"),
}
_METRIC_SUFFIX: Final = "_metric.csv"
#: Columns read as strings, so ids keep leading zeros and `Time` keeps its text.
_STRINGS: Final = (
    "TraceID",
    "SpanID",
    "ParentID",
    "PodName",
    "OperationName",
    "Time",
    "Log",
    "Container",
    "Node",
)


class ForbiddenFile(PermissionError):
    """The adapter tried to open a file outside its allow-list (01 §3.3)."""


def _open(day: Path, kind: str, name: str) -> Path | None:
    """The allow-listed file `<day>/<kind>/<name>` if it exists; ForbiddenFile for any other name."""
    pattern = _ALLOWED.get(kind)
    if pattern is None or pattern.fullmatch(name) is None:
        raise ForbiddenFile(f"{kind}/{name} is not on the nezha allow-list")
    path = day / kind / name
    return path if path.is_file() else None


def _read(path: Path) -> pa.Table:
    """A CSV file as a table; id and text columns as strings, quoted newlines allowed (log bodies).
    A row with the wrong number of columns is skipped and logged as a data-quality drop (01 §6):
    one of the 8.3 million published log rows is two lines spliced together."""
    skipped: list[int] = []

    def skip(row: Any) -> str:
        skipped.append(int(row.number or 0))
        return "skip"

    table = cast(
        "pa.Table",
        _csv.read_csv(
            path,
            parse_options=_csv.ParseOptions(newlines_in_values=True, invalid_row_handler=skip),
            convert_options=_csv.ConvertOptions(
                column_types=dict.fromkeys(_STRINGS, pa.string()), strings_can_be_null=True
            ),
        ),
    )
    if skipped:
        _log.info(
            "infralume.rows_dropped", source=path.parent.name, rows=len(skipped), reason="malformed_csv_row"
        )
    return table


def _inside(table: pa.Table, column: str, window: tuple[int, int]) -> pa.Table:
    """Rows whose ns `column` lies in the half-open window; rows without a time are dropped."""
    if column not in table.column_names:
        return table.slice(0, 0)
    t = np.asarray(_pc.cast(table.column(column), pa.int64()).fill_null(-1).to_numpy(zero_copy_only=False))
    return table.filter(pa.array((t >= window[0]) & (t < window[1])))


def _minute_files(day: Path, kind: str, window: tuple[int, int]) -> list[Path]:
    """The day's allow-listed `kind` files that can hold rows of `window`, in time order."""
    suffix = f"_{kind}.csv"
    names = {p.name.removesuffix(suffix): p.name for p in sorted((day / kind).glob(f"*{suffix}"))}
    stems = [stem for stem, name in names.items() if _ALLOWED[kind].fullmatch(name)]
    found = (_open(day, kind, names[stem]) for stem in stems_for(day.name, stems, window))
    return [path for path in found if path is not None]


def _unique_rows(table: pa.Table) -> pa.Table:
    """`table` without repeated rows. Neighbouring minute files overlap by a second or two, so a
    log line can be published twice (24,717 of 4.2 million rows); counted twice it would look like a
    step in log rate. Dropped rows are logged as a data-quality drop (01 §6)."""
    if table.num_rows == 0:
        return table
    unique = table.group_by(table.column_names, use_threads=False).aggregate([])
    if unique.num_rows != table.num_rows:
        _log.info(
            "infralume.rows_dropped",
            source="logs",
            rows=table.num_rows - unique.num_rows,
            reason="duplicate_row",
        )
    return unique.select(table.column_names).cast(table.schema)


def _input_names(used: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """`case_manifest.inputs` names (03 §2.1). Minute files are named by their position among the
    case's files, `logs/minute-0.csv`, …: their real names are the clock minute around the fault,
    which would give the fault time to every reader of the manifest and the receipt even where the
    hint is blanked (detected protocol, shifted alerts). Pod metric files keep their names."""
    counts: dict[str, int] = {}
    named: list[tuple[str, Path]] = []
    for source, path in used:
        if source == "metrics":
            named.append((f"{source}/{path.name}", path))
            continue
        position = counts.get(source, 0)
        counts[source] = position + 1
        named.append((f"{source}/minute-{position}.csv", path))
    return named


def _concat(tables: list[pa.Table], contract: str) -> pa.Table:
    return pa.concat_tables(tables) if tables else empty_table(contract)


@dataclass(frozen=True)
class NezhaAdapter:
    """Adapter protocol implementation for datasets nezha-ob and nezha-tt (Adapter, core)."""

    name: str = "nezha"
    version: str = "1"  # per-adapter revision (D-21): bump when converted tables change
    datasets: tuple[str, ...] = ("nezha-*",)
    cacheable: bool = True

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        """A case id, or a canonical key such as nezha-ob-2022-08-22-0, via the private index."""
        if dataset not in DATASETS:
            raise UsageError(f"unknown Nezha dataset {dataset!r}; expected one of {', '.join(DATASETS)}")
        parsed = None if is_case_id(case) else parse_key(case)
        if parsed is None and not is_case_id(case):
            raise UsageError(f"{case!r} is neither a 12-hex case id nor a Nezha case key")
        if parsed is not None and f"nezha-{parsed[0]}" != dataset:
            raise UsageError(f"case {case!r} belongs to nezha-{parsed[0]}, not {dataset}")
        case_id = make_case_id(case) if parsed is not None else case
        location = resolve_entry(data_root, dataset, case_id)
        key = self._key(dataset, location)
        if make_case_id(key) != case_id:
            raise UsageError(f"the {dataset} index points {case_id} at another case")
        return CaseRef(dataset=dataset, case_id=case_id, canonical_key=key, location=location)

    @staticmethod
    def _key(dataset: str, location: Path) -> str:
        """The canonical key of an index location `<day directory>/<index>`."""
        if not location.name.isdigit():
            raise UsageError(f"the {dataset} index entry {location.name!r} is not a fault index")
        return nezha_key(dataset.removeprefix("nezha-"), location.parent.name, int(location.name))

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        """Every fetched case id of `dataset`, sorted."""
        if dataset not in DATASETS:
            raise UsageError(f"unknown Nezha dataset {dataset!r}; expected one of {', '.join(DATASETS)}")
        return sorted(read_index(data_root, dataset))

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        """Read the case's slice into canonical, normalised, scrubbed tables (01 §3.3–3.6)."""
        if ref.location is None:
            raise UsageError(f"nezha case {ref.case_id} has no location")
        day, index = ref.location.parent, int(ref.location.name)
        system = ref.dataset.removeprefix("nezha-")
        times = fault_times_ns(day)
        window = window_ns(times, index, SliceRule.from_config(cfg))
        rules = NameRules.from_config(cfg, system)
        scrub = Scrubber(ScrubRules.from_config(cfg), folder_tokens(ref.canonical_key, ""))
        # case_manifest.inputs lists files behind emitted rows (03 §2.1), so not the fault list.
        used: list[tuple[str, Path]] = []

        metrics: list[pa.Table] = []
        for path in sorted((day / "metric").glob(f"*{_METRIC_SUFFIX}")):
            if _open(day, "metric", path.name) is None:
                continue
            service = strip_pod_suffix(path.name.removesuffix(_METRIC_SUFFIX))
            table = metrics_table(raw_metrics(_read(path), service, window), rules, scrub)
            if table.num_rows:
                metrics.append(table)
                used.append(("metrics", path))

        logs: list[pa.Table] = []
        for path in _minute_files(day, "log", window):
            table = logs_table(raw_logs(_inside(_read(path), "TimeUnixNano", window)), rules, scrub)
            if table.num_rows:
                logs.append(table)
                used.append(("logs", path))
        spans: list[pa.Table] = []
        for path in _minute_files(day, "trace", window):
            raw = raw_spans(_inside(_read(path), "StartTimeUnixNano", window))
            if raw.num_rows:
                spans.append(raw)
                used.append(("traces", path))
        # One call over all minute files: a span repeated across files is de-duplicated once.
        span_table = (
            spans_table(pa.concat_tables(spans), rules, StatusRules.from_config(cfg), scrub)
            if spans
            else empty_table("telemetry.spans")
        )
        tables = TelemetryTables.from_tables(
            metrics=_concat(metrics, "telemetry.metrics"),
            logs=_unique_rows(_concat(logs, "telemetry.logs")),
            spans=span_table,
        )
        present = {
            "metrics": tables.metrics.num_rows > 0,
            "logs": tables.logs.num_rows > 0,
            "traces": tables.spans.num_rows > 0,
            "events": False,
        }
        if not any(present.values()):
            raise CaseRejected("no_telemetry", f"case {ref.case_id} has no metric, log or span rows")
        inputs = sorted(
            (name, sha256_file(path), path.stat().st_size)
            for name, path in _input_names(used)
            if present[name.partition("/")[0]]
        )
        return CanonicalCase(
            system=cast("Any", system),
            tables=tables,
            sources_present=present,
            inputs=tuple(inputs),
            adapter_name=self.name,
            adapter_version=self.version,
            scrub=scrub.counts,
            t_alert_hint_ns=times[index],
            hint_source=cast("Any", "oracle"),
        )

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        """The fault-list time of the case in ns, `oracle` (01 §3.3)."""
        if ref.location is None:
            return None, "none"
        return fault_times_ns(ref.location.parent)[int(ref.location.name)], "oracle"
