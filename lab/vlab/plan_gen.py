"""Collection grid for overnight campaigns (05 §6 "Targets", §8.3; X-11).

The grid is every (target, fault) pair repeated ``reps`` times plus about 10% no-fault controls,
shuffled once from the seed and dealt round-robin to laptops, then cut into nights. The same seed
gives the same plan on every laptop, so the three laptops never run the same case twice.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

from vlab.faults import CATALOG, DATASTORES, NO_FAULT

#: Default targets: five OB services on the main request paths (05 §6 "5 target services", a priori).
DEFAULT_SERVICES = ("cartservice", "checkoutservice", "currencyservice", "frontend", "productcatalogservice")
REPS = 3  # 05 §6: 3 repetitions
#: Severity per repetition (a priori). F02 and F07 always use L2: at L1 neither moved a user-facing
#: SLI on the 2026-11-09 live run, so 05 §8.2 rejected them (ADR 20261110-cl-lab-validation).
SEVERITY_BY_REP = ("L1", "L2", "L1")
ALWAYS_L2 = frozenset({"F02", "F07"})
#: Load profile per repetition: the third runs at 30 users (05 §3.2 profiles, a priori).
USERS_BY_REP = (10, 10, 30)
NO_FAULT_FRAC = 0.10  # 05 §6: ≈ 10% no-fault cases
#: ≈ 24 cases per 10-hour night at ≈ 25 min each (05 §8.3).
PER_NIGHT = 24


def grid(seed: int, services: Sequence[str] = DEFAULT_SERVICES, reps: int = REPS) -> list[dict[str, Any]]:
    """Every entry of the campaign, shuffled from ``seed``."""
    entries: list[dict[str, Any]] = []
    for fault in sorted(CATALOG.values(), key=lambda f: f.fault_id):
        targets = DATASTORES if fault.targets == DATASTORES else tuple(services)
        for target in targets:
            for rep in range(reps):
                severity = (
                    "L2" if fault.fault_id in ALWAYS_L2 else SEVERITY_BY_REP[rep % len(SEVERITY_BY_REP)]
                )
                entries.append(
                    {
                        "fault": fault.fault_id,
                        "target": target,
                        "severity": severity,
                        "users": USERS_BY_REP[rep % len(USERS_BY_REP)],
                    }
                )
    controls = math.ceil(len(entries) * NO_FAULT_FRAC)
    entries += [{"fault": NO_FAULT, "users": USERS_BY_REP[i % len(USERS_BY_REP)]} for i in range(controls)]
    random.Random(seed).shuffle(entries)  # lab code: seeded randomness is fine and reproducible
    return entries


def share(entries: Sequence[dict[str, Any]], *, laptops: int, laptop: int) -> list[dict[str, Any]]:
    """Laptop ``laptop`` (1-based) of ``laptops``: every laptops-th entry, so shares differ by ≤ 1."""
    if not 1 <= laptop <= laptops:
        raise ValueError(f"laptop must be in 1..{laptops}")
    return list(entries[laptop - 1 :: laptops])


def night(
    entries: Sequence[dict[str, Any]], *, night: int, per_night: int = PER_NIGHT
) -> list[dict[str, Any]]:
    """Night ``night`` (1-based) of a laptop's share."""
    if night < 1:
        raise ValueError("night is 1-based")
    return list(entries[(night - 1) * per_night : night * per_night])


def plan_document(
    entries: Sequence[dict[str, Any]], *, seed: int, dataset: str = "veyllab-ob"
) -> dict[str, Any]:
    return {"profile": "ob", "dataset": dataset, "seed": seed, "entries": list(entries)}
