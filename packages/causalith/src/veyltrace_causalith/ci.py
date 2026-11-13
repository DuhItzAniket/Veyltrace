"""Restricted conditional-independence test for trial T8 (05-causalith §3.7; IDI-lite).

Why: T8 asks whether the candidate's anomaly is explained by its parents (02 §6.9). In a call graph
a service's symptom has its callees and its own load as parents, so the test fits the candidate's
signal on those parents with baseline data only and asks whether the incident deviation survives in
the residual (IDI, ICLR 2025; card N4). Full causal discovery is out (02 §11): at most
`ci.max_parents` regressors, matrices of at most 6 × 6.

Pure functions: no files, clock or RNG (package AGENTS Never 3); float64; fixed parent order. The
robust scale floor of 03-anomara §3.2 is re-implemented here because Causalith must not import
Anomara (Anomara imports `entry`); a cross-engine test pins the parity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa

from veyltrace_core.errors import ConfigError

__all__ = [
    "CI_API_VERSION",
    "CIConfig",
    "CIResult",
    "CISeries",
    "effective_step",
    "grid_matrix",
    "latency_quantile",
    "persistent_max",
    "ridge_fit",
    "robust_scale",
    "series_by_id",
    "target_of",
]

CI_API_VERSION: Final = "1"
Floats = npt.NDArray[np.float64]


@dataclass(frozen=True)
class CIConfig:
    """`causalith.ci.*` plus Anomara's robust_z floor terms (03-anomara §3.2), so the scale matches,
    and its grid bucket (03-anomara §3.1), the step of traces and logs series."""

    max_parents: int
    ridge: float
    min_baseline_points: int
    threshold: float
    persist_steps: int
    mad_factor: float
    iqr_divisor: float
    eta: float
    epsilon: Mapping[str, Mapping[str, float]]
    bucket_ns: int

    def epsilon_for(self, family: str, unit: str | None) -> float:
        """ε(family, unit) with Anomara's fallbacks: the unit, the family's `*`, then `other.*`."""
        table = self.epsilon.get(family, {})
        if unit is not None and unit in table:
            return table[unit]
        return table.get("*", self.epsilon["other"]["*"])

    @classmethod
    def from_sections(cls, causalith: Mapping[str, Any], anomara: Mapping[str, Any]) -> CIConfig:
        """Build from the run's `causalith` and `anomara` config sections (ctx.config.section)."""
        try:
            ci = cast("Mapping[str, Any]", causalith["ci"])
            rz = cast("Mapping[str, Any]", anomara["robust_z"])
            grid = cast("Mapping[str, Any]", anomara["grid"])
            return cls(
                max_parents=int(ci["max_parents"]),
                ridge=float(ci["ridge"]),
                min_baseline_points=int(ci["min_baseline_points"]),
                threshold=float(ci["threshold"]),
                persist_steps=int(rz["persist_steps"]),
                mad_factor=float(rz["mad_factor"]),
                iqr_divisor=float(rz["iqr_divisor"]),
                eta=float(rz["eta"]),
                epsilon={
                    str(f): {str(u): float(e) for u, e in units.items()} for f, units in rz["epsilon"].items()
                },
                bucket_ns=int(grid["bucket_s"]) * 1_000_000_000,
            )
        except (KeyError, TypeError, ValueError) as exc:
            msg = f"causalith.ci / anomara.robust_z keys missing or malformed: {exc}"
            raise ConfigError(msg) from exc


@dataclass(frozen=True)
class CIResult:
    """Outcome of one intervention test (05 §3.7); a Python type, not a contract (03 §1)."""

    candidate: str
    target_series_id: str | None
    parents: tuple[str, ...]
    n_baseline: int
    n_incident: int
    stat_raw: float
    stat_resid: float
    explained_fraction: float
    p_value: float
    independent_of_parents: bool | None
    reason: str | None


def robust_scale(baseline: Floats, epsilon: float, cfg: CIConfig) -> tuple[float, float]:
    """(median, max(1.4826·MAD, IQR/1.349, ε, η·|median|)): Anomara's floor, re-implemented."""
    med = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - med)))
    q25, q75 = (float(q) for q in np.quantile(baseline, [0.25, 0.75], method="linear"))
    return med, max(cfg.mad_factor * mad, (q75 - q25) / cfg.iqr_divisor, epsilon, cfg.eta * abs(med))


#: Target priority (05 §3.7 step 1): (signal prefix, source), first present wins.
_TARGETS: Final = (
    ("latency_p99", "traces"),
    ("latency", "metrics"),
    ("error_rate", "traces"),
    ("error", "metrics"),
)
_LOAD: Final = ("rps", "workload")


@dataclass(frozen=True, eq=False)
class CISeries:
    """One `signal_cube.series` series as sorted arrays (the CI test's input view)."""

    series_id: str
    service: str
    signal: str
    family: str
    source: str
    unit: str | None
    t: npt.NDArray[np.int64]
    x: Floats


def series_by_id(table: pa.Table) -> dict[str, CISeries]:
    columns = ["series_id", "service", "signal", "family", "source", "unit", "t_ns", "value"]
    rows = table.select(columns).to_pylist()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["series_id"]), []).append(row)
    out: dict[str, CISeries] = {}
    for sid in sorted(grouped):
        pts = sorted(grouped[sid], key=lambda r: int(r["t_ns"]))
        first = pts[0]
        out[sid] = CISeries(
            sid,
            str(first["service"]),
            str(first["signal"]),
            str(first["family"]),
            str(first["source"]),
            first["unit"],
            np.asarray([int(p["t_ns"]) for p in pts], dtype=np.int64),
            np.asarray([float(p["value"]) for p in pts], dtype=np.float64),
        )
    return out


def latency_quantile(signal: str) -> float:
    digits = signal.removeprefix("latency_p")
    return float(f"0.{digits}") if digits.isdigit() and signal.startswith("latency_p") else -1.0


def target_of(service: str, series: Mapping[str, CISeries]) -> CISeries | None:
    """The service's target-priority series (05 §3.7 step 1); metric latency: highest quantile."""
    own = [s for s in series.values() if s.service == service]
    for prefix, source in _TARGETS:
        found = [
            s for s in own if s.source == source and (s.signal == prefix or s.signal.startswith(prefix + "_"))
        ]
        if prefix == "latency" and source == "metrics":
            found = [s for s in own if s.source == "metrics" and s.signal.startswith("latency")]
            found.sort(key=lambda s: (-latency_quantile(s.signal), s.series_id))
        else:
            found.sort(key=lambda s: s.series_id)
        if found:
            return found[0]
    return None


def effective_step(s: CISeries, bucket_ns: int) -> int:
    """Effective step `g` (03-anomara §3.1, as `veyltrace_anomara.series.effective_step`): for
    metrics, the median run of equal values, at least the median spacing; for traces and logs, and
    a metric with fewer than two points, the Signalyth bucket. The run rule on a bucketed series
    would coarsen the grid whenever buckets repeat a value (an error_rate of 0)."""
    if s.source != "metrics" or s.t.size < 2:
        return bucket_ns
    spacing = float(np.median(np.diff(s.t)))
    starts = np.concatenate(([0], np.flatnonzero(s.x[1:] != s.x[:-1]) + 1))
    runs = np.diff(s.t[starts])
    return max(int(np.rint(max(float(np.median(runs)), spacing) if runs.size else spacing)), 1)


def grid_matrix(
    columns: Sequence[CISeries], span: tuple[int, int], bucket_ns: int
) -> tuple[npt.NDArray[np.int64], Floats, int]:
    """Bucket starts, a (buckets × columns) matrix (last value per bucket, rows all observed) and
    the grid step, the largest effective step of the columns."""
    step = max(effective_step(s, bucket_ns) for s in columns)
    first = -(-span[0] // step)
    count = max(-(-span[1] // step) - first, 0)
    matrix = np.full((count, len(columns)), np.nan)
    for j, s in enumerate(columns):
        inside = (s.t >= span[0]) & (s.t < span[1])
        index = s.t[inside] // step - first
        keep = index >= 0
        index, values = index[keep], s.x[inside][keep]
        if index.size:
            last = np.flatnonzero(np.concatenate((index[1:] != index[:-1], [True])))
            matrix[index[last], j] = values[last]
    rows = ~np.isnan(matrix).any(axis=1)
    return ((first + np.arange(count, dtype=np.int64)) * step)[rows], matrix[rows], step


def persistent_max(z: Floats, starts: npt.NDArray[np.int64], step: int, p: int) -> float:
    """Max over t of min |z| on [t, t + p·g) when those p grid buckets are all kept and share one
    sign (03-anomara §3.2 step 4). Kept rows far apart in time (the joint grid drops buckets where a
    column is missing) never form a run, so isolated spikes are not persistent."""
    best = 0.0
    for i in range(z.size - p + 1):
        window = z[i : i + p]
        contiguous = int(starts[i + p - 1] - starts[i]) == (p - 1) * step
        if contiguous and (bool((window > 0).all()) or bool((window < 0).all())):
            best = max(best, float(np.min(np.abs(window))))
    return best


def ridge_fit(z: Floats, x: Floats, ridge: float) -> tuple[Floats, float, float] | None:
    """Coefficients, intercept terms (column means, x mean) of a ridge fit with an unpenalised
    intercept: centre, then solve (ZᵀZ + λ n I) b = Zᵀx. None if the system is singular."""
    zm, xm = z.mean(axis=0), float(x.mean())
    zc, xc = z - zm, x - xm
    gram: Floats = zc.T @ zc + ridge * z.shape[0] * np.eye(z.shape[1])
    rhs: Floats = zc.T @ xc
    try:
        b = np.linalg.solve(gram, rhs)
    except np.linalg.LinAlgError:
        return None
    return b, float(zm @ b), xm
