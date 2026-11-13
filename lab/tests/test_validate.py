"""05 §13: the validation rule on synthetic SLI series (breach, no breach, no-fault control)."""

import json
from pathlib import Path

import pytest
from vlab.validate import ABS_FLOOR, BUCKET_S, WINDOW_S, Bucket, buckets, evaluate, p95, validate_capture

S = 1_000_000_000
T = 1_800_000_000 * S  # t_inject
AFTER = WINDOW_S // BUCKET_S  # 10 buckets in the rule window


def _series(
    base_ms: float,
    after_ms: list[float | None],
    base_err: float = 0.0,
    after_err: float | None = None,
) -> list[Bucket]:
    """20 baseline buckets (10 min) with a little noise, then the post-injection buckets, padded with
    the baseline level to the full window. ``None`` in ``after_ms`` is a silent (empty) bucket."""
    base = [Bucket(i, 100, base_ms + (i % 3), base_err) for i in range(-20, 0)]
    err = base_err if after_err is None else after_err
    padded = after_ms + [base_ms] * (AFTER - len(after_ms))
    return base + [
        Bucket(i, 0, None, None) if v is None else Bucket(i, 100, v, err) for i, v in enumerate(padded)
    ]


def test_two_consecutive_buckets_over_threshold_validate_a_fault() -> None:
    v = evaluate(_series(70, [70, 300, 320, 70]), is_no_fault=False)
    assert (v.validated, v.reason) == (True, "impact")
    assert v.impact["p95_ms"]["first_breach_s"] == BUCKET_S
    assert json.loads(v.sli_impact_json)["reason"] == "impact"


def test_a_single_spike_is_not_enough() -> None:
    v = evaluate(_series(70, [300, 70, 300, 70]), is_no_fault=False)
    assert (v.validated, v.reason) == (False, "no_impact")


def test_breaches_with_a_normal_bucket_between_are_not_consecutive() -> None:
    # Regression (#222 review): breaches at buckets 0 and 9 used to count as a run.
    v = evaluate(_series(70, [300, *[70] * 8, 300]), is_no_fault=False)
    assert (v.validated, v.impact["p95_ms"]["first_breach_s"]) == (False, None)


def test_first_breach_comes_from_the_bucket_index() -> None:
    v = evaluate(_series(70, [70, 70, 70, 400, 400]), is_no_fault=False)
    assert v.impact["p95_ms"]["first_breach_s"] == 3 * BUCKET_S


def test_a_fully_silent_window_is_an_outage() -> None:
    # Regression (#222 review): F08 on frontend leaves no server spans; that is impact, not "no_impact".
    v = evaluate(_series(70, [None] * AFTER), is_no_fault=False)
    assert (v.validated, v.reason) == (True, "impact")
    assert v.impact["silent_after_buckets"] == AFTER
    assert v.impact["p95_ms"]["first_breach_s"] == 0


def test_two_silent_buckets_breach_and_a_missing_bucket_counts_as_silent() -> None:
    assert evaluate(_series(70, [70, None, None]), is_no_fault=False).validated
    series = [b for b in _series(70, []) if b.index not in (4, 5)]  # dropped from the series entirely
    v = evaluate(series, is_no_fault=False)
    assert v.validated and v.impact["silent_after_buckets"] == 2


def test_a_breach_after_the_five_minute_window_does_not_count() -> None:
    v = evaluate(_series(70, [70] * AFTER + [400, 400]), is_no_fault=False)
    assert not v.validated


def test_error_rate_alone_can_validate() -> None:
    v = evaluate(_series(70, [70, 70, 70], base_err=0.0, after_err=0.2), is_no_fault=False)
    assert v.validated and v.impact["error_rate"]["first_breach_s"] == 0
    assert v.impact["p95_ms"]["first_breach_s"] is None


def test_the_floors_are_pinned() -> None:
    assert ABS_FLOOR == {"p95_ms": 1.0, "error_rate": 0.005}
    # Flat baseline: the absolute floors set the thresholds exactly (median + 5 × floor).
    flat = [Bucket(i, 100, 70.0, 0.0) for i in range(-20, 0)] + [
        Bucket(i, 100, 70.0, 0.0) for i in range(AFTER)
    ]
    v = evaluate(flat, is_no_fault=False)
    assert v.impact["p95_ms"]["threshold"] == pytest.approx(70.0 + 5 * 1.0)
    assert v.impact["error_rate"]["threshold"] == pytest.approx(0.025)


def test_zero_error_baseline_needs_more_than_one_failed_request() -> None:
    # 1 failure in 300 requests is 0.33%: below the 0.5-point floor, so no breach.
    v = evaluate(_series(70, [70, 70], base_err=0.0, after_err=1 / 300), is_no_fault=False)
    assert not v.validated


def test_no_fault_control_is_kept_only_without_breach() -> None:
    clean = evaluate(_series(70, [71, 69, 72]), is_no_fault=True)
    assert (clean.validated, clean.reason) == (True, "clean_control")
    noisy = evaluate(_series(70, [300, 300]), is_no_fault=True)
    assert (noisy.validated, noisy.reason) == (False, "control_breached")
    spread = evaluate(_series(70, [70, 300, 70, 70, 70, 300]), is_no_fault=True)
    assert spread.validated  # breaches at buckets 1 and 5 are not a run


def test_short_baseline_is_not_validated() -> None:
    series = [Bucket(i, 100, 70, 0) for i in range(-3, 0)] + [Bucket(0, 100, 900, 0), Bucket(1, 100, 900, 0)]
    assert evaluate(series, is_no_fault=False).reason == "insufficient_baseline"


def test_p95_is_nearest_rank() -> None:
    assert p95(list(range(1, 101))) == 95
    assert p95([5.0]) == 5.0


def test_buckets_align_to_injection_and_keep_empty_ones() -> None:
    spans = [
        (T - 1, 10.0, False),
        (T, 20.0, True),
        (T + BUCKET_S * S - 1, 30.0, False),
        (T + 3 * BUCKET_S * S, 40.0, False),
    ]
    got = buckets(spans, T, first_index=-2)
    assert [(b.index, b.n, b.error_rate) for b in got][:5] == [
        (-2, 0, None), (-1, 1, 0.0), (0, 2, 0.5), (1, 0, None), (2, 0, None),
    ]  # fmt: skip
    assert got[-1].index == AFTER - 1  # always reaches the end of the rule window


def _span(t: int, ms: int, kind: int = 2, err: bool = False) -> dict[str, object]:
    return {
        "kind": kind,
        "startTimeUnixNano": str(t),
        "endTimeUnixNano": str(t + ms * 1_000_000),
        "status": {"code": 2} if err else {},
    }


def _req(service: str, spans: list[dict[str, object]]) -> str:
    res = {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]}
    return json.dumps({"resourceSpans": [{"resource": res, "scopeSpans": [{"spans": spans}]}]}) + "\n"


def test_validate_capture_reads_frontend_server_spans(tmp_path: Path) -> None:
    otlp = tmp_path / "otlp"
    otlp.mkdir()
    before = [_span(T - j * 5 * S, 20) for j in range(1, 121)]  # 10 min of fast requests
    slow = [_span(T + j * 5 * S, 900) for j in range(0, 24)]  # 2 min of slow ones
    rest = [_span(T + 120 * S + j * 5 * S, 20) for j in range(0, 36)]  # then healthy again
    other = [_span(T + j * S, 5000) for j in range(10)]  # a slow backend must not count
    client = [_span(T + j * S, 5000, kind=3) for j in range(10)]  # nor client spans
    (otlp / "traces.jsonl").write_text(
        _req("frontend", before + slow + rest + client) + _req("cartservice", other), encoding="utf-8"
    )
    v = validate_capture(tmp_path, {"t_inject_ns": T, "is_no_fault": False})
    assert v.validated and v.impact["p95_ms"]["max_after"] == 900.0
    assert json.loads(v.sli_impact_json)["rule"] == "05-8.2"


def test_no_fault_capture_uses_the_orchestrator_reference_time(tmp_path: Path) -> None:
    # F14 keys have null t_inject_ns (03 §13.1); the reference time comes from orchestrator.json.
    otlp = tmp_path / "otlp"
    otlp.mkdir()
    steady = [_span(T + j * 5 * S, 20) for j in range(-120, 60)]
    (otlp / "traces.jsonl").write_text(_req("frontend", steady), encoding="utf-8")
    (tmp_path / "orchestrator.json").write_text(
        json.dumps({"t_inject_ns": T, "t_capture_start_ns": T - 600 * S}), encoding="utf-8"
    )
    v = validate_capture(tmp_path, {"t_inject_ns": None, "is_no_fault": True})
    assert (v.validated, v.reason) == (True, "clean_control")
    assert validate_capture(tmp_path / "missing", {"t_inject_ns": None, "is_no_fault": True}).reason == (
        "no_reference_time"
    )
