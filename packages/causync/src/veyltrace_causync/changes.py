"""The change timeline and its time evidence (04-causync §3.4 to §3.6).

Change-kind events become rows of `changes`, each compared with the aligned onset of the entity
it touches: how long before the onset it happened, a proximity score `exp(−Δt/τ)` that still
counts a change recorded within `tolerance_ns` after the onset, and whether it is the latest
change on its entity before the onset. A change is scored from its time, entity and kind only:
`source_system` and `actor` are hashed into `change_id` and never read again, so a decoy looks
exactly like a true change here (02 §6.4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import duckdb
import pyarrow as pa

from veyltrace_causync.settings import MS, CausyncConfig
from veyltrace_causync.tracepairs import Offset
from veyltrace_contracts import models
from veyltrace_core.ids import short_id

__all__ = ["EVENT_COLUMNS", "Change", "aligned_onsets", "evidence", "timeline"]

EVENT_COLUMNS: Final = ("t_ns", "entity", "kind", "source_system", "detail_json", "actor")
CHANGE_ID_HEX: Final = 10


@dataclass(frozen=True)
class Change:
    """One change on the reference clock. `service` is the service whose onset it is compared
    with: the entity, the component's service, or None for cluster scope."""

    change_id: str
    t_ns: int
    entity: str
    kind: str
    scope: str
    detail_json: str
    service: str | None


def aligned_onsets(onsets: models.Onsets, offsets: list[Offset]) -> dict[str, int]:
    """`O(s)` per service with an onset: the earlier of its external and internal onsets, each
    moved to the reference clock by the offset of its recorded source (the (source, service)
    offset if there is one, else the source-level one, else 0)."""
    table: dict[tuple[str | None, str | None], int] = {(o.source, o.service): o.offset_ns for o in offsets}
    out: dict[str, int] = {}
    for p in onsets.per_service:
        pairs = (
            (p.external_onset_ns, p.external_onset_source),
            (p.internal_onset_ns, p.internal_onset_source),
        )
        found = [
            t + table.get((source, p.service), table.get((source, None), 0))
            for t, source in pairs
            if t is not None
        ]
        if found:
            out[p.service] = min(found)
    return out


def timeline(
    events: pa.Table,
    services: list[str],
    components: Mapping[str, str],
    cfg: CausyncConfig,
    offset_ns: int = 0,
) -> list[Change]:
    """Changes from `telemetry.events` rows (EVENT_COLUMNS) whose kind is in `changes.kinds`,
    sorted by (t_ns, entity, change_id). `components` maps a component of `signal_cube.series`
    to its service; `offset_ns` is the events offset. Rows with the same `change_id` collapse."""
    known = set(services)
    out: dict[str, Change] = {}
    for row in events.to_pylist():
        if row["kind"] not in cfg.change_kinds:
            continue
        entity = str(row["entity"])
        cid = short_id("C", CHANGE_ID_HEX, {name: row[name] for name in EVENT_COLUMNS})
        if entity in known:
            scope, service = "service", entity
        elif entity in components:
            scope, service = "component", components[entity]
        else:
            scope, service = "cluster", None
        t_ns = int(row["t_ns"]) + offset_ns
        out[cid] = Change(cid, t_ns, entity, str(row["kind"]), scope, str(row["detail_json"]), service)
    return sorted(out.values(), key=lambda c: (c.t_ns, c.entity, c.change_id))


def _latest(
    con: duckdb.DuckDBPyConnection, timed: list[tuple[str, int, int]], tolerance_ns: int
) -> set[tuple[str, int]]:
    """(entity, t_ns) of the latest change per entity at or before its onset plus the tolerance,
    by an ASOF join; `timed` holds (entity, t_ns, onset) rows."""
    array: Any = pa.array  # pyarrow-stubs overloads carry Unknown parts
    entities = sorted({(entity, onset + tolerance_ns) for entity, _, onset in timed})
    con.register(
        "entity_onsets",
        pa.Table.from_arrays(
            [
                array([e for e, _ in entities], type=pa.string()),
                array([c for _, c in entities], type=pa.int64()),
            ],
            names=["entity", "cutoff_ns"],
        ),
    )
    con.register(
        "change_times",
        pa.Table.from_arrays(
            [
                array([e for e, _, _ in timed], type=pa.string()),
                array([t for _, t, _ in timed], type=pa.int64()),
            ],
            names=["entity", "t_ns"],
        ),
    )
    rows = con.execute(
        "SELECT o.entity, c.t_ns FROM entity_onsets o ASOF JOIN change_times c "
        "ON o.entity = c.entity AND o.cutoff_ns >= c.t_ns"
    ).fetchall()
    con.unregister("entity_onsets")
    con.unregister("change_times")
    return {(str(entity), int(t)) for entity, t in rows}


def evidence(
    con: duckdb.DuckDBPyConnection,
    changes: list[Change],
    onsets: Mapping[str, int],
    t_onset_ns: int | None,
    tolerance_ns: int,
    cfg: CausyncConfig,
) -> dict[str, list[Any]]:
    """`changes` columns except `peer_contrast` (all null here). The target onset of a change is
    its service's aligned onset, or `t_onset_ns` for cluster scope and for a service without one;
    with no onset at all the change has no delta, proximity 0 and is never the latest."""
    targets = [onsets.get(c.service, t_onset_ns) if c.service is not None else t_onset_ns for c in changes]
    timed = [(c.entity, c.t_ns, o) for c, o in zip(changes, targets, strict=True) if o is not None]
    latest = _latest(con, timed, tolerance_ns) if timed else set[tuple[str, int]]()
    cols: dict[str, list[Any]] = {
        name: []
        for name in (
            "change_id", "t_ns", "entity", "kind", "scope", "detail_json",
            "latest_before_onset", "delta_to_onset_ms", "proximity", "peer_contrast",
        )
    }  # fmt: skip
    for c, onset in zip(changes, targets, strict=True):
        counted = onset is not None and c.t_ns <= onset + tolerance_ns
        row = (
            c.change_id, c.t_ns, c.entity, c.kind, c.scope, c.detail_json,
            onset is not None and (c.entity, c.t_ns) in latest,
            None if onset is None else (c.t_ns - onset) / MS,
            math.exp(-max(0, onset - c.t_ns) / cfg.tau_ns) if onset is not None and counted else 0.0,
            None,
        )  # fmt: skip
        for name, value in zip(cols, row, strict=True):
            cols[name].append(value)
    return cols
