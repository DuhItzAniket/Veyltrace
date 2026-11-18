"""The change baseline `naive-change` (04 §4): blame the service with the latest change before t_alert.

RCAEval-C only: it reads the run's `telemetry.events` (overlay merged, 01 §3.10), `alert.json`
and `case_manifest.services`; every events row is a change (a priori: RCAEval-C writes only those).
An entity counts for its service by RCAEval's coarse transform (`carts-db` -> `carts`, 04 §7); one
that maps to no service of the case (cluster scope) is not ranked. Ranks: the services with a
change strictly before t_alert, latest first, ties A→Z (a priori); a case without one is an
unranked miss (04 §7).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final, cast

import pyarrow as pa

from veyltrace_bench.metrics import coarse_service
from veyltrace_contracts.models import Alert, CaseManifest
from veyltrace_core import io

METHOD: Final = "naive-change"  # the 04 §4 method id


def rank(events: pa.Table, t_alert_ns: int, services: Iterable[str]) -> tuple[str, ...]:
    """Services with a change before `t_alert_ns`, latest change first, ties A→Z."""
    known = set(services)
    latest: dict[str, int] = {}
    times = cast("list[int]", events.column("t_ns").to_pylist())  # t_ns is non-null (03 §2.5)
    entities = cast("list[str]", events.column("entity").to_pylist())
    for t, entity in zip(times, entities, strict=True):
        service = coarse_service(entity)
        if t < t_alert_ns and service in known:
            latest[service] = max(latest.get(service, t), t)
    return tuple(sorted(latest, key=lambda s: (-latest[s], s)))


def run(run_dir: Path) -> tuple[str, ...]:
    """naive-change's ranks for the case in `run_dir` (a run through core's alert step)."""
    case = io.read_model("case_manifest", run_dir, CaseManifest)
    alert = io.read_model("alert", run_dir, Alert)
    return rank(io.read_table("telemetry.events", run_dir), alert.t_alert_ns, case.services)
