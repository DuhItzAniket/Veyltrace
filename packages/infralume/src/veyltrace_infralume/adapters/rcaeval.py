"""The `rcaeval` dataset adapter (entry point `veyltrace.adapters:rcaeval`; 01 §3.3).

Resolves RCAEval cases through the private index, detects the layout (Hugging Face Parquet or
Zenodo CSV), reads only that layout's allow-listed files, so the label files (`cases.parquet`,
`root_cause.txt`) can never be opened, and converts them with `rcaeval_tables`. The folder name,
which *is* the label, leaves the adapter only as the opaque `case_id`; its tokens are scrubbed
from every output (01 §3.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from veyltrace_core import textio
from veyltrace_core.adapters import CanonicalCase, CaseRef, TelemetryTables
from veyltrace_core.config import data_root
from veyltrace_core.errors import CaseRejected, ConfigError, UsageError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.ids import is_case_id
from veyltrace_infralume.adapters.rcaeval_tables import (
    NS,
    SPAN_COLUMNS,
    logs_table,
    metrics_table,
    spans_table,
)
from veyltrace_infralume.casekey import parse_case_dir, parse_suite
from veyltrace_infralume.index import read_index, resolve_entry
from veyltrace_infralume.names import NameRules
from veyltrace_infralume.scrub import Scrubber, ScrubRules, folder_tokens
from veyltrace_infralume.status import StatusRules

if TYPE_CHECKING:
    from veyltrace_core.config import EngineConfig

__all__ = ["HF", "ZENODO", "ForbiddenFile", "Layout", "RcaevalAdapter"]

# pyarrow-stubs type the parquet and csv readers with Unknown parts; core's io.py uses Any aliases.
_pq: Any = pq

_csv: Any = pacsv

HINT_FILE: Final = "inject_time.txt"

#: CSV columns read as strings, so IDs keep leading zeros (01 §3.3).
_CSV_STRINGS: Final = (*SPAN_COLUMNS[:6], "container_name", "message", "pod_name", "level")


class ForbiddenFile(PermissionError):
    """The adapter tried to open a file outside its layout's allow-list (01 §3.3)."""


@dataclass(frozen=True)
class Layout:
    """One physical layout: its metrics file (first present wins) and its logs and traces files."""

    name: str
    metrics: tuple[str, ...]
    logs: str
    traces: str

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset({*self.metrics, self.logs, self.traces, HINT_FILE})


HF: Final = Layout("hf", ("metrics.parquet",), "logs.parquet", "traces.parquet")

#: Zenodo: `simple_metrics.csv` (RE2/RE3) or `data.csv` (RE1); raw `metrics.csv` is never read.
ZENODO: Final = Layout("zenodo", ("simple_metrics.csv", "data.csv"), "logs.csv", "traces.csv")


@dataclass(frozen=True)
class _Case:
    """One case directory, read only through its layout's allow-list."""

    location: Path
    layout: Layout

    def path(self, name: str) -> Path | None:
        if name not in self.layout.allowed:
            raise ForbiddenFile(f"{name!r} is not on the {self.layout.name} allow-list")
        found = self.location / name
        return found if found.is_file() else None

    def read(self, name: str, columns: tuple[str, ...] = ()) -> tuple[pa.Table, Path | None]:
        """The file as a table (no rows when absent or header-only) and its path if it has rows."""
        path = self.path(name)
        if path is None:
            return pa.Table.from_arrays([], names=[]), None
        if path.suffix == ".parquet":
            present = set(cast("list[str]", _pq.read_schema(path).names))
            table = cast(
                "pa.Table", _pq.read_table(path, columns=[c for c in columns if c in present] or None)
            )
        else:
            types = dict.fromkeys(_CSV_STRINGS, pa.string())
            table = cast(
                "pa.Table",
                _csv.read_csv(
                    path, convert_options=_csv.ConvertOptions(column_types=types, strings_can_be_null=True)
                ),
            )
        return table, (path if table.num_rows else None)


def _layout(location: Path, cfg: Mapping[str, Any]) -> Layout:
    """The layout by file presence (01 §3.3), or the one `rcaeval.layout` forces."""
    section = cast("Mapping[str, Any]", cfg["rcaeval"])
    wanted, table = str(section["layout"]), str(section["metrics_table"])
    if wanted not in ("auto", HF.name, ZENODO.name) or table != "simple":
        raise ConfigError(
            f"rcaeval.layout must be auto|hf|zenodo and metrics_table simple, got {wanted!r}, {table!r}"
        )
    for layout in (HF, ZENODO):
        if wanted in ("auto", layout.name) and any((location / m).is_file() for m in layout.metrics):
            return layout
    raise CaseRejected("unsupported_format", f"no {wanted} RCAEval metrics file in the case directory")


def _input(source: str, path: Path | None) -> tuple[str, str, int] | None:
    return None if path is None else (f"{source}/{path.name}", sha256_file(path), path.stat().st_size)


@dataclass(frozen=True)
class RcaevalAdapter:
    """Adapter protocol implementation for datasets re1-*, re2-*, re3-* (Adapter, core)."""

    name: str = "rcaeval"
    version: str = "1"  # per-adapter revision (D-21): bump when converted tables change
    datasets: tuple[str, ...] = ("re1-*", "re2-*", "re3-*")
    cacheable: bool = True

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        """A case id, or a canonical key such as re2ob_cartservice_cpu_1, via the private index."""
        parse_suite(dataset)
        key = None if is_case_id(case) else parse_case_dir([case])
        if key is not None and key.suite != dataset:
            raise UsageError(f"case {case!r} belongs to {key.suite}, not {dataset}")
        if key is None and not is_case_id(case):
            raise UsageError(f"{case!r} is neither a 12-hex case id nor an RCAEval case name")
        case_id = key.case_id if key is not None else case
        location = resolve_entry(data_root, dataset, case_id)
        found = parse_case_dir(location.parts)
        if found is None or found.case_id != case_id:
            raise UsageError(f"the {dataset} index points {case_id} at a directory of another case")
        return CaseRef(dataset=dataset, case_id=case_id, canonical_key=found.key, location=location)

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        """Every fetched case id of `dataset`, sorted."""
        parse_suite(dataset)
        return sorted(read_index(data_root, dataset))

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        """Read the case into canonical, normalised, scrubbed tables (01 §3.3–3.6)."""
        if ref.location is None:
            raise UsageError(f"rcaeval case {ref.case_id} has no location")
        case = _Case(ref.location, _layout(ref.location, cfg))
        key = parse_case_dir(ref.location.parts)
        rules = NameRules.from_config(cfg, key.system if key is not None else "other")
        root = data_root()
        rel = (
            ref.location.relative_to(root).as_posix()
            if ref.location.is_relative_to(root)
            else ref.location.name
        )
        scrub = Scrubber(ScrubRules.from_config(cfg), folder_tokens(ref.canonical_key, rel))
        metrics_file = next(
            (m for m in case.layout.metrics if case.path(m) is not None), case.layout.metrics[0]
        )
        raw_m, path_m = case.read(metrics_file)
        raw_l, path_l = case.read(case.layout.logs)
        raw_s, path_s = case.read(case.layout.traces, SPAN_COLUMNS)
        tables = TelemetryTables.from_tables(
            metrics=metrics_table(raw_m, rules, scrub), logs=logs_table(raw_l, rules, scrub),
            spans=spans_table(raw_s, rules, StatusRules.from_config(cfg), scrub),
        )  # fmt: skip
        present = {"metrics": tables.metrics.num_rows > 0, "logs": tables.logs.num_rows > 0,
                   "traces": tables.spans.num_rows > 0, "events": False}  # fmt: skip
        if not any(present.values()):
            raise CaseRejected("no_telemetry", f"case {ref.case_id} has no metric, log or span rows")
        paths = (("metrics", path_m), ("logs", path_l), ("traces", path_s))
        inputs = [i for s, p in paths if present[s] and (i := _input(s, p)) is not None]
        hint, source = self.alert_hint(ref)
        return CanonicalCase(
            system=cast("Any", key.system if key is not None else "other"), tables=tables,
            sources_present=present, inputs=tuple(sorted(inputs)), adapter_name=self.name,
            adapter_version=self.version, scrub=scrub.counts, t_alert_hint_ns=hint,
            hint_source=cast("Any", source),
        )  # fmt: skip

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        """`inject_time.txt` (integer Unix seconds on line 1, as RCAEval's main.py reads it) in ns,
        `oracle`; (None, `none`) if the case has no such file."""
        path = None if ref.location is None else ref.location / HINT_FILE
        if path is None or not path.is_file():
            return None, "none"
        first = textio.read_text(path).strip().splitlines()
        try:
            return int(first[0].strip()) * NS, "oracle"
        except (IndexError, ValueError):
            raise CaseRejected("no_hint", f"{HINT_FILE} of case {ref.case_id} is not an integer") from None
