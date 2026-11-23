"""The live buffer (06 §3.4): per source, Arrow tables in canonical shape with a data-time index.

Why data time, not arrival time: the snapshot cuts a window of data time around the trigger, and
retention must keep the 20-minute baseline plus the incident window of 02 §5.1 whatever the
Collector's batching. The newest data time held is the buffer's "now"; batches that end more than
`live.buffer_minutes` before it are evicted, and the oldest go first past the byte cap. A request
the Collector retries has the same body digest and is buffered once.

The buffer sits on a laptop with little free RAM, so the cap is hard. Three kinds of batch are
refused, counted and logged, and never stored:
- a batch larger than the whole cap;
- a batch whose newest row is later than the wall clock plus `live.future_tolerance_s`, because one
  far-future point would otherwise become "now" and evict everything;
- a batch with a null data time.
The clock is read only for these limits and for "seconds since the last batch" (06 §7: the
gateway may read the clock; no clock value reaches a table). Sizes are Arrow buffer bytes, not the
process RSS, which X-10's RAM figure must measure separately.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, cast

import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_core.io import TELEMETRY, conform_table
from veyltrace_core.log import get_logger

__all__ = ["BYTES_PER_MIB", "TIME_COLUMN", "AddResult", "Batch", "BufferStats", "LiveBuffer"]

#: The data-time column of each canonical source (03 §2.2-2.5): spans are placed by their start.
TIME_COLUMN: Final = {"metrics": "t_ns", "logs": "t_ns", "spans": "start_ns", "events": "t_ns"}
_NS_PER_MIN: Final = 60_000_000_000
_NS_PER_S: Final = 1_000_000_000
#: The `*_mb` keys are MiB (06 §6).
BYTES_PER_MIB: Final = 1024 * 1024
_LOG: Final = get_logger(__name__)

#: What `add` did with a batch; the last three are refusals (counted in `BufferStats.dropped`).
AddResult = Literal["accepted", "duplicate", "too_large", "future", "no_time"]


@dataclass(frozen=True)
class Batch:
    """One converted request: its table, data-time bounds, size and request digest."""

    source: str
    table: pa.Table
    t_min_ns: int
    t_max_ns: int
    nbytes: int
    digest: str


@dataclass(frozen=True)
class BufferStats:
    """Rows, bytes and data-time bounds per source (`live_status`, 06 §3.4)."""

    rows: dict[str, int]
    bytes: dict[str, int]
    oldest_ns: int | None
    newest_ns: int | None
    seconds_since_last: float | None
    dropped: dict[str, int]


class LiveBuffer:
    """Thread-safe: the receiver adds from its worker threads, the API reads."""

    def __init__(
        self,
        buffer_minutes: int,
        buffer_max_mb: int,
        future_tolerance_s: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], int] = time.time_ns,
    ) -> None:
        self._retention_ns = buffer_minutes * _NS_PER_MIN
        self._max_bytes = buffer_max_mb * BYTES_PER_MIB
        self._future_ns = future_tolerance_s * _NS_PER_S
        self._clock, self._wall = clock, wall
        self._batches: list[Batch] = []
        self._dropped: dict[str, int] = {}
        self._last: float | None = None
        self._lock = threading.Lock()

    def add(self, source: str, table: pa.Table, digest: str) -> AddResult:
        """Buffer `table` (conformed to the source's contract), or say why not."""
        table = conform_table(TELEMETRY[source], table)
        when = table.column(TIME_COLUMN[source])
        bounds = cast(dict[str, int | None], pc.min_max(when).as_py())
        low, high = bounds["min"], bounds["max"]
        with self._lock:
            self._last = self._clock()
            if any(b.digest == digest for b in self._batches):
                return "duplicate"
            if not table.num_rows:
                return "accepted"
            if when.null_count or low is None or high is None:
                return self._refuse("no_time", source, table)
            if table.nbytes > self._max_bytes:
                return self._refuse("too_large", source, table)
            if high > self._wall() + self._future_ns:
                return self._refuse("future", source, table)
            self._batches.append(Batch(source, table, low, high, table.nbytes, digest))
            self._evict()
            return "accepted"

    def _refuse(self, reason: AddResult, source: str, table: pa.Table) -> AddResult:
        """Count and log a refused batch (the caller holds the lock)."""
        self._dropped[reason] = self._dropped.get(reason, 0) + 1
        _LOG.warning("live_batch_dropped", reason=reason, source=source, rows=table.num_rows)
        return reason

    def _evict(self) -> None:
        newest = max(b.t_max_ns for b in self._batches)
        kept = sorted((b for b in self._batches if b.t_max_ns >= newest - self._retention_ns), key=_age)
        total = sum(b.nbytes for b in kept)
        while total > self._max_bytes:  # every batch fits the cap alone, so this ends
            total -= kept.pop(0).nbytes  # oldest data first
        self._batches = kept

    def tables(self, source: str) -> list[pa.Table]:
        """The buffered tables of one source, oldest data first."""
        with self._lock:
            return [b.table for b in self._batches if b.source == source]

    def receiving(self, within_s: float) -> bool:
        with self._lock:
            return self._last is not None and self._clock() - self._last <= within_s

    def stats(self) -> BufferStats:
        with self._lock:
            batches, last, dropped = list(self._batches), self._last, dict(self._dropped)
            since = None if last is None else self._clock() - last
        rows = {s: sum(b.table.num_rows for b in batches if b.source == s) for s in TELEMETRY}
        size = {s: sum(b.nbytes for b in batches if b.source == s) for s in TELEMETRY}
        oldest = min((b.t_min_ns for b in batches), default=None)
        newest = max((b.t_max_ns for b in batches), default=None)
        return BufferStats(rows, size, oldest, newest, since, dropped)


def _age(batch: Batch) -> tuple[int, int]:
    return batch.t_max_ns, batch.t_min_ns
