"""The 05 §8.2 validation rule: keep a case only if user-facing impact is measurable.

SLIs are the entry service's server-span p95 latency and error rate in 30 s buckets, aligned to the
injection time. The baseline gives each SLI a median and a MAD; a fault case is validated when, within
5 minutes after ``t_inject``, at least 2 consecutive buckets exceed ``median + k × MAD`` for either
SLI. A no-fault control is validated only when no such breach occurs.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vlab.answer_key import canonical_json

ENTRY_SERVICE = "frontend"  # OB's entry service (05 §8.2 rule 1)
SPAN_KIND_SERVER = 2  # OTLP SpanKind
STATUS_ERROR = 2  # OTLP StatusCode
BUCKET_S = 30  # 05 §8.2 rule 1
K = 5  # 05 §8.2 rule 3 (a priori)
WINDOW_S = 300  # 05 §8.2 rule 3: N = 5 min after t_inject
CONSECUTIVE = 2  # 05 §8.2 rule 3
MAD_FLOOR_FRAC = 0.01  # 05 §8.2 rule 2: MAD floored at 1% of the median (a priori)
#: Absolute MAD floors (a priori, ADR 20261110-cl-lab-validation): with an error-free baseline the
#: median and MAD are 0, and "1% of the median" would make one failed request a breach.
ABS_FLOOR = {"p95_ms": 1.0, "error_rate": 0.005}
#: Fewer baseline buckets than this (3 min) cannot give a stable median and MAD (a priori).
MIN_BASELINE_BUCKETS = 6


@dataclass(frozen=True)
class Bucket:
    index: int  # bucket number relative to t_inject (0 = the first bucket after injection)
    n: int
    p95_ms: float
    error_rate: float


def _resource_service(rs: Mapping[str, Any]) -> str | None:
    for attr in rs.get("resource", {}).get("attributes", []):
        if attr.get("key") == "service.name":
            return next(iter(attr.get("value", {}).values()), None)
    return None


def entry_spans(otlp_dir: Path, service: str = ENTRY_SERVICE) -> Iterable[tuple[int, float, bool]]:
    """(start ns, duration ms, is error) of every server span of ``service`` in a raw capture."""
    for path in sorted(otlp_dir.glob("traces*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                for rs in json.loads(line).get("resourceSpans", []):
                    if _resource_service(rs) != service:
                        continue
                    for ss in rs.get("scopeSpans", []):
                        for sp in ss.get("spans", []):
                            if sp.get("kind") != SPAN_KIND_SERVER:
                                continue
                            start = int(sp["startTimeUnixNano"])
                            duration_ms = (int(sp["endTimeUnixNano"]) - start) / 1e6
                            yield start, duration_ms, sp.get("status", {}).get("code") == STATUS_ERROR


def p95(values: Sequence[float]) -> float:
    """Nearest-rank 95th percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def buckets(
    spans: Iterable[tuple[int, float, bool]], t_inject_ns: int, bucket_s: int = BUCKET_S
) -> list[Bucket]:
    """Spans grouped into buckets aligned to ``t_inject_ns``; buckets without spans are absent."""
    width = bucket_s * 1_000_000_000
    groups: dict[int, list[tuple[float, bool]]] = {}
    for start, duration_ms, error in spans:
        groups.setdefault((start - t_inject_ns) // width, []).append((duration_ms, error))
    return [
        Bucket(i, len(g), p95([d for d, _ in g]), sum(e for _, e in g) / len(g))
        for i, g in sorted(groups.items())
    ]


def _sli(
    name: str, baseline: Sequence[float], after: Sequence[tuple[int, float]], k: float
) -> dict[str, Any]:
    median = statistics.median(baseline)
    mad = statistics.median(abs(v - median) for v in baseline)
    floored = max(mad, MAD_FLOOR_FRAC * median, ABS_FLOOR[name])
    threshold = median + k * floored
    run, first = 0, None
    for index, value in after:
        run = run + 1 if value > threshold else 0
        if run >= CONSECUTIVE and first is None:
            first = (index - CONSECUTIVE + 1) * BUCKET_S
    return {
        "median": round(median, 4),
        "mad": round(mad, 4),
        "threshold": round(threshold, 4),
        "max_after": round(max((v for _, v in after), default=0.0), 4),
        "first_breach_s": first,
    }


@dataclass(frozen=True)
class Validation:
    validated: bool
    breach: bool
    reason: str
    impact: dict[str, Any]

    @property
    def sli_impact_json(self) -> str:
        return canonical_json(self.impact)


def evaluate(series: Sequence[Bucket], *, is_no_fault: bool, k: float = K) -> Validation:
    """Apply rules 2-4 to buckets from :func:`buckets`."""
    base = [b for b in series if b.index < 0]
    after = [b for b in series if 0 <= b.index < WINDOW_S // BUCKET_S]
    impact: dict[str, Any] = {
        "rule": "05-8.2",
        "entry_service": ENTRY_SERVICE,
        "bucket_s": BUCKET_S,
        "k": k,
        "window_s": WINDOW_S,
        "baseline_buckets": len(base),
        "after_buckets": len(after),
    }
    if len(base) < MIN_BASELINE_BUCKETS:
        return Validation(False, False, "insufficient_baseline", impact)
    for name in ("p95_ms", "error_rate"):
        impact[name] = _sli(
            name, [getattr(b, name) for b in base], [(b.index, getattr(b, name)) for b in after], k
        )
    breach = any(impact[n]["first_breach_s"] is not None for n in ("p95_ms", "error_rate"))
    if is_no_fault:
        return Validation(not breach, breach, "control_breached" if breach else "clean_control", impact)
    return Validation(breach, breach, "impact" if breach else "no_impact", impact)


def validate_capture(capture_dir: Path, key: Mapping[str, Any]) -> Validation:
    """The rule over one raw capture and its answer key."""
    spans = entry_spans(capture_dir / "otlp")
    return evaluate(buckets(spans, int(key["t_inject_ns"])), is_no_fault=bool(key["is_no_fault"]))
