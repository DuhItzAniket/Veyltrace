"""Change timeline and time evidence (04 §3.4 to §3.6)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causync.changes import Change, aligned_onsets, evidence, timeline
from veyltrace_causync.settings import causync_config
from veyltrace_causync.tracepairs import Offset
from veyltrace_contracts import models
from veyltrace_core import duck
from veyltrace_core.config import resolve_config

CONFIG = resolve_config({}, ai_mode="off").engine("causync")
CFG = causync_config(CONFIG)
S = 10**9
TOL = 15 * S
SERVICES = ["cart", "catalog"]
COMPONENTS = {"cart-0": "cart", "cart-1": "cart"}
Event = tuple[int, str, str, str, str, str | None]  # second, entity, kind, source_system, detail_json, actor


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with duck.connect(CONFIG, tmp_path) as connection:
        yield connection


def events(rows: list[Event]) -> pa.Table:
    cols = list(zip(*rows, strict=True)) if rows else [[]] * 6
    return pa.table(
        {
            "t_ns": pa.array([t * S for t in cols[0]], pa.int64()),
            "entity": pa.array(cols[1], pa.string()),
            "kind": pa.array(cols[2], pa.string()),
            "source_system": pa.array(cols[3], pa.string()),
            "detail_json": pa.array(cols[4], pa.string()),
            "actor": pa.array(cols[5], pa.string()),
        }
    )


EVENTS: list[Event] = [
    (100, "catalog", "deploy", "k8s", '{"to":"catalog:1.5.0"}', None),
    (50, "cart-1", "config", "k8s", '{"key":"A"}', "ci"),
    (70, "mesh", "flag", "flagd", '{"flag":"0a1b2c3d"}', None),
    (90, "catalog", "k8s_event", "k8s", '{"reason":"Killing"}', None),  # a symptom, not a change
    (95, "catalog", "other", "manual", "{}", None),
]


def test_timeline_keeps_change_kinds_and_assigns_scope() -> None:
    found = timeline(events(EVENTS), SERVICES, COMPONENTS, CFG)
    assert [(c.t_ns // S, c.entity, c.kind, c.scope, c.service) for c in found] == [
        (50, "cart-1", "config", "component", "cart"),
        (70, "mesh", "flag", "cluster", None),
        (100, "catalog", "deploy", "service", "catalog"),
    ]
    assert found[2].detail_json == '{"to":"catalog:1.5.0"}'  # copied unchanged
    assert timeline(events([]), SERVICES, COMPONENTS, CFG) == []


def test_change_id_is_stable_and_hashes_the_original_event() -> None:
    first = timeline(events(EVENTS), SERVICES, COMPONENTS, CFG)
    again = timeline(events(EVENTS[::-1]), SERVICES, COMPONENTS, CFG, offset_ns=7 * S)
    assert [c.change_id for c in again] == [c.change_id for c in first]  # the id uses the unaligned time
    assert [c.t_ns for c in again] == [c.t_ns + 7 * S for c in first]
    assert all(len(c.change_id) == 11 and c.change_id[0] == "C" for c in first)
    twice = timeline(events([EVENTS[0], EVENTS[0]]), SERVICES, COMPONENTS, CFG)
    assert len(twice) == 1  # duplicate ids collapse
    other_actor = timeline(events([(*EVENTS[0][:5], "bob")]), SERVICES, COMPONENTS, CFG)
    assert other_actor[0].change_id != first[2].change_id


def _onsets(per_service: list[tuple[Any, ...]]) -> models.Onsets:
    return models.Onsets.model_construct(
        per_service=[
            models.OnsetsPerService(
                service=s, external_onset_ns=e, external_onset_source=es, internal_onset_ns=i,
                internal_onset_source=isrc, silent=False,
            )
            for s, e, es, i, isrc in per_service
        ]
    )  # fmt: skip


def test_onsets_move_to_the_reference_clock() -> None:
    onsets = _onsets(
        [("a", 100, "traces", 90, "metrics"), ("b", None, None, 80, "logs"), ("c", None, None, None, None)]
    )
    offsets = [
        Offset("traces", "a", -30, "trace_pairs", 1.0),
        Offset("traces", "b", 5, "trace_pairs", 1.0),
        Offset("logs", None, 7, "log_span_join", 1.0),
        Offset("metrics", None, 0, "none", 0.0),
    ]
    assert aligned_onsets(onsets, offsets) == {"a": 70, "b": 87}  # min(100 − 30, 90); 80 + 7; c has none
    assert aligned_onsets(onsets, []) == {"a": 90, "b": 80}


def change(t: int, entity: str = "catalog", service: str | None = "catalog", cid: str = "") -> Change:
    scope = "cluster" if service is None else "service" if entity == service else "component"
    return Change(cid or f"C{t:010d}", t * S, entity, "deploy", scope, "{}", service)


def rows(cols: dict[str, list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(cols, values, strict=True)) for values in zip(*cols.values(), strict=True)]


def test_proximity_before_at_and_after_the_onset(con: duckdb.DuckDBPyConnection) -> None:
    found = rows(
        evidence(
            con, [change(t) for t in (700, 940, 1000, 1010, 1015, 1016)], {"catalog": 1000 * S}, 0, TOL, CFG
        )
    )
    assert [r["delta_to_onset_ms"] for r in found] == [
        -300_000.0,
        -60_000.0,
        0.0,
        10_000.0,
        15_000.0,
        16_000.0,
    ]
    assert [r["proximity"] for r in found] == [math.exp(-1), math.exp(-0.2), 1.0, 1.0, 1.0, 0.0]
    # after the onset but inside the tolerance still counts; beyond it does not
    assert [r["latest_before_onset"] for r in found] == [False, False, False, False, True, False]
    assert all(r["peer_contrast"] is None for r in found)


def test_ties_at_the_latest_time_are_all_flagged(con: duckdb.DuckDBPyConnection) -> None:
    changes = [change(900, cid="Ca"), change(900, cid="Cb"), change(800), change(900, "cart", "cart")]
    found = rows(evidence(con, changes, {"catalog": 1000 * S, "cart": 850 * S}, 0, TOL, CFG))
    assert [r["latest_before_onset"] for r in found] == [
        True,
        True,
        False,
        False,
    ]  # cart's is after its onset


def test_target_onset_by_scope(con: duckdb.DuckDBPyConnection) -> None:
    changes = [change(90, "cart-1", "cart"), change(90, "mesh", None), change(90, "catalog", "catalog")]
    found = rows(evidence(con, changes, {"cart": 100 * S}, 400 * S, TOL, CFG))
    assert [r["delta_to_onset_ms"] for r in found] == [
        -10_000.0,
        -310_000.0,
        -310_000.0,
    ]  # catalog has no onset
    assert [r["latest_before_onset"] for r in found] == [True, True, True]
    no_onset = rows(evidence(con, changes[1:], {}, None, TOL, CFG))
    assert [(r["delta_to_onset_ms"], r["proximity"], r["latest_before_onset"]) for r in no_onset] == [
        (None, 0.0, False)
    ] * 2
    assert evidence(con, [], {}, None, TOL, CFG)["change_id"] == []


@given(st.lists(st.integers(min_value=0, max_value=4000), min_size=2, max_size=8, unique=True))
def test_proximity_is_bounded_and_falls_with_distance(times: list[int]) -> None:
    with duck.connect(CONFIG, Path(".")) as con:
        found = rows(evidence(con, [change(t) for t in sorted(times)], {"catalog": 2000 * S}, 0, TOL, CFG))
        before = [r["proximity"] for r in found if r["delta_to_onset_ms"] <= 0]
        assert all(0.0 <= r["proximity"] <= 1.0 for r in found)
        assert before == sorted(before)  # closer to the onset, never lower
        alone = rows(evidence(con, [change(sorted(times)[0])], {"catalog": 2000 * S}, 0, TOL, CFG))
        keep = ("delta_to_onset_ms", "proximity")
        assert {k: alone[0][k] for k in keep} == {k: found[0][k] for k in keep}
