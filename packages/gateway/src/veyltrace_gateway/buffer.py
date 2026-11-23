"""The live buffer (06 §3.4): per source, Arrow tables in canonical shape with a data-time index.

Why data time, not arrival time: the snapshot cuts a window of data time around the trigger, and
retention must keep the 20-minute baseline plus the incident window of 02 §5.1 whatever the
Collector's batching. The newest data time seen is the buffer's "now"; batches that end more than
`live.buffer_minutes` before it are evicted, and the oldest go first past the byte cap. A request
the Collector retries has the same body digest and is buffered once. The clock is read only for
"seconds since the last batch" (06 §7: the gateway may read the clock; no clock value reaches a
table).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, cast

import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_core.io import TELEMETRY, conform_table

__all__ = ["TIME_COLUMN", "Batch", "BufferStats", "LiveBuffer"]

#: The data-time column of each canonical source (03 §2.2-2.5): spans are placed by their start.
TIME_COLUMN: Final = {"metrics": "t_ns", "logs": "t_ns", "spans": "start_ns", "events": "t_ns"}
_NS_PER_MIN: Final = 60_000_000_000
_BYTES_PER_MB: Final = 1024 * 1024


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


class LiveBuffer:
    """Thread-safe: the receiver adds from its worker threads, the API reads."""

    def __init__(
        self, buffer_minutes: int, buffer_max_mb: int, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._retention_ns = buffer_minutes * _NS_PER_MIN
        self._max_bytes = buffer_max_mb * _BYTES_PER_MB
        self._clock = clock
        self._batches: list[Batch] = []
        self._last: float | None = None
        self._lock = threading.Lock()

    def add(self, source: str, table: pa.Table, digest: str) -> bool:
        """Buffer `table` (conformed to the source's contract); False for a request already held."""
        name = TELEMETRY[source]
        table = conform_table(name, table)
        with self._lock:
            self._last = self._clock()
            if any(b.digest == digest for b in self._batches):
                return False
            if table.num_rows:
                bounds = cast(dict[str, int], pc.min_max(table.column(TIME_COLUMN[source])).as_py())
                self._batches.append(Batch(source, table, bounds["min"], bounds["max"], table.nbytes, digest))
                self._evict()
            return True

    def _evict(self) -> None:
        newest = max(b.t_max_ns for b in self._batches)
        kept = sorted((b for b in self._batches if b.t_max_ns >= newest - self._retention_ns), key=_age)
        while len(kept) > 1 and sum(b.nbytes for b in kept) > self._max_bytes:
            kept.pop(0)  # oldest data first
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
            batches, last = list(self._batches), self._last
            since = None if last is None else self._clock() - last
        rows = {s: sum(b.table.num_rows for b in batches if b.source == s) for s in TELEMETRY}
        size = {s: sum(b.nbytes for b in batches if b.source == s) for s in TELEMETRY}
        oldest = min((b.t_min_ns for b in batches), default=None)
        newest = max((b.t_max_ns for b in batches), default=None)
        return BufferStats(rows, size, oldest, newest, since)


def _age(batch: Batch) -> tuple[int, int]:
    return batch.t_max_ns, batch.t_min_ns
