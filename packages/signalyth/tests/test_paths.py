"""Edges (02 §3.3) and the critical path with its slow-trace spectrum (02 §3.4)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_core.config import resolve_config
from veyltrace_signalyth.paths import critical_path_rows, edge_rows, trace_paths, walk
from veyltrace_signalyth.spans import Forest, TraceRules, build_forest

RULES = TraceRules.from_config(resolve_config({}, ai_mode="off").engine("signalyth"))
MS = 1_000_000
T0 = 1_767_225_600_000_000_000
WINDOWS = {"baseline": (T0, T0 + 1000 * MS), "incident": (T0 + 1000 * MS, T0 + 2000 * MS)}


def span(
    trace: str,
    sid: str,
    parent: str | None,
    svc: str,
    start: int,
    end: int,
    *,
    kind: str = "server",
    status: str = "ok",
) -> dict[str, Any]:
    return {
        "trace_id": trace,
        "span_id": sid,
        "parent_span_id": parent,
        "service": svc,
        "operation": "op",
        "kind": kind,
        "start_ns": T0 + start * MS,
        "end_ns": T0 + end * MS,
        "status": status,
    }


def micro(trace: str = "t1", shift: int = 0, scale: int = 1) -> list[dict[str, Any]]:
    """02 §3.4's micro-example: A [0,100] calls B via client b1 and C via client c1."""
    s, k = shift, scale
    return [
        span(trace, "a", None, "a", s, s + 100 * k),
        span(trace, "b1", "a", "a", s + 10, s + 60, kind="client"),
        span(trace, "b", "b1", "b", s + 12, s + 58),
        span(trace, "c1", "a", "a", s + 20, s + 90 * k, kind="client"),
        span(trace, "c", "c1", "c", s + 22, s + 88 * k, status="error"),
    ]


def forest(rows: list[dict[str, Any]]) -> Forest:
    return build_forest(pa.Table.from_pylist(rows), RULES, "case")


def test_micro_example_walk() -> None:
    f = forest(micro())
    paths = trace_paths(f, RULES, WINDOWS, "case")
    assert len(paths) == 1
    named = {f.services[s]: v // MS for s, v in paths[0].self_ns.items()}
    assert named == {"a": 30, "c": 66}  # B is off the path; gap 2 + 2 = 4
    _, gap = walk(f, _children(f), int(f.parent.argmin()), RULES.skew_tolerance_ns)  # root: no parent
    assert gap == 4 * MS


def _children(f: Forest) -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for c in sorted(range(f.size), key=lambda i: (-int(f.end[i]), -int(f.start[i]), str(f.span_ids[i]))):
        if f.parent[c] >= 0:
            kids.setdefault(int(f.parent[c]), []).append(c)
    return kids


def test_edges_with_client_gap() -> None:
    rows = [r for i in range(5) for r in micro(trace=f"t{i}", shift=i * 200)]
    cols = edge_rows(forest(rows), RULES, WINDOWS)
    edges = {(a, b): i for i, (a, b) in enumerate(zip(cols["caller"], cols["callee"], strict=True))}
    assert sorted(edges) == [("a", "b"), ("a", "c")] and set(cols["window"]) == {"baseline"}
    ab, ac = edges["a", "b"], edges["a", "c"]
    assert cols["calls"][ab] == 5 and cols["error_rate"][ab] == 0.0 and cols["error_rate"][ac] == 1.0
    assert (cols["p50_callee_ms"][ab], cols["p50_caller_ms"][ab], cols["p50_gap_ms"][ab]) == (46.0, 50.0, 4.0)
    few = edge_rows(forest(micro()), RULES, WINDOWS)
    assert few["calls"] == [1, 1] and few["p50_gap_ms"] == [None, None]  # below min_spans_per_quantile


def test_critical_path_table_and_slow_spectrum() -> None:
    baseline = [r for i in range(6) for r in micro(trace=f"b{i}", shift=i * 120)]
    incident = micro(trace="slow", shift=1100, scale=3)  # A 300 ms: above the baseline p95
    f = forest(baseline + incident)
    cols = critical_path_rows(f, trace_paths(f, RULES, WINDOWS, "case"), RULES.min_spans_per_quantile)
    rows = {(w, s): i for i, (w, s) in enumerate(zip(cols["window"], cols["service"], strict=True))}
    assert sorted(rows) == [
        ("baseline", "a"),
        ("baseline", "b"),
        ("baseline", "c"),
        ("incident", "a"),
        ("incident", "b"),
        ("incident", "c"),
    ]
    b_a, i_c, i_b = rows["baseline", "a"], rows["incident", "c"], rows["incident", "b"]
    assert (cols["traces"][b_a], cols["traces_total"][b_a], cols["cp_self_ms_p50"][b_a]) == (6, 6, 30.0)
    assert abs(cols["cp_share_mean"][b_a] - 0.30) < 1e-9 and cols["traces_slow"][b_a] == 0
    assert (cols["traces_total"][i_c], cols["traces_slow"][i_c]) == (1, 1)
    assert (cols["traces"][i_b], cols["cp_self_ms_p50"][i_b], cols["cp_share_mean"][i_b]) == (0, 0.0, 0.0)


@st.composite
def trees(draw: st.DrawFn) -> list[dict[str, Any]]:
    """A random span tree under one root [0, 1000] ms (children may overlap or stick out)."""
    rows = [span("t", "s0", None, "svc0", 0, 1000)]
    for i in range(1, draw(st.integers(1, 15))):
        parent = draw(st.integers(0, i - 1))
        lo = draw(st.integers(0, 1000))
        rows.append(
            span(
                "t",
                f"s{i}",
                f"s{parent}",
                f"svc{draw(st.integers(0, 3))}",
                lo,
                lo + draw(st.integers(0, 400)),
                kind=draw(st.sampled_from(["server", "client", "unspecified"])),
            )
        )
    return rows


@given(trees())
def test_critical_path_invariants(rows: list[dict[str, Any]]) -> None:
    f = forest(rows)
    root = int(next(i for i in range(f.size) if f.span_ids[i] == "s0"))
    self_ns, gap = walk(f, _children(f), root, RULES.skew_tolerance_ns)
    assert sum(self_ns.values()) + gap == f.end[root] - f.start[root]
    assert all(v >= 0 for v in self_ns.values()) and gap >= 0
    cols = critical_path_rows(f, trace_paths(f, RULES, WINDOWS, "case"), RULES.min_spans_per_quantile)
    assert sum(cols["cp_share_mean"]) <= 1 + 1e-9
    for t, slow, total, share_slow in zip(
        cols["traces"], cols["traces_slow"], cols["traces_total"], cols["cp_share_sum_slow"], strict=True
    ):
        assert slow <= t <= total and share_slow <= slow + 1e-9
