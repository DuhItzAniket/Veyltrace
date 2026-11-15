"""Changed-vs-peer contrast (04 §3.6): cohort construction and the score."""

from __future__ import annotations

import pyarrow as pa

from veyltrace_causync.changes import Change
from veyltrace_causync.peers import Replicas, peer_contrast, replica_scores, replicas

S = 10**9
#: A rolling deploy of `cart` at 100 s: cart-0 and cart-1 keep running, cart-2 and cart-3 are new.
PODS = Replicas(
    {
        "cart": {
            "cart-0": (0, 400 * S),
            "cart-1": (0, 400 * S),
            "cart-2": (100 * S, 400 * S),
            "cart-3": (130 * S, 400 * S),
        }
    }
)
SCORES = {"cart-0": 1.0, "cart-1": 3.0, "cart-2": 9.0, "cart-3": 5.0}
ONSET = 200 * S


def change(t: int, entity: str = "cart", kind: str = "deploy", service: str | None = "cart") -> Change:
    scope = "cluster" if service is None else "service" if entity == service else "component"
    return Change("C0", t * S, entity, kind, scope, "{}", service)


def series(rows: list[tuple[str, str, int]]) -> pa.Table:
    return pa.table(
        {
            "source": pa.array(["metrics"] * len(rows)),
            "service": pa.array([s for s, _, _ in rows]),
            "component": pa.array([c for _, c, _ in rows]),
            "signal": pa.array(["cpu"] * len(rows)),
            "t_ns": pa.array([t * S for _, _, t in rows], pa.int64()),
            "value": pa.array([0.0] * len(rows), pa.float64()),
        }
    )


def test_replicas_are_components_other_than_the_service() -> None:
    table = series(
        [
            ("cart", "cart-0", 5),
            ("cart", "cart-0", 90),
            ("cart", "cart", 1),
            ("cart", "cart-1", 40),
            ("pay", "pay", 3),
        ]
    )
    found = replicas(table)
    assert found.seen == {"cart": {"cart-0": (5 * S, 90 * S), "cart-1": (40 * S, 40 * S)}}
    assert found.service_of == {"cart-0": "cart", "cart-1": "cart"}
    assert replicas(series([])).seen == {}


def test_replica_score_is_the_max_raw_robust_z() -> None:
    rows = [
        ("cart-0", "internal", "robust_z", 2.0),
        ("cart-0", "external", "robust_z", 7.5),
        ("cart-0", "context", "robust_z", 99.0),  # context series are not evidence
        ("cart-0", "internal", "bocpd", 50.0),  # another detector, another unit
        ("cart-1", "internal", "robust_z", -1.0),
        ("cart-2", "internal", "robust_z", float("nan")),
    ]
    table = pa.table(
        {
            "component": pa.array([r[0] for r in rows]),
            "klass": pa.array([r[1] for r in rows]),
            "detector": pa.array([r[2] for r in rows]),
            "score": pa.array([r[3] for r in rows], pa.float64()),
        }
    )
    assert replica_scores(table) == {"cart-0": 7.5, "cart-1": -1.0}


def test_rolling_deploy_compares_new_pods_with_old_ones() -> None:
    # changed = {cart-2, cart-3} (first seen at or after the change); peers = {cart-0, cart-1}
    assert peer_contrast(change(100), ONSET, PODS, SCORES, 2) == (9.0 + 5.0) / 2 - (1.0 + 3.0) / 2
    assert peer_contrast(change(120), ONSET, PODS, SCORES, 2) == 5.0 - 3.0  # cart-2 is now a peer: median 3
    assert peer_contrast(change(100, kind="restart"), ONSET, PODS, SCORES, 2) == 5.0


def test_component_scope_compares_one_replica_with_the_rest() -> None:
    assert peer_contrast(change(150, "cart-1"), ONSET, PODS, SCORES, 2) == 3.0 - 5.0  # peers 1, 9, 5
    assert peer_contrast(change(150, "cart-1"), ONSET, PODS, {}, 2) == 0.0  # no anomaly rows: scores 0


def test_replica_sightings_move_to_the_reference_clock() -> None:
    # the metrics clock runs 30 s behind: cart-2, first seen at 100 s, really appeared at 130 s
    assert peer_contrast(change(120), ONSET, PODS, SCORES, 2) == 5.0 - 3.0  # raw: cart-2 is a peer
    assert peer_contrast(change(120), ONSET, PODS, SCORES, 2, 30 * S) == (9.0 + 5.0) / 2 - (1.0 + 3.0) / 2
    late = Replicas({"cart": {"cart-0": (0, 190 * S), "cart-2": (100 * S, 400 * S)}})
    assert peer_contrast(change(100), ONSET, late, SCORES, 2) is None  # the peer ended before the onset
    # 15 s later on the reference clock the peer outlives the onset (205 s): there is a cohort
    assert peer_contrast(change(100), ONSET, late, SCORES, 2, 15 * S) == 9.0 - 1.0


def test_no_cohort_gives_null() -> None:
    assert peer_contrast(change(100, "mesh", service=None), ONSET, PODS, SCORES, 2) is None  # cluster scope
    assert (
        peer_contrast(change(100, kind="flag"), ONSET, PODS, SCORES, 2) is None
    )  # a flag changes no replica
    assert peer_contrast(change(0), ONSET, PODS, SCORES, 2) is None  # no replica seen before the change
    assert peer_contrast(change(300), ONSET, PODS, SCORES, 2) is None  # no new replica after it
    assert peer_contrast(change(100), ONSET, PODS, SCORES, 5) is None  # fewer than min_replicas
    assert peer_contrast(change(100, "catalog", service="catalog"), ONSET, PODS, SCORES, 2) is None
    assert peer_contrast(change(100), None, PODS, SCORES, 2) is None
    gone = Replicas({"cart": {"cart-0": (0, 150 * S), "cart-2": (100 * S, 400 * S)}})
    assert peer_contrast(change(100), ONSET, gone, SCORES, 2) is None  # the only peer ended before the onset
