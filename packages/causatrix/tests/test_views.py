"""Tests of Causatrix's input views: U (06 §2.1), G and the 07 §2.1 per-service quantities."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causatrix.views import (
    ServiceEvidence,
    component_of,
    engine_atoms,
    evidence_view,
    graph_view,
    universe,
)


def _row(cand: str, kind: str, v: float, args: Mapping[str, Any], aid: str, **extra: Any) -> dict[str, Any]:
    """An evidence row; `extra` sets component (default None) or origin (default engine)."""
    comp = extra.get("component")
    refs = [f"{cand}|{comp or cand}|x|metrics"]
    row = {"atom_id": aid, "candidate": cand, "component": comp, "kind": kind, "value": v, "refs": refs}
    return {**row, "args_json": json.dumps(args, sort_keys=True), "origin": extra.get("origin", "engine")}


def _anomaly(detector: str = "robust_z", family: str = "cpu", source: str = "metrics") -> dict[str, str]:
    return {"detector": detector, "family": family, "source": source, "window": "incident"}


INC = {"window": "incident"}
ROWS = [
    _row("a", "internal_anomaly", 9.0, _anomaly(), "E0000000002", component="a-0"),
    _row("a", "internal_anomaly", 9.0, _anomaly(family="mem"), "E0000000001", component="a-1"),
    _row("a", "internal_anomaly", 2.0, _anomaly(source="logs", family="logs"), "E0000000003"),
    _row("a", "internal_anomaly", 50.0, _anomaly("nsigma"), "E0000000004"),
    _row("a", "external_anomaly", 61.0, _anomaly("nsigma", "latency"), "E0000000005"),
    _row("a", "onset_precedence", 120.0, {"scope": "self", "window": "onset"}, "E0000000006"),
    _row("a", "onset_precedence", 0.5, {"scope": "dependents", "window": "onset"}, "E0000000007"),
    _row("a", "silence", 0.0, INC, "E0000000008"),
    _row("b", "external_anomaly", 4.0, _anomaly(family="latency"), "E0000000009", component="b-0"),
    _row("b", "silence", 1.0, INC, "E000000000a"),
    _row(
        "b", "spectrum", 0.25, {"formula": "ochiai", "weighting": "cp", "window": "incident"}, "E000000000b"
    ),
    _row("b", "change_proximity", 0.2, {"change_id": "C0000000001", "event_kind": "deploy", **INC}, "E1"),
    _row("b", "change_proximity", 0.7, {"change_id": "C0000000002", "event_kind": "config", **INC}, "E2"),
    _row("c", "external_anomaly", 4.0, _anomaly(), "E000000000c", component=None),
    _row("zz", "internal_anomaly", 7.0, _anomaly(), "E000000000d"),  # not in U
    _row("a", "claim_check", 99.0, {"k": 3.0}, "E000000000e", origin="claim_check"),
]


def test_universe_is_services_plus_non_external_nodes_sorted() -> None:
    nodes = [("redis", "cache"), ("gw.example", "external"), ("frontend", "entry")]
    assert universe(["payment", "frontend"], nodes, include_external=False) == (
        "frontend",
        "payment",
        "redis",
    )
    wide = universe(["payment"], nodes, include_external=True)
    assert (wide, universe([], [], include_external=False)) == (
        ("frontend", "gw.example", "payment", "redis"),
        (),
    )


def test_engine_atoms_ignore_claim_checks_and_parse_args_and_refs() -> None:
    atoms = engine_atoms(ROWS)
    assert all(a.kind != "claim_check" for a in atoms)
    assert [a.candidate for a in atoms] == sorted(a.candidate for a in atoms)
    assert [(a.candidate, a.kind) for a in atoms[:2]] == [
        ("a", "external_anomaly"),
        ("a", "internal_anomaly"),
    ]
    top = next(a for a in atoms if a.atom_id == "E0000000002")
    assert (top.args["detector"], top.component, top.refs) == ("robust_z", "a-0", ("a|a-0|x|metrics",))


def test_service_quantities_follow_07_2_1() -> None:
    ev = evidence_view(engine_atoms(ROWS), ["a", "b", "c", "d"])
    a, b, c = ev.of("a"), ev.of("b"), ev.of("c")
    # I is the robust_z max over all families and sources; nsigma atoms never count.
    assert (a.internal, a.external) == (9.0, 0.0)
    # topI: equal values -> the smaller atom_id (E…01, family mem, component a-1).
    assert a.top_internal is not None and a.top_internal.atom_id == "E0000000001"
    assert a.top_external is None
    # NS spans internal and external nsigma atoms; onset_ms is the self-scope value only.
    assert (a.nsigma, a.onset_ms, a.silent) == (61.0, 120.0, 0.0)
    assert (b.external, b.silent, b.spectrum, b.change) == (4.0, 1.0, 0.25, 0.7)
    assert b.onset_ms == math.inf and b.internal == 0.0
    assert c.top_external is not None and c.top_external.atom_id == "E000000000c"
    assert ev.of("d") == ServiceEvidence() == ev.of("not-in-u")
    assert len(ev.atoms_of("b", "change_proximity")) == 2


def test_case_channels_and_atoms_outside_u() -> None:
    ev = evidence_view(engine_atoms(ROWS), ["a", "b", "c", "d"])
    assert (ev.has_robust_z, ev.has_nsigma, ev.has_spectrum, ev.has_change) == (True, True, True, True)
    assert "zz" not in ev.services and all(x.candidate != "zz" for x in ev.atoms)
    empty = evidence_view((), ["a"])
    assert (empty.has_robust_z, empty.has_nsigma, empty.has_spectrum, empty.has_change) == (False,) * 4
    # A nsigma-only case has the nsigma channel and no robust_z channel.
    only = evidence_view(engine_atoms([ROWS[3]]), ["a"])
    assert (only.has_robust_z, only.has_nsigma) == (False, True)


def test_component_from_top_internal_else_top_external() -> None:
    ev = evidence_view(engine_atoms(ROWS), ["a", "b", "c", "d"])
    assert component_of("a", ev) == "a-1"
    assert component_of("b", ev) == "b-0"
    assert component_of("c", ev) is None
    assert component_of("d", ev) is None
    same = evidence_view(
        engine_atoms([_row("e", "internal_anomaly", 5.0, _anomaly(), "E3", component="e")]), ["e"]
    )
    assert component_of("e", same) is None  # equal to the service


def _edge(
    src: str, dst: str, weight: float = 1.0, provenance: tuple[str, ...] = ("traces",)
) -> dict[str, Any]:
    return {"src": src, "dst": dst, "weight": weight, "provenance": list(provenance)}


def test_graph_view_restricts_to_u_and_drops_self_edges() -> None:
    nodes = [("frontend", "entry"), ("cart", "service"), ("redis", "cache"), ("gw.example", "external")]
    edges = [
        _edge("frontend", "cart", 0.75, ("traces", "topology")),
        _edge("frontend", "redis", 0.25),
        _edge("cart", "cart"),
        _edge("cart", "gw.example"),
        _edge("cart", "redis"),
    ]
    g = graph_view(["frontend", "cart"], nodes, reversed(edges), include_external=False)
    assert g.universe == ("cart", "frontend", "redis")
    assert [(e.src, e.dst) for e in g.edges] == [
        ("cart", "redis"),
        ("frontend", "cart"),
        ("frontend", "redis"),
    ]
    assert [e.dst for e in g.callees("frontend")] == ["cart", "redis"]
    assert g.callees("frontend")[0].provenance == ("topology", "traces")
    assert g.callees("redis") == () and g.has_edges
    assert dict(g.kinds) == {"cart": "service", "frontend": "entry", "redis": "cache"}
    wide = graph_view(["frontend", "cart"], nodes, edges, include_external=True)
    assert ("cart", "gw.example") in [(e.src, e.dst) for e in wide.edges]
    assert not graph_view(["a"], [], [], include_external=False).has_edges


_values = st.floats(min_value=0.0, max_value=50.0, allow_nan=False)
_rows = st.lists(
    st.builds(
        lambda s, kind, v, det, i: _row(s, kind, v, _anomaly(det), f"E{i:010x}"),
        st.sampled_from(["a", "b", "c"]),
        st.sampled_from(["internal_anomaly", "external_anomaly"]),
        _values,
        st.sampled_from(["robust_z", "nsigma", "silence"]),
        st.integers(min_value=0, max_value=2**32),
    ),
    max_size=12,
    unique_by=lambda r: r["atom_id"],
)


@given(rows=_rows, data=st.data())
def test_views_ignore_row_order_and_claim_checks(rows: list[dict[str, Any]], data: st.DataObject) -> None:
    members = ["a", "b", "c"]
    view = evidence_view(engine_atoms(rows), members)
    claims = [_row(r["candidate"], "claim_check", 1.0, {}, r["atom_id"], origin="claim_check") for r in rows]
    shuffled = data.draw(st.permutations(rows + claims))
    assert evidence_view(engine_atoms(shuffled), reversed(members)) == view
