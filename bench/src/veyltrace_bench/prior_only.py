"""The prior-only floor (04 §4, §10 rule 3): rank a case's services by how often each is the root in
the calibration fold, reading no telemetry.

RCAEval injects into five services per system, so a ranker that knows only that prior is a floor
every accuracy table must show (04 §2). bench, not an engine, computes it, because it reads answer
keys (AGENTS.md Never 5). A case is ranked with the counts of the fold that fits it under the
experiment's crossfit2 split (04 §5.4 item 3), so its own cluster (system, root service, fault)
never counts. Only fault cases of the same dataset part count: each part is one system, with its
own service names.

Ranks: every service in the case's `case_manifest.services` once, most roots first, ties A→Z (a
priori, as SimpleRCA). That is the same universe as Chance@k's n_i (04 §7). The run stops after
Infralume, which gives the services. No alert and no telemetry signal is read, so one result serves
the oracle and the detected tables (04 §10.3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from veyltrace_bench import splits
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.errors import ConfigError

METHOD: Final = "prior-only"  # the 04 §4 method id
SCHEME: Final = "crossfit2"  # the only split with a calibration fold for every case (04 §5.4 item 3)


def check_split(scheme: str) -> None:
    """prior-only needs the cross-fit folds of 04 §5.4. Without them it would count its own case."""
    if scheme != SCHEME:
        raise ConfigError(f"methods {METHOD}: needs split.scheme {SCHEME} (04 §5.4), got {scheme}")


def root_counts(case_id: str, plan: splits.FoldPlan, keys: Mapping[str, AnswerKeyRow]) -> dict[str, int]:
    """Root-service counts over the fault cases in `keys` (one dataset part) that fit `case_id`'s fold."""
    fitting = plan.fits[plan.applied[case_id]]
    counts: dict[str, int] = {}
    for other in sorted(fitting & keys.keys()):
        key = keys[other]
        if key.is_no_fault or key.root_service is None:
            continue
        counts[key.root_service] = counts.get(key.root_service, 0) + 1
    return counts


def rank(services: Iterable[str], counts: Mapping[str, int]) -> tuple[str, ...]:
    """Every service once, most roots in the calibration fold first, ties A→Z."""
    return tuple(sorted(set(services), key=lambda s: (-counts.get(s, 0), s)))
