"""Dataset adapters and the canonical telemetry handed between ingest and analysis (D-1, D-2).

An adapter turns one dataset's raw case into canonical tables (`CanonicalCase`); Infralume owns
materialisation (cache, source drops, overlays, hint blanking, the writes) and pipeline step 0
always runs Infralume, for synth too (01 §1, §10 O-00). The Protocol and the dataclasses live in
core so core's synth adapter implements them without depending on Infralume. `TelemetryTables`
(the four telemetry tables, never None; defined in io and re-exported here, one class) and
`AlertDetection` (what Anomara's alert detector returns to core's alert step) are shared value
types for the same reason.

Engine-facing module: no importlib.metadata at import time. `adapter_for` loads the
`veyltrace.adapters` entry points lazily, when Infralume or the pipeline actually resolves a case.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, get_args, runtime_checkable

from veyltrace_contracts.models import CaseManifest, HintSource, System
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import is_sha256
from veyltrace_core.io import TELEMETRY, TelemetryTables

if TYPE_CHECKING:
    from veyltrace_core.config import EngineConfig

__all__ = [
    "ADAPTERS_GROUP",
    "SOURCE_NAMES",
    "TELEMETRY_CONTRACTS",
    "Adapter",
    "AlertDetection",
    "CanonicalCase",
    "CaseRef",
    "DetectAlert",
    "TelemetryTables",
    "adapter_for",
    "find_adapter",
]

ADAPTERS_GROUP = "veyltrace.adapters"

#: TelemetryTables attribute -> contract name (03 §2.2–2.5); the same mapping as io.TELEMETRY.
TELEMETRY_CONTRACTS: Mapping[str, str] = TELEMETRY

#: case_manifest.sources keys (03 §2.1): the source vocabulary, with `traces`, not `spans`.
SOURCE_NAMES: tuple[str, ...] = ("metrics", "logs", "traces", "events")

_SYSTEMS: tuple[str, ...] = get_args(System)
_HINT_SOURCES: tuple[str, ...] = get_args(HintSource)


@dataclass(frozen=True)
class CaseRef:
    """A resolved case: dataset, opaque case id, the adapter's canonical key and where the raw
    data lives (None for synth, which is generated)."""

    dataset: str
    case_id: str
    canonical_key: str
    location: Path | None


@dataclass(frozen=True)
class CanonicalCase:
    """What an adapter's convert() returns: canonical tables plus the descriptive facts Infralume
    turns into case_manifest (03 §2.1). The hint is reported before protocol blanking; Infralume
    blanks it under the detected protocol (01 §3.3)."""

    system: System
    tables: TelemetryTables
    sources_present: Mapping[str, bool]
    inputs: tuple[tuple[str, str, int], ...]
    adapter_name: str
    adapter_version: str
    scrub: tuple[str, int, int]
    t_alert_hint_ns: int | None
    hint_source: HintSource

    def __post_init__(self) -> None:
        if self.system not in _SYSTEMS:
            msg = f"system must be one of {_SYSTEMS}, got {self.system!r}"
            raise ValueError(msg)
        if sorted(self.sources_present) != sorted(SOURCE_NAMES):
            msg = f"sources_present must have exactly the keys {SOURCE_NAMES}"
            raise ValueError(msg)
        names = [name for name, _, _ in self.inputs]
        if names != sorted(names) or len(set(names)) != len(names):
            msg = "inputs must be sorted by name and unique"
            raise ValueError(msg)
        for name, digest, size in self.inputs:
            if not is_sha256(digest) or isinstance(size, bool) or size < 0:
                msg = f"input {name!r} needs a 64-hex sha256 and a byte count >= 0"
                raise ValueError(msg)
        if self.hint_source not in _HINT_SOURCES:
            msg = f"hint_source must be one of {_HINT_SOURCES}, got {self.hint_source!r}"
            raise ValueError(msg)
        if (self.t_alert_hint_ns is None) != (self.hint_source == "none"):
            msg = "hint_source is 'none' if and only if t_alert_hint_ns is null (03 §2.1)"
            raise ValueError(msg)


@runtime_checkable
class Adapter(Protocol):
    """A dataset adapter, registered under the entry-point group `veyltrace.adapters`.

    `datasets` are fnmatchcase patterns (e.g. ("re1-*", "re2-*", "re3-*")); `version` is a
    per-adapter revision string, not the package version (D-21). `cacheable` is False for
    generated data (synth), whose Infralume cache would otherwise serve stale telemetry after a
    generator edit (critic gap, accepted).
    """

    name: str
    version: str
    datasets: tuple[str, ...]
    cacheable: bool

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        """Resolve a case id (or, for synth, a synth-0N name) to a CaseRef."""
        ...

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        """All case ids of `dataset`, sorted."""
        ...

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        """Read the raw case into canonical tables."""
        ...

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        """(t_alert_hint_ns, hint_source) before protocol blanking."""
        ...


def find_adapter(dataset: str) -> Adapter | None:
    """The one registered adapter whose `datasets` patterns match `dataset` (case-sensitive), or
    None when none matches.

    Several matches are a ConfigError naming them: which adapter reads a dataset must never depend
    on entry-point order. The None case exists for the R-02 bootstrap stub Infralume, which writes
    a placeholder case while no adapter for the dataset is installed (synth lands in R-03).
    """
    from veyltrace_core import plugins  # lazy: plugins imports importlib.metadata

    matches: list[tuple[str, Adapter]] = []
    for name, obj in plugins.load(ADAPTERS_GROUP).items():
        adapter = obj() if isinstance(obj, type) else obj
        if not isinstance(adapter, Adapter):
            msg = f"{ADAPTERS_GROUP}:{name} is not an Adapter (needs name, version, datasets, ...)"
            raise ConfigError(msg)
        if any(fnmatchcase(dataset, pattern) for pattern in adapter.datasets):
            matches.append((name, adapter))
    if len(matches) > 1:
        found = ", ".join(name for name, _ in matches)
        msg = f"dataset {dataset!r} needs exactly one adapter in {ADAPTERS_GROUP}; matched: {found}"
        raise ConfigError(msg)
    return matches[0][1] if matches else None


def adapter_for(dataset: str) -> Adapter:
    """The one registered adapter whose `datasets` patterns match `dataset` (case-sensitive).

    Raises ConfigError if none or several match, naming them.
    """
    adapter = find_adapter(dataset)
    if adapter is None:
        msg = f"dataset {dataset!r} needs exactly one adapter in {ADAPTERS_GROUP}; matched: none"
        raise ConfigError(msg)
    return adapter


@dataclass(frozen=True)
class AlertDetection:
    """A sustained SLO breach found by the alert detector (Anomara, D-2): when, on which entry
    services, on which signal and against which threshold. Core's alert step turns it into
    alert.t_alert_ns and alert.detector."""

    t_alert_ns: int
    entry_services: tuple[str, ...]
    signal: str
    threshold: float

    def __post_init__(self) -> None:
        if isinstance(self.t_alert_ns, bool) or not isinstance(self.t_alert_ns, int):  # pyright: ignore[reportUnnecessaryIsInstance]  (plugin output)
            msg = f"t_alert_ns must be an int, got {self.t_alert_ns!r}"
            raise TypeError(msg)
        if not self.signal:
            msg = "signal must be a non-empty string"
            raise ValueError(msg)
        threshold = float(self.threshold)
        if not math.isfinite(threshold):
            msg = f"threshold must be finite, got {self.threshold!r}"
            raise ValueError(msg)
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "entry_services", tuple(sorted(set(self.entry_services))))


class DetectAlert(Protocol):
    """The `veyltrace.alert_detectors:default` callable (D-2). It reads telemetry and the
    descriptive manifest fields (the hint is always null here) and the run's Anomara config."""

    def __call__(
        self, telemetry: TelemetryTables, manifest: CaseManifest, config: EngineConfig, /
    ) -> AlertDetection | None:
        """Return the first sustained breach, or None if there is none."""
        ...
