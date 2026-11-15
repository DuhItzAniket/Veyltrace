"""Metric series (02 §3.2): one typed series per (service, component, signal) on its native grid.

Each raw metric name is mapped to a `signal`, `family` and `klass` by the first matching rule of
`metrics.family_rules` (the PRISM internal/external split, 02 §6.2); latency becomes ms; counters
become per-second rates. Points stay at their observation times: no resampling, no forward fill
(02 §3.1). Nothing here reads `alert.json`, so series never move with the windows.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

__all__ = ["CounterRules", "FamilyRule", "MetricRules", "metric_series", "sanitise"]

_pc: Any = pc  # pyarrow-stubs type compute kernels with Unknown parts (as core's io.py)
type Vec = np.ndarray[Any, Any]
NS: Final = 1_000_000_000
#: Latency units → factor to ms (02 §3.2 step 2).
_TO_MS: Final = {"s": 1000.0, "ms": 1.0, "us": 0.001, "\u00b5s": 0.001}
#: Memory units → factor to bytes (02 §3.2 step 2; SI prefixes are powers of 10, IEC of 2). A
#: memory series in any other unit (a percentage, an unknown or missing unit) keeps its unit.
_TO_BYTES: Final = {
    "b": 1.0, "byte": 1.0, "bytes": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9,
    "kib": 2.0**10, "mib": 2.0**20, "gib": 2.0**30,
}  # fmt: skip
_SANITISE: Final = re.compile(r"[|\s]")
#: A quantile in a name: `quantile="0.99"`, `-50`, `_p99`, `p90` (02 §3.2 rule 5).
_QUANTILE: Final = re.compile(r'quantile="?(0?\.\d+)|(?:[-_]p?|\bp)(\d{2,3})(?!\d)')


def sanitise(name: str) -> str:
    """`|` and whitespace → `-`, so a signal never breaks a series_id (02 §2; AGENTS Never 4)."""
    return _SANITISE.sub("-", name)


@dataclass(frozen=True)
class FamilyRule:
    """One row of 02 §3.2: `signal` is a fixed name or `{name}` (the sanitised raw name); `exact`
    is a raw name that keeps itself as signal (`diskio`); `quantile` appends `_p{q}`."""

    pattern: re.Pattern[str]
    signal: str
    family: str
    klass: str
    exact: str | None = None
    quantile: bool = False

    def signal_for(self, name: str) -> str:
        if self.signal == "{name}":
            return sanitise(name)
        if self.exact is not None and name.lower() == self.exact:
            return self.exact
        if self.quantile and (found := _QUANTILE.search(name.lower())) is not None:
            fraction, digits = found.groups()
            q = format(float(fraction) * 100, "g") if fraction else digits
            return f"{self.signal}_p{q}"
        return self.signal


@dataclass(frozen=True)
class CounterRules:
    """`metrics.counter_*` (02 §3.2 step 3, §4)."""

    name_patterns: tuple[re.Pattern[str], ...]
    shape_test: bool
    min_increases: int
    min_increase_share: float
    reset_ratio: float
    exclude_families: frozenset[str]


@dataclass(frozen=True)
class MetricRules:
    family_rules: tuple[FamilyRule, ...]
    counters: CounterRules

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> MetricRules:
        section = cast("Mapping[str, Any]", cfg["metrics"])
        rules = tuple(
            FamilyRule(
                re.compile(str(r["pattern"]), re.IGNORECASE),
                str(r["signal"]),
                str(r["family"]),
                str(r["klass"]),
                r.get("exact"),
                bool(r.get("quantile", False)),
            )
            for r in cast("Sequence[Mapping[str, Any]]", section["family_rules"])
        )
        shape = cast("Mapping[str, Any]", section["counter_shape"])
        counters = CounterRules(
            tuple(re.compile(str(p)) for p in section["counter_name_patterns"]),
            bool(section["counter_shape_test"]),
            int(shape["min_increases"]),
            float(shape["min_increase_share"]),
            float(shape["reset_ratio"]),
            frozenset(str(f) for f in shape["exclude_families"]),
        )
        return cls(rules, counters)

    def classify(self, name: str) -> FamilyRule:
        """The first rule whose pattern matches `name` (the table ends with a catch-all)."""
        for rule in self.family_rules:
            if rule.pattern.search(name):
                return rule
        raise ValueError(f"no metrics.family_rules entry matches {name!r}; the table needs a catch-all")

    def is_named_counter(self, name: str) -> bool:
        """A counter by name (`metrics.counter_name_patterns`): monotone by contract, so any
        decrease is a reset (Prometheus semantics)."""
        return any(p.search(name) for p in self.counters.name_patterns)

    def is_counter(self, name: str, family: str, values: Vec) -> bool:
        """Name rule, else the shape test: ≥ 0, enough increases, ≥ 99 % of changes increases
        (a drop below `reset_ratio` of the previous value is a reset, not a decrease)."""
        c = self.counters
        if self.is_named_counter(name):
            return True
        if not c.shape_test or family in c.exclude_families or values.size < 2 or bool((values < 0).any()):
            return False
        prev, nxt = values[:-1], values[1:]
        increases = int((nxt > prev).sum())
        decreases = int(((nxt < prev) & (nxt >= c.reset_ratio * prev)).sum())
        return increases >= c.min_increases and increases >= c.min_increase_share * (increases + decreases)


def _rate(t_ns: Vec, values: Vec, reset_ratio: float) -> tuple[Vec, Vec]:
    """Per-second rate between consecutive points, at the later point; the first point has no
    rate. A reset, a drop below `reset_ratio` of the previous value, counts the new value from
    zero; any other step is `(v2 - v1) / dt` (02 §3.2 step 3). Named counters pass 1.0 (every
    decrease is a reset); shape counters pass `counter_shape.reset_ratio`, so the small dips the
    shape test admits stay small steps instead of becoming spikes."""
    dt = np.diff(t_ns).astype(np.float64) / NS
    reset = values[1:] < reset_ratio * values[:-1]
    rate = np.where(reset, values[1:], np.diff(values)) / dt
    return t_ns[1:], rate


def metric_series(metrics: pa.Table, rules: MetricRules) -> dict[str, list[Any]]:
    """Series rows (as columns) from `telemetry.metrics` (`t_ns, service, component, name, value,
    unit`), sorted by (service, component, name, t_ns)."""
    out: dict[str, list[Any]] = {
        k: [] for k in ("service", "component", "signal", "family", "klass", "unit", "t_ns", "value")
    }
    if metrics.num_rows == 0:
        return out
    order = _pc.sort_indices(
        metrics, sort_keys=[(k, "ascending") for k in ("service", "component", "name", "t_ns")]
    )
    m = metrics.take(order)
    keys = list(zip(*(m.column(k).to_pylist() for k in ("service", "component", "name")), strict=True))
    t_all = np.asarray(m.column("t_ns").to_numpy(), dtype=np.int64)
    v_all = np.asarray(m.column("value").to_numpy(), dtype=np.float64)
    units = m.column("unit").to_pylist()
    starts = [0] + [i for i in range(1, len(keys)) if keys[i] != keys[i - 1]] + [len(keys)]
    groups = [(keys[a], a, b) for a, b in pairwise(starts)]
    named = {(s, c, n): (rule := rules.classify(n), rule.signal_for(n)) for (s, c, n), _, _ in groups}
    taken: dict[tuple[str, str, str], int] = {}
    for (s, c, _), (_, signal) in named.items():
        taken[(s, c, signal)] = taken.get((s, c, signal), 0) + 1
    for (service, component, name), a, b in groups:
        rule, signal = named[(service, component, name)]
        if taken[(service, component, signal)] > 1:
            signal = f"{signal}:{sanitise(name)}"  # 02 §3.2: two raw names, one signal
        t, v, unit = t_all[a:b], v_all[a:b], cast("str | None", units[a])
        if rule.family == "latency" and unit is not None and unit.lower() in _TO_MS:
            v, unit = v * _TO_MS[unit.lower()], "ms"
        if rule.family == "mem" and unit is not None and unit.lower() in _TO_BYTES:
            v, unit = v * _TO_BYTES[unit.lower()], "bytes"
        if rules.is_counter(name, rule.family, v):
            t, v = _rate(t, v, 1.0 if rules.is_named_counter(name) else rules.counters.reset_ratio)
            unit = f"{unit}/s" if unit else "1/s"
        n = int(t.size)
        for key, value in (
            ("service", service),
            ("component", component),
            ("signal", signal),
            ("family", rule.family),
            ("klass", rule.klass),
            ("unit", unit),
        ):
            out[key].extend([value] * n)
        out["t_ns"].extend(t.tolist())
        out["value"].extend(v.tolist())
    return out
