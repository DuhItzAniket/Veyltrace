"""The shared entry-service rule (05-causalith §3.3): which services receive external traffic.

Why one module: three callers must agree on the entry set. Anomara's `detect_alert` (core's alert
step, from parent→child spans), Anomara's `run()` and Causalith (both from `signal_cube.edges`)
all call `entry_services`; under the detected protocol the last two copy
`alert.detector.entry_services` instead (`run_entry_services`), so the entry set the alert was
decided on is the one every engine uses. A cross-engine test asserts
`onsets.entry_services == sorted(node where is_entry)`.

Pure functions: no files, clock or RNG (AGENTS Never 3 of this package). Anomara imports this
module, so it must never import `veyltrace_anomara` (circular).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import pyarrow as pa

from veyltrace_contracts.models import Alert
from veyltrace_core.errors import ConfigError

__all__ = [
    "CONFIG_KEY",
    "EntryConfig",
    "call_pairs_from_edges",
    "entry_config",
    "entry_services",
    "run_entry_services",
]

#: The config subsection of `causalith` that holds the rule's keys (05 §4).
CONFIG_KEY = "entry"

CallPair = tuple[str, str]


@dataclass(frozen=True)
class EntryConfig:
    """The `causalith.entry` keys: per-system entry hints and the excluded traffic sources."""

    hints: Mapping[str, tuple[str, ...]]
    exclude: tuple[str, ...]


def _names(value: object, where: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"{where} must be a list of service names, got {value!r}"
        raise ConfigError(msg)
    items = cast("Sequence[object]", value)
    if not all(isinstance(v, str) and v for v in items):
        msg = f"{where} must be a list of non-empty strings, got {value!r}"
        raise ConfigError(msg)
    return tuple(sorted({cast("str", v) for v in items}))


def entry_config(section: Mapping[str, Any]) -> EntryConfig:
    """Parse the `entry` subsection of the causalith config section (ConfigError if malformed).

    `section` is the whole causalith section (`ctx.config` in Causalith,
    `ctx.config.section("causalith")` in Anomara), so both engines read the same keys.
    """
    raw: object = section.get(CONFIG_KEY)
    if not isinstance(raw, Mapping):
        msg = f"causalith.{CONFIG_KEY} must be a mapping with hints and exclude"
        raise ConfigError(msg)
    entry = cast("Mapping[str, object]", raw)
    hints_raw = entry.get("hints")
    if not isinstance(hints_raw, Mapping):
        msg = "causalith.entry.hints must map a system to a list of services"
        raise ConfigError(msg)
    items = cast("Mapping[object, object]", hints_raw).items()
    hints = {
        str(system): _names(names, f"causalith.entry.hints.{system}")
        for system, names in sorted(items, key=lambda kv: str(kv[0]))
    }
    return EntryConfig(hints=hints, exclude=_names(entry.get("exclude"), "causalith.entry.exclude"))


def entry_services(
    call_pairs: Iterable[CallPair], services: Iterable[str], system: str, cfg: EntryConfig
) -> list[str]:
    """Entry services, sorted A→Z (05 §3.3).

    1. The system hint, intersected with `services`, if that is non-empty.
    2. Else, ignoring excluded services (load generators): the services that appear as a caller
       and never as the callee of a non-excluded service. A self pair is not a cross-service call.
    3. Else an empty list: without traces and a hint there is no defensible entry.
    """
    known = set(services)
    hinted = sorted(set(cfg.hints.get(system, ())) & known)
    if hinted:
        return hinted
    excluded = set(cfg.exclude)
    pairs = {(a, b) for a, b in call_pairs if a != b and a not in excluded}
    callers = {a for a, _ in pairs}
    callees = {b for _, b in pairs}
    return sorted(callers - callees)


def call_pairs_from_edges(edges: pa.Table) -> list[CallPair]:
    """Sorted unique (caller, callee) pairs of `signal_cube.edges`, both windows (05 §3.3)."""
    if edges.num_rows == 0:
        return []
    callers = cast("list[str]", edges.column("caller").to_pylist())
    callees = cast("list[str]", edges.column("callee").to_pylist())
    return sorted(set(zip(callers, callees, strict=True)))


def run_entry_services(
    alert: Alert, edges: pa.Table, services: Iterable[str], system: str, cfg: EntryConfig
) -> list[str]:
    """The entry set of a run, for Anomara's `run()` and Causalith (05 §3.3).

    `alert.detector.entry_services` verbatim when the detected protocol set it (the alert was
    decided on that set), else the rule on `signal_cube.edges`.
    """
    if alert.detector is not None:
        return sorted(alert.detector.entry_services)
    return entry_services(call_pairs_from_edges(edges), services, system, cfg)
