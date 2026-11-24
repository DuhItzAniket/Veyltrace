"""The live snapshot (06 §3.4 steps 2-3): the buffer's data-time window, written to disk and hashed.

Why on disk first: every live verdict comes from `run_case` on files (package rule 1), so a live
run replays like an offline one. The trigger time is the only clock value that reaches analysis,
and it enters through `snapshot.json`, which is hashed into the id. The layout is the one proposed
to Observe on #24 (OQ-6): `${VEYLTRACE_DATA}/live/<snapshot_id>/{metrics,logs,spans,events}.parquet`
in canonical shape (core's writers sort and hash them) and `snapshot.json` = `{snapshot_id,
t_trigger_ns, trigger}`. `events.parquet` is empty: live has no change feed. The id is
`veyltrace_core.ids.snapshot_id`, so the same rows and trigger always give the same id; the
trigger kind is recorded but not hashed (06 §3.4), so it may overwrite `snapshot.json`. The case
id is `case_id(snapshot_id)`, because the snapshot id is `otlp_live`'s canonical case key (01
§3.2), and `${VEYLTRACE_DATA}/index/live.json` maps it to the snapshot folder, as for every
dataset (01 §2).

The trigger is the requested time (the click) capped at the newest buffered data time. Rows reach
the buffer seconds after their data time (Collector batching, scrapes), so a trigger at the click
would lie after `data_end_ns`, and core's alert step would reject the case as `hint_outside_span`
(`core.alert.reject_hint_outside_span`). The newest data time is the latest moment we have data
for. A repeated click with no new data therefore gives the same snapshot.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.hashing import sha256_bytes
from veyltrace_core.ids import case_id, snapshot_id
from veyltrace_core.io import TELEMETRY, arrow_schema, contract_info, empty_table, encode
from veyltrace_gateway.buffer import TIME_COLUMN, LiveBuffer

__all__ = ["LIVE_DATASET", "SNAPSHOT_DIR", "Snapshot", "write_snapshot"]

LIVE_DATASET: Final = "live"
#: Snapshot folders under the data root (06 §3.4); also the dataset's index name (01 §2).
SNAPSHOT_DIR: Final = "live"
INDEX_DIR: Final = "index"
_NS_PER_MIN: Final = 60_000_000_000
_LOCK: Final = threading.Lock()  # one snapshot at a time: the index file is read, merged, rewritten

Trigger = Literal["watcher", "manual"]


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    case_id: str
    t_trigger_ns: int
    rows: dict[str, int]


def _window(buffer: LiveBuffer, source: str, start_ns: int, end_ns: int) -> pa.Table:
    """Rows of `source` with data time in [start, end]; exact repeats dropped for unique-key
    contracts (a point the Collector sent in two requests is one row, 03 §2.2-2.4 keys)."""
    name = TELEMETRY[source]
    tables = buffer.tables(source) if source != "events" else []
    if not tables:
        return empty_table(name)
    table = pa.concat_tables(tables)
    when = table.column(TIME_COLUMN[source])
    low, high = pa.scalar(start_ns, pa.int64()), pa.scalar(end_ns, pa.int64())
    table = table.filter(pc.and_(pc.greater_equal(when, low), pc.less_equal(when, high)))
    if contract_info(name).unique and table.num_rows:
        schema = arrow_schema(name)
        distinct = table.group_by(schema.names, use_threads=False).aggregate([])
        table = distinct.select(schema.names).cast(schema)
    return table


def write_snapshot(
    buffer: LiveBuffer, data_root: Path, at_ns: int, before_min: int, trigger: Trigger
) -> Snapshot | None:
    """Write the window [t_trigger − before_min, t_trigger], where t_trigger = min(at_ns, newest
    buffered data time) (the manual settle is 0, 06 §6), and return it, or None when the window
    holds no rows. Raises ContractValidationError when two different rows share a unique key (the
    converter's combine rule did not cover them)."""
    newest = buffer.stats().newest_ns
    if newest is None:
        return None
    t_trigger_ns = min(at_ns, newest)
    start = t_trigger_ns - before_min * _NS_PER_MIN
    tables = {source: _window(buffer, source, start, t_trigger_ns) for source in TELEMETRY}
    if not any(t.num_rows for t in tables.values()):
        return None
    payloads = {source: encode(TELEMETRY[source], table) for source, table in tables.items()}
    sid = snapshot_id([sha256_bytes(p) for p in payloads.values()], t_trigger_ns)
    folder = data_root / SNAPSHOT_DIR / sid
    with _LOCK:  # files first, index last: a crash leaves a folder no case id points to
        for source, payload in payloads.items():
            textio.write_bytes(folder / f"{source}.parquet", payload)
        meta = {"snapshot_id": sid, "t_trigger_ns": t_trigger_ns, "trigger": trigger}
        textio.write_bytes(folder / "snapshot.json", canonical_json(meta) + b"\n")
        cid = case_id(sid)
        _index(data_root, cid, f"{SNAPSHOT_DIR}/{sid}")
    return Snapshot(sid, cid, t_trigger_ns, {s: t.num_rows for s, t in tables.items()})


def _index(data_root: Path, cid: str, relpath: str) -> None:
    """Add `cid → relpath` to `index/live.json` (canonical JSON, sorted keys, as Infralume writes)."""
    path = data_root / INDEX_DIR / f"{LIVE_DATASET}.json"
    entries = cast(dict[str, str], json.loads(textio.read_text(path))) if path.is_file() else {}
    entries[cid] = relpath
    textio.write_bytes(path, canonical_json(dict(sorted(entries.items()))) + b"\n")
