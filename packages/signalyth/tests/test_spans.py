"""The span forest and trace series (02 §3.3)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_core.config import resolve_config
from veyltrace_signalyth.spans import Forest, TraceRules, build_forest, trace_series

RULES = TraceRules.from_config(resolve_config({}, ai_mode="off").engine("signalyth"))
MS = 1_000_000
T0 = 1_767_225_600_000_000_000  # an epoch-aligned bucket start


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
    op: str = "op",
) -> dict[str, Any]:
    return {
        "trace_id": trace,
        "span_id": sid,
        "parent_span_id": parent,
        "service": svc,
        "operation": op,
        "kind": kind,
        "start_ns": T0 + start * MS,
        "end_ns": T0 + end * MS,
        "status": status,
    }


def micro(trace: str = "t1", kind: str = "client") -> list[dict[str, Any]]:
    """02 §3.4's micro-example: A [0,100] calls B via b1 and C via c1."""
    return [
        span(trace, "a", None, "a", 0, 100),
        span(trace, "b1", "a", "a", 10, 60, kind=kind),
        span(trace, "b", "b1", "b", 12, 58),
        span(trace, "c1", "a", "a", 20, 90, kind=kind),
        span(trace, "c", "c1", "c", 22, 88, status="error"),
    ]


def forest(rows: list[dict[str, Any]], rules: TraceRules = RULES) -> Forest:
    return build_forest(pa.Table.from_pylist(rows), rules, "case")


def by_id(f: Forest, field: str) -> dict[str, Any]:
    return {str(s): getattr(f, field)[i] for i, s in enumerate(f.span_ids)}


def test_micro_example_entries_clients_self_time() -> None:
    for kind in ("client", "unspecified"):  # unspecified one-child spans are inferred as clients
        f = forest(micro(kind=kind))
        assert by_id(f, "client") == {"a": False, "b1": True, "b": False, "c1": True, "c": False}
        assert by_id(f, "entry") == {"a": True, "b1": False, "b": True, "c1": False, "c": True}
        assert {k: v // MS for k, v in by_id(f, "self_ns").items()} == {
            "a": 20,
            "b1": 0,
            "b": 46,
            "c1": 0,
            "c": 66,
        }
        visit = {k: str(f.span_ids[v]) if v >= 0 else None for k, v in by_id(f, "visit").items()}
        assert visit == {"a": "a", "b1": "a", "c1": "a", "b": "b", "c": "c"}


def test_parents_rebuilt_by_containment_only_when_all_are_missing() -> None:
    rows = [
        span("t", "x", None, "a", 0, 100),
        span("t", "y", None, "b", 10, 50),
        span("t", "z", None, "c", 12, 40),
    ]
    f = forest(rows)
    assert {k: (str(f.span_ids[p]) if p >= 0 else None) for k, p in by_id(f, "parent").items()} == {
        "x": None,
        "y": "x",
        "z": "y",
    }
    rows[2]["parent_span_id"] = "gone"  # an orphan: some parent ids exist, so nothing is rebuilt
    f = forest(rows)
    assert list(f.parent) == [-1, -1, -1] and f.entry.all()


def test_overlapping_children_count_once() -> None:
    rows = [
        span("t", "p", None, "a", 0, 100),
        span("t", "k1", "p", "a", 10, 50, kind="internal"),
        span("t", "k2", "p", "a", 30, 70, kind="internal"),
        span("t", "k3", "p", "a", 90, 120, kind="internal"),
    ]
    assert by_id(forest(rows), "self_ns")["p"] == (100 - 60 - 10) * MS  # [10,70] and [90,100]


def test_trace_series() -> None:
    rows = [r for i in range(6) for r in micro(trace=f"t{i}")]
    out = trace_series(forest(rows), RULES, T0, T0 + 25_000 * MS)
    got = {
        (s, sig): v
        for s, sig, v, t in zip(out["service"], out["signal"], out["value"], out["t_ns"], strict=True)
        if t == T0
    }
    assert got[("a", "rps")] == 0.6 and got[("c", "error_rate")] == 1.0 and got[("a", "error_rate")] == 0.0
    assert got[("b", "latency_p50")] == 46.0 and got[("a", "self_time_p99")] == 20.0
    later = [(s, sig) for s, sig, t in zip(out["service"], out["signal"], out["t_ns"], strict=True) if t > T0]
    assert sorted(set(later)) == [("a", "rps"), ("b", "rps"), ("c", "rps")]  # zero-filled counts only
    assert out["value"][out["t_ns"].index(T0 + 20_000 * MS)] == 0.0
    few = trace_series(forest(micro()), RULES, T0, T0)  # one trace: below min_spans_per_quantile
    assert "latency_p50" not in few["signal"] and "rps" in few["signal"]


@given(
    st.lists(st.tuples(st.integers(0, 50), st.integers(1, 50), st.integers(0, 4)), min_size=1, max_size=12)
)
def test_self_time_is_bounded(children: list[tuple[int, int, int]]) -> None:
    rows = [span("t", "r", None, "root", 0, 100)]
    rows += [span("t", f"k{i}", "r", f"s{svc}", lo, lo + w) for i, (lo, w, svc) in enumerate(children)]
    f = forest(rows)
    assert (f.self_ns >= 0).all() and (f.self_ns <= f.end - f.start).all()
