"""Changed-vs-peer contrast (04-causync §3.6): do changed replicas look worse than the rest?

A cohort test in the style of staged-rollout health checks: the replicas a change touched are
compared with the replicas of the same service it did not touch. The score is in raw robust-z
units (max `anomalies.score` of `robust_z`), the units of FaultLoom's own peer atom, and is null
whenever there is no cohort to compare: fewer than `peer.min_replicas` replicas, an empty
changed or peer set, or cluster scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pyarrow as pa

from veyltrace_causync.changes import Change
from veyltrace_causync.steps import series_groups

__all__ = ["ANOMALY_COLUMNS", "Replicas", "peer_contrast", "replica_scores", "replicas"]

ANOMALY_COLUMNS: Final = ("component", "klass", "detector", "score")
#: Kinds that replace or add replicas of a service: its changed set is the replicas first seen
#: at or after the change (the new pods of a rollout).
ROLLOUT_KINDS: Final = frozenset({"deploy", "config", "restart", "scale"})
_SCORED_KLASS: Final = frozenset({"internal", "external"})


@dataclass(frozen=True)
class Replicas:
    """Replicas of every service: {service: {component: (first_seen_ns, last_seen_ns)}}, from
    the components of `signal_cube.series` other than the service itself."""

    seen: Mapping[str, Mapping[str, tuple[int, int]]]

    @property
    def service_of(self) -> dict[str, str]:
        """{component: service}; a name used by two services belongs to the first A→Z."""
        out: dict[str, str] = {}
        for service in sorted(self.seen, reverse=True):
            out.update(dict.fromkeys(self.seen[service], service))
        return out


def replicas(series: pa.Table) -> Replicas:
    """First and last observation of every replica (SERIES_COLUMNS of `signal_cube.series`)."""
    seen: dict[str, dict[str, tuple[int, int]]] = {}
    for (_, service, component, _), t, _ in series_groups(series):
        if component == service or t.size == 0:
            continue
        first, last = seen.setdefault(service, {}).get(component, (int(t[0]), int(t[-1])))
        seen[service][component] = (min(first, int(t[0])), max(last, int(t[-1])))
    return Replicas(seen)


def replica_scores(anomalies: pa.Table) -> dict[str, float]:
    """`a(k)` per component: the max raw robust-z score over its internal and external series."""
    out: dict[str, float] = {}
    for row in anomalies.to_pylist():
        if row["detector"] == "robust_z" and row["klass"] in _SCORED_KLASS and row["score"] is not None:
            score = float(row["score"])
            if np.isfinite(score):
                out[row["component"]] = max(out.get(row["component"], score), score)
    return out


def peer_contrast(
    change: Change,
    onset_ns: int | None,
    pods: Replicas,
    scores: Mapping[str, float],
    min_replicas: int,
    offset_ns: int = 0,
) -> float | None:
    """`mean a(changed) − median a(peers)`, or None without a cohort. Peers are replicas seen
    before the change and after the onset that are not in the changed set; a replica without an
    anomaly row scores 0 (04 §6). Replica sightings are in source time: `offset_ns` (the metrics
    offset) moves them to the reference clock of the change and the onset."""
    if change.service is None or onset_ns is None:
        return None
    seen = {
        k: (first + offset_ns, last + offset_ns)
        for k, (first, last) in pods.seen.get(change.service, {}).items()
    }
    if len(seen) < min_replicas:
        return None
    if change.scope == "component":
        changed = [change.entity] if change.entity in seen else []
    elif change.kind in ROLLOUT_KINDS:
        changed = sorted(k for k, (first, _) in seen.items() if first >= change.t_ns)
    else:
        changed = []
    peers = sorted(
        k for k, (first, last) in seen.items() if k not in changed and first < change.t_ns and last > onset_ns
    )
    if not changed or not peers:
        return None
    value: Any = np.mean([scores.get(k, 0.0) for k in changed]) - np.median(
        [scores.get(k, 0.0) for k in peers]
    )
    return float(value)
