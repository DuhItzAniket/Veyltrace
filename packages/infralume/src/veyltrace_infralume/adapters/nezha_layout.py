"""The Nezha data layout (01 §3.3 `nezha`): days, fault times, case keys, slices. No network.

Nezha (IntelligentDDS/Nezha, MIT) publishes one directory per collection day under `rca_data/`:
`<date>-fault_list.json`, `metric/<pod>_metric.csv` (one row per minute for the whole day), and
`log/HH_MM_log.csv` and `trace/HH_MM_trace.csv`, which exist only for the fault's minute and the two
after it (neighbouring files overlap by a second or two). A case is one entry of a day's fault
list. Its telemetry is the slice
[t_fault − 12 min, t_fault + 12 min), clipped to the midpoint to each neighbouring fault of the day,
so no row belongs to two cases.

The fault list is read for `inject_time` only. `inject_timestamp` is not used: on the Train Ticket
days it is eight hours off and repeats between entries, while `inject_time` (UTC) agrees with the
file names and the log timestamps. The root-cause fields are never read (package AGENTS).
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Final, cast

from veyltrace_core import textio
from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_infralume.index import write_index

__all__ = [
    "DATASETS",
    "HALF_SPAN_NS",
    "KEY_FORMAT",
    "MINUTE_FILES",
    "SRC",
    "NezhaCase",
    "build_index",
    "day_system",
    "discover",
    "fault_list_name",
    "fault_times_ns",
    "minute_stems",
    "nezha_key",
    "parse_key",
    "stem_time_ns",
    "stems_for",
    "window_ns",
]

NS: Final = 1_000_000_000
#: Where the extracted `rca_data/` lives under the data root (the fetcher writes it there).
SRC: Final = ("nezha", "src", "rca_data")
#: Dataset ids (03 §2.1): Online Boutique (`hipster`) and Train Ticket (`ts`).
DATASETS: Final = ("nezha-ob", "nezha-tt")
#: The canonical case key (01 §3.2): index = 0-based position in the day's fault list, in time order.
KEY_FORMAT: Final = "nezha-{system}-{date}-{index}"
#: 01 §3.3: the slice mirrors RCAEval's 12 + 12 minutes around the fault.
HALF_SPAN_NS: Final = 12 * 60 * NS
#: Log and trace files exist for the fault's minute and the next two (verified on all 101 faults).
MINUTE_FILES: Final = 3
#: How far a minute file's rows can lie from the minute it is named after (see `stems_for`).
FILE_SLACK_NS: Final = 60 * NS
#: Pod names of Train Ticket start with `ts-`; Online Boutique's never do.
TT_PREFIX: Final = "ts-"

_DAY: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_KEY: Final = re.compile(r"nezha-(ob|tt)-(\d{4}-\d{2}-\d{2})-(\d+)")
_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class NezhaCase:
    """One fault-list entry: its dataset, canonical key and index path under the data root."""

    dataset: str
    key: str
    relpath: str  # `nezha/src/rca_data/<date>/<index>`: the day directory plus the entry's index

    @property
    def case_id(self) -> str:
        return make_case_id(self.key)


def nezha_key(system: str, date: str, index: int) -> str:
    """The canonical key of the `index`-th fault of `date` (01 §3.2)."""
    return KEY_FORMAT.format(system=system, date=date, index=index)


def parse_key(key: str) -> tuple[str, str, int] | None:
    """(system, date, index) of a canonical key, or None if `key` is not one."""
    found = _KEY.fullmatch(key)
    return (found.group(1), found.group(2), int(found.group(3))) if found else None


def fault_list_name(date: str) -> str:
    return f"{date}-fault_list.json"


def fault_times_ns(day_dir: Path) -> tuple[int, ...]:
    """The day's fault times in ns, ascending; a case's index is its position here. Only
    `inject_time` is taken from each entry, and no two entries may share it."""
    path = day_dir / fault_list_name(day_dir.name)
    raw: object = json.loads(textio.read_text(path))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected an object of hour -> fault entries")
    hours = cast("dict[str, object]", raw)
    times: list[int] = []
    for hour in sorted(hours):
        entries = hours[hour]
        if not isinstance(entries, list):
            raise ConfigError(f"{path}: hour {hour!r} is not a list")
        for entry in cast("list[object]", entries):
            stamp = cast("dict[str, object]", entry).get("inject_time") if isinstance(entry, dict) else None
            if not isinstance(stamp, str):
                raise ConfigError(f"{path}: a fault entry has no inject_time")
            try:
                when = datetime.strptime(stamp, _TIME_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                raise ConfigError(f"{path}: inject_time {stamp!r} is not {_TIME_FORMAT}") from None
            times.append(int(when.timestamp()) * NS)
    times.sort()  # by parsed time, not by the hour keys' text ("10" sorts before "9")
    if any(b <= a for a, b in itertools.pairwise(times)):
        raise ConfigError(f"{path}: two faults share one inject_time")
    return tuple(times)


def day_system(day_dir: Path) -> str:
    """`tt` if the day's pod metric files are Train Ticket's, else `ob`."""
    names = sorted(p.name for p in (day_dir / "metric").glob("*_metric.csv"))
    if not names:
        raise ConfigError(f"{day_dir}: no pod metric file")
    return "tt" if any(n.startswith(TT_PREFIX) for n in names) else "ob"


def window_ns(times: tuple[int, ...], index: int) -> tuple[int, int]:
    """The half-open slice [lo, hi) of fault `index`: ±12 min, clipped to the midpoints to the
    neighbouring faults of the day (01 §3.3)."""
    if not 0 <= index < len(times):
        raise UsageError(f"fault index {index} is outside the day's {len(times)} faults")
    t = times[index]
    lo, hi = t - HALF_SPAN_NS, t + HALF_SPAN_NS
    if index > 0:
        lo = max(lo, (times[index - 1] + t) // 2)
    if index + 1 < len(times):
        hi = min(hi, (t + times[index + 1]) // 2)
    return lo, hi


def minute_stems(t_ns: int) -> tuple[str, ...]:
    """`HH_MM` of the fault's minute and the following ones that have log and trace files."""
    start = datetime.fromtimestamp(t_ns // NS, UTC).replace(second=0)
    return tuple((start + timedelta(minutes=k)).strftime("%H_%M") for k in range(MINUTE_FILES))


def stem_time_ns(date: str, stem: str) -> int:
    """The minute a log or trace file is named after (`HH_MM` on `date`, UTC) in ns."""
    return int(datetime.strptime(f"{date} {stem}", "%Y-%m-%d %H_%M").replace(tzinfo=UTC).timestamp()) * NS


def stems_for(date: str, stems: Iterable[str], window: tuple[int, int]) -> list[str]:
    """The `stems` whose file can hold rows of the half-open `window`, in time order. A file named
    after minute M holds rows from about M − 41 s to M + 20 s (measured on all four days), so every
    file with M in [lo − 1 min, hi + 1 min] is read and the rows are filtered afterwards. This
    includes neighbouring faults' files: with faults a few minutes apart, a fault's last file has
    rows past the midpoint, which belong to the next case."""
    timed = sorted((stem_time_ns(date, s), s) for s in stems)
    return [s for m, s in timed if window[0] - FILE_SLACK_NS <= m <= window[1] + FILE_SLACK_NS]


def discover(data_root: Path) -> list[NezhaCase]:
    """Every case under `<data root>/nezha/src/rca_data`, days and indexes in sorted order."""
    root = Path(data_root).joinpath(*SRC)
    days = sorted(p for p in root.iterdir() if p.is_dir() and _DAY.fullmatch(p.name)) if root.is_dir() else []
    cases: list[NezhaCase] = []
    for day in days:
        system = day_system(day)
        for index in range(len(fault_times_ns(day))):
            rel = PurePosixPath(*SRC, day.name, str(index)).as_posix()
            cases.append(NezhaCase(f"nezha-{system}", nezha_key(system, day.name, index), rel))
    return cases


def build_index(data_root: Path) -> dict[str, int]:
    """Write the private index of both Nezha datasets (01 §2); cases per dataset."""
    by_dataset: dict[str, dict[str, str]] = {d: {} for d in DATASETS}
    for case in discover(data_root):
        by_dataset[case.dataset][case.case_id] = case.relpath
    for dataset, entries in by_dataset.items():
        if entries:
            write_index(Path(data_root), dataset, entries)
    return {dataset: len(entries) for dataset, entries in by_dataset.items()}
