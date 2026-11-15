"""Trace clock offsets (04 §3.2): NTP estimate, propagation, publish gate."""

from __future__ import annotations

from dataclasses import replace

import pyarrow as pa
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causync.settings import causync_config
from veyltrace_causync.tracepairs import pair_stats, trace_offsets
from veyltrace_core.config import resolve_config
from veyltrace_core.testing import golden

ALIGN = causync_config(resolve_config({}, ai_mode="off").engine("causync")).align
MS = 10**6
Span = tuple[str, str, str | None, str, str, int, int]  # trace, span, parent, service, kind, start, end (ms)


def table(spans: list[Span]) -> pa.Table:
    cols = list(zip(*spans, strict=True)) if spans else [[]] * 7
    return pa.table(
        {
            "trace_id": pa.array(cols[0], pa.string()),
            "span_id": pa.array(cols[1], pa.string()),
            "parent_span_id": pa.array(cols[2], pa.string()),
            "service": pa.array(cols[3], pa.string()),
            "kind": pa.array(cols[4], pa.string()),
            "start_ns": pa.array([t * MS for t in cols[5]], pa.int64()),
            "end_ns": pa.array([t * MS for t in cols[6]], pa.int64()),
        }
    )


def chain(n: int, skew_b: int = 0, skew_c: int = 0, kind: str = "client") -> list[Span]:
    """n traces A → B → C: each call is a client span wrapping a server span 30 ms later that
    returns 4 ms before the client (the §3.2 micro-example); B and C clocks run ahead by the skews."""
    spans: list[Span] = []
    for i in range(n):
        t, base = f"t{i}", 1000 + 100 * i
        spans += [
            (t, "a", None, "A", "server", base, base + 60),
            (t, "a>b", "a", "A", kind, base, base + 50),
            (t, "b", "a>b", "B", "server", base + 30 + skew_b, base + 46 + skew_b),
            (t, "b>c", "b", "B", kind, base + 31 + skew_b, base + 45 + skew_b),
            (t, "c", "b>c", "C", "server", base + 33 + skew_c, base + 43 + skew_c),
        ]
    return spans


def offsets(spans: list[Span], entry: tuple[str, ...] = ("A",)) -> dict[str, tuple[int, str, float]]:
    found = trace_offsets(table(spans), list(entry), ALIGN)
    assert [o.service for o in found] == sorted(o.service or "" for o in found)
    assert all(o.source == "traces" for o in found)
    return {str(o.service): (o.offset_ns, o.method, o.confidence) for o in found}


def test_ntp_estimate_and_its_sign() -> None:
    stats, counts = pair_stats(table(chain(40)))
    assert counts == {"A": 80, "B": 80, "C": 40}
    ab = stats[("A", "B")]
    assert (ab.theta_ns, ab.n, ab.violation_share, ab.sign_share) == (13 * MS, 40, 0.0, 1.0)  # micro-example
    skewed, _ = pair_stats(table(chain(40, skew_b=200)))
    assert skewed[("A", "B")].theta_ns == 213 * MS  # callee clock minus caller clock
    assert skewed[("A", "B")].violation_share == 1.0
    assert skewed[("B", "C")].theta_ns == -200 * MS  # C looks behind when only B runs ahead


def test_no_visible_skew_publishes_zero() -> None:
    found = offsets(chain(40))
    assert {s: v[:2] for s, v in found.items()} == {s: (0, "trace_pairs") for s in "ABC"}
    assert found["A"][2] == 1.0  # the root defines the clock
    assert found["B"][2] == 40 / (40 + 30)


def test_skew_propagates_along_the_chain() -> None:
    found = offsets(chain(40, skew_b=200, skew_c=200))
    assert found["B"][0] == -213 * MS  # the micro-example: B ran 200 ms ahead
    assert found["C"][0] == 0  # θ_BC is small and contained: gated, although its raw offset is −215 ms
    only_c = offsets(chain(40, skew_c=-300))
    assert only_c["B"][0] == 0
    assert only_c["C"][0] == (-13 + 300) * MS  # offset(B) − θ_BC, from B's raw −13 ms


def test_propagation_against_the_call_direction() -> None:
    found = offsets(chain(40, skew_b=200, skew_c=200), entry=("C",))
    assert found["C"][:2] == (0, "trace_pairs")
    assert found["B"][0] == 0  # B → C pairs show no violation
    assert found["A"][0] == 213 * MS  # offset(A) = offset(B) + θ_AB


def test_too_few_pairs_leave_a_service_unreachable() -> None:
    found = offsets(chain(29, skew_b=200))
    assert found["B"] == (0, "none", 0.0)
    assert found["C"] == (0, "none", 0.0)
    assert found["A"][:2] == (0, "trace_pairs")


def test_root_falls_back_to_the_service_with_most_spans() -> None:
    found = offsets(chain(40, skew_c=-300), entry=("nowhere",))
    assert found["A"][2] == 1.0  # A and B tie at 80 spans: name order
    assert offsets([]) == {}


def test_kindless_spans_are_inferred_clients() -> None:
    spans = chain(40, skew_b=200, kind="unspecified")
    assert offsets(spans)["B"][0] == -213 * MS
    servers = [(t, s, p, svc, "unspecified" if k == "server" else k, a, b) for t, s, p, svc, k, a, b in spans]
    assert offsets(servers)["B"][0] == -213 * MS  # a kind-less server span has a foreign parent: not a client


def test_gate_thresholds() -> None:
    small = offsets(chain(40, skew_b=-10))  # |offset| = 3 ms < 5 ms although children stick out
    assert small["B"][0] == 0
    strict = replace(ALIGN, min_violation_share=1.0)
    mixed = chain(40, skew_b=200)[: 5 * 39] + chain(40)[5 * 39 :]
    assert trace_offsets(table(mixed), ["A"], strict)[1].offset_ns == 0  # 39/40 pairs violate
    assert trace_offsets(table(mixed), ["A"], ALIGN)[1].offset_ns == -213 * MS


@given(st.integers(min_value=-5000, max_value=5000).filter(lambda d: abs(d) >= 50), st.randoms())
def test_planted_skew_is_recovered_whatever_the_row_order(delta: int, rnd: object) -> None:
    spans = chain(40, skew_b=delta, skew_c=delta)
    found = offsets(spans)
    assert abs(found["B"][0] - (-delta - 13) * MS) == 0
    assert abs(found["B"][0] + delta * MS) <= 13 * MS  # −δ up to the client overhead bias
    shuffled = list(spans)
    rnd.shuffle(shuffled)  # type: ignore[attr-defined]  # hypothesis Random
    assert offsets(shuffled) == found


def test_synth_has_no_skew() -> None:
    spans = golden("telemetry.spans", "synth-04")
    assert isinstance(spans, pa.Table)
    found = trace_offsets(spans, ["frontend"], ALIGN)
    assert found
    assert all(o.offset_ns == 0 for o in found)
    assert {o.method for o in found} <= {"trace_pairs", "none"}
