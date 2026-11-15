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
    p95_ms: float | None  # None when the bucket has no server span (the entry service was silent)
    error_rate: float | None


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
    spans: Iterable[tuple[int, float, bool]],
    t_inject_ns: int,
    *,
    first_index: int | None = None,
    bucket_s: int = BUCKET_S,
) -> list[Bucket]:
    """Every bucket from ``first_index`` (default: the earliest span's) through the rule window,
    aligned to ``t_inject_ns``. A bucket without spans is kept with ``n = 0``: a silent entry
    service is an outage, not a missing data point (05 §8.2)."""
    width = bucket_s * 1_000_000_000
    groups: dict[int, list[tuple[float, bool]]] = {}
    for start, duration_ms, error in spans:
        groups.setdefault((start - t_inject_ns) // width, []).append((duration_ms, error))
    lo = first_index if first_index is not None else min(groups, default=0)
    hi = max(WINDOW_S // bucket_s, max(groups, default=-1) + 1)
    out = []
    for i in range(lo, hi):
        g = groups.get(i, [])
        out.append(
            Bucket(i, len(g), p95([d for d, _ in g]), sum(e for _, e in g) / len(g))
            if g
            else Bucket(i, 0, None, None)
        )
    return out


def _sli(name: str, baseline: Sequence[float], after: Sequence[Bucket], k: float) -> dict[str, Any]:
    """Threshold and first breach of one SLI. ``after`` holds every bucket of the window in index
    order, so a run is adjacent by construction; a silent bucket breaches."""
    median = statistics.median(baseline)
    mad = statistics.median(abs(v - median) for v in baseline)
    floored = max(mad, MAD_FLOOR_FRAC * median, ABS_FLOOR[name])
    threshold = median + k * floored
    run, first = 0, None
    for b in after:
        value = getattr(b, name)
        run = run + 1 if value is None or value > threshold else 0
        if run >= CONSECUTIVE and first is None:
            first = (b.index - CONSECUTIVE + 1) * BUCKET_S
    seen = [getattr(b, name) for b in after if getattr(b, name) is not None]
    return {
        "median": round(median, 4),
        "mad": round(mad, 4),
        "threshold": round(threshold, 4),
        "max_after": round(max(seen, default=0.0), 4),
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


def _done(validated: bool, breach: bool, reason: str, impact: dict[str, Any]) -> Validation:
    return Validation(validated, breach, reason, {**impact, "reason": reason})


def evaluate(series: Sequence[Bucket], *, is_no_fault: bool, k: float = K) -> Validation:
    """Apply rules 2-4 to buckets from :func:`buckets`; a window bucket missing from ``series``
    counts as silent."""
    by_index = {b.index: b for b in series}
    after = [by_index.get(i, Bucket(i, 0, None, None)) for i in range(WINDOW_S // BUCKET_S)]
    base = [b for b in series if b.index < 0 and b.n > 0]  # silent baseline buckets carry no SLI
    impact: dict[str, Any] = {
        "rule": "05-8.2",
        "entry_service": ENTRY_SERVICE,
        "bucket_s": BUCKET_S,
        "k": k,
        "window_s": WINDOW_S,
        "baseline_buckets": len(base),
        "silent_after_buckets": sum(b.n == 0 for b in after),
    }
    if len(base) < MIN_BASELINE_BUCKETS:
        return _done(False, False, "insufficient_baseline", impact)
    for name in ("p95_ms", "error_rate"):
        impact[name] = _sli(name, [getattr(b, name) for b in base], after, k)
    breach = any(impact[n]["first_breach_s"] is not None for n in ("p95_ms", "error_rate"))
    if is_no_fault:
        return _done(not breach, breach, "control_breached" if breach else "clean_control", impact)
    return _done(breach, breach, "impact" if breach else "no_impact", impact)


def reference_time_ns(capture_dir: Path, key: Mapping[str, Any]) -> int | None:
    """``t_inject_ns`` of a fault key; for a no-fault control (null in the key, 03 §13.1) the
    reference time the campaign recorded in orchestrator.json."""
    if key.get("t_inject_ns") is not None:
        return int(key["t_inject_ns"])
    orch = capture_dir / "orchestrator.json"
    if orch.is_file():
        t = json.loads(orch.read_text(encoding="utf-8")).get("t_inject_ns")
        return None if t is None else int(t)
    return None


def validate_capture(capture_dir: Path, key: Mapping[str, Any]) -> Validation:
    """The rule over one raw capture and its answer key."""
    t_ref = reference_time_ns(capture_dir, key)
    if t_ref is None:
        return _done(False, False, "no_reference_time", {"rule": "05-8.2"})
    first_index = None
    orch = capture_dir / "orchestrator.json"
    if orch.is_file():
        t_start = json.loads(orch.read_text(encoding="utf-8")).get("t_capture_start_ns")
        if t_start is not None:
            first_index = (int(t_start) - t_ref) // (BUCKET_S * 1_000_000_000)
    spans = entry_spans(capture_dir / "otlp")
    return evaluate(buckets(spans, t_ref, first_index=first_index), is_no_fault=bool(key["is_no_fault"]))
