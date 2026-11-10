"""05 §13: the validation rule on synthetic SLI series (breach, no breach, no-fault control)."""

import json
from pathlib import Path

from vlab.validate import BUCKET_S, Bucket, buckets, evaluate, p95, validate_capture

S = 1_000_000_000
T = 1_800_000_000 * S  # t_inject


def _series(
    base_ms: float, after_ms: list[float], base_err: float = 0.0, after_err: float | None = None
) -> list[Bucket]:
    """20 baseline buckets (10 min) with a little noise, then the given post-injection buckets."""
    base = [Bucket(i, 100, base_ms + (i % 3), base_err) for i in range(-20, 0)]
    err = base_err if after_err is None else after_err
    return base + [Bucket(i, 100, v, err) for i, v in enumerate(after_ms)]


def test_two_consecutive_buckets_over_threshold_validate_a_fault() -> None:
    v = evaluate(_series(70, [70, 300, 320, 70]), is_no_fault=False)
    assert (v.validated, v.reason) == (True, "impact")
    assert v.impact["p95_ms"]["first_breach_s"] == BUCKET_S


def test_a_single_spike_is_not_enough() -> None:
    v = evaluate(_series(70, [300, 70, 300, 70]), is_no_fault=False)
    assert (v.validated, v.reason) == (False, "no_impact")


def test_a_breach_after_the_five_minute_window_does_not_count() -> None:
    v = evaluate(_series(70, [70] * 10 + [400, 400]), is_no_fault=False)
    assert not v.validated


def test_error_rate_alone_can_validate() -> None:
    v = evaluate(_series(70, [70, 70, 70], base_err=0.0, after_err=0.2), is_no_fault=False)
    assert v.validated and v.impact["error_rate"]["first_breach_s"] == 0
    assert v.impact["p95_ms"]["first_breach_s"] is None


def test_zero_error_baseline_needs_more_than_one_failed_request() -> None:
    # 1 failure in 300 requests is 0.33%: below the 0.5-point floor, so no breach.
    v = evaluate(_series(70, [70, 70], base_err=0.0, after_err=1 / 300), is_no_fault=False)
    assert not v.validated


def test_no_fault_control_is_kept_only_without_breach() -> None:
    clean = evaluate(_series(70, [71, 69, 72]), is_no_fault=True)
    assert (clean.validated, clean.reason) == (True, "clean_control")
    noisy = evaluate(_series(70, [300, 300]), is_no_fault=True)
    assert (noisy.validated, noisy.reason) == (False, "control_breached")


def test_short_baseline_is_not_validated() -> None:
    series = [Bucket(i, 100, 70, 0) for i in range(-3, 0)] + [Bucket(0, 100, 900, 0), Bucket(1, 100, 900, 0)]
    assert evaluate(series, is_no_fault=False).reason == "insufficient_baseline"


def test_p95_is_nearest_rank() -> None:
    assert p95(list(range(1, 101))) == 95
    assert p95([5.0]) == 5.0


def test_buckets_align_to_injection() -> None:
    spans = [
        (T - 1, 10.0, False),
        (T, 20.0, True),
        (T + BUCKET_S * S - 1, 30.0, False),
        (T + BUCKET_S * S, 40.0, False),
    ]
    got = buckets(spans, T)
    assert [(b.index, b.n, b.error_rate) for b in got] == [(-1, 1, 0.0), (0, 2, 0.5), (1, 1, 0.0)]


def test_validate_capture_reads_frontend_server_spans(tmp_path: Path) -> None:
    def span(t: int, ms: int, kind: int = 2, err: bool = False) -> dict[str, object]:
        return {
            "kind": kind,
            "startTimeUnixNano": str(t),
            "endTimeUnixNano": str(t + ms * 1_000_000),
            "status": {"code": 2} if err else {},
        }

    def req(service: str, spans: list[dict[str, object]]) -> str:
        res = {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]}
        return json.dumps({"resourceSpans": [{"resource": res, "scopeSpans": [{"spans": spans}]}]}) + "\n"

    otlp = tmp_path / "otlp"
    otlp.mkdir()
    before = [span(T - j * 5 * S, 20) for j in range(1, 121)]  # 10 min of fast requests
    slow = [span(T + j * 5 * S, 900) for j in range(0, 24)]  # 2 min of slow ones
    other = [span(T + j * S, 5000) for j in range(10)]  # a slow backend must not count
    client = [span(T + j * S, 5000, kind=3) for j in range(10)]  # nor client spans
    (otlp / "traces.jsonl").write_text(
        req("frontend", before + slow + client) + req("cartservice", other), encoding="utf-8"
    )
    v = validate_capture(tmp_path, {"t_inject_ns": T, "is_no_fault": False})
    assert v.validated and v.impact["p95_ms"]["max_after"] == 900.0
    assert json.loads(v.sli_impact_json)["rule"] == "05-8.2"
