"""Plan files ``lab/plans/<plan>.yaml`` (05 §8.1): profile, dataset, seed and ordered entries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vlab.faults import get_fault

#: Phase lengths in seconds (05 §8.1). A plan may shorten them for smoke runs; the values used are
#: recorded in every capture's orchestrator.json.
DEFAULT_DURATIONS_S = {"warmup": 180, "baseline": 600, "fault": 600, "recovery": 120}
PLAN_KEYS = frozenset({"profile", "dataset", "seed", "durations_s", "entries"})
ENTRY_KEYS = frozenset({"fault", "target", "severity", "decoy"})


@dataclass(frozen=True)
class Entry:
    fault: str
    target: str
    severity: str


@dataclass(frozen=True)
class Plan:
    profile: str
    dataset: str
    seed: int
    durations_s: dict[str, int]
    entries: tuple[Entry, ...]


def parse(data: Any) -> Plan:
    """Validate a loaded plan; raise ValueError naming the first problem."""
    if not isinstance(data, dict):
        raise ValueError("plan must be a mapping")
    if unknown := set(data) - PLAN_KEYS:
        raise ValueError(f"unknown plan keys {sorted(unknown)}")
    if data.get("profile") != "ob":
        raise ValueError("only profile 'ob' is supported (otel arrives with X-06)")
    seed = data.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    durations = dict(DEFAULT_DURATIONS_S)
    override = data.get("durations_s") or {}
    if set(override) - set(durations) or not all(isinstance(v, int) and v > 0 for v in override.values()):
        raise ValueError(f"durations_s keys must be {sorted(durations)} with positive integer seconds")
    durations.update(override)
    entries: list[Entry] = []
    for i, raw in enumerate(data.get("entries") or []):
        if not isinstance(raw, dict) or set(raw) - ENTRY_KEYS:
            raise ValueError(f"entry {i}: keys must be a subset of {sorted(ENTRY_KEYS)}")
        if raw.get("decoy"):
            raise ValueError(f"entry {i}: decoy changes arrive with X-06")
        entry = Entry(str(raw.get("fault")), str(raw.get("target")), str(raw.get("severity", "L1")))
        try:
            get_fault(entry.fault, entry.target, entry.severity)
        except ValueError as exc:
            raise ValueError(f"entry {i}: {exc}") from None
        entries.append(entry)
    if not entries:
        raise ValueError("plan has no entries")
    return Plan("ob", str(data.get("dataset", "veyllab-ob")), seed, durations, tuple(entries))


def load(path: Path) -> Plan:
    with path.open(encoding="utf-8") as fh:
        return parse(yaml.safe_load(fh))
