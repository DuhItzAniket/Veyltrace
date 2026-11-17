"""The RCAEval-C generator: one true change on the root with probability π, Poisson decoys elsewhere.

RCAEval has injection times but no change events, so the change channel cannot be tested on it.
This module writes a synthetic change log per case (04 §5.2; 04-causync §3.7; technique card N5):
a true change on the injected service shortly before the injection, and decoy changes on other
services. Every row has the same shape, so nothing but time, entity and kind separates them;
which row is true goes only into the answer key (`decoy_changes_json`, 03 §13.1).

All randomness comes from `rng(case_id, "rcaeval-c")`. The true-change draws are made for every
case, emitted or not, so a case's decoys are the same at every π, and the cases that get a true
change at a lower π are a subset of those at a higher one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import pyarrow as pa

from veyltrace_core import io
from veyltrace_core.canonical import canonical_json_str
from veyltrace_core.config import data_root as default_data_root
from veyltrace_core.ids import is_case_id
from veyltrace_core.rng import rng

RNG_PURPOSE: Final = "rcaeval-c"  # 04 §5.2: seed rng(case_id, "rcaeval-c")
#: A true change lies at t_inject − U(0, TRUE_LEAD_MAX_S) (04 §5.2, a priori; card N5).
TRUE_LEAD_MAX_S: Final = 120
#: Kinds a synthetic change is drawn from, uniformly (04 §5.2, a priori).
KINDS: Final = ("deploy", "config", "flag")
#: Decoy window relative to t_inject when `protocol.decoys` gives none (04 §5.2: −30 min, +5 min).
DEFAULT_WINDOW_S: Final = (-1800, 300)
SOURCE_SYSTEM: Final = "synthetic"  # 01 §3.10: every overlay row
#: The same for every row and free of any "true"/"decoy" token (04-causync §3.7 step 4).
DETAIL_JSON: Final = "{}"
EVENTS: Final = "telemetry.events"
OVERLAY_DIR: Final = "overlays"  # 01 §3.10: ${VEYLTRACE_DATA}/overlays/<experiment_id>/<case_id>/
OVERLAY_FILE: Final = "events.parquet"
NS_PER_S: Final = 1_000_000_000
S_PER_H: Final = 3600
_EXPERIMENT_ID: Final = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # 04 §9; also blocks "../"
_SPEC_KEYS: Final = frozenset({"pi", "rate_per_h", "window_s"})


@dataclass(frozen=True)
class DecoySpec:
    """One cell of the RCAEval-C grid: an experiment's `protocol.decoys` (04 §5.2, §9)."""

    pi: float
    rate_per_h: float
    window_s: tuple[int, int] = DEFAULT_WINDOW_S

    def __post_init__(self) -> None:
        lo, hi = self.window_s
        if not 0.0 <= self.pi <= 1.0:
            raise ValueError(f"decoys.pi must be in [0, 1], got {self.pi}")
        if self.rate_per_h < 0:
            raise ValueError(f"decoys.rate_per_h must be >= 0, got {self.rate_per_h}")
        if lo >= hi:
            raise ValueError(f"decoys.window_s must be [lo, hi] with lo < hi, got {[lo, hi]}")

    @classmethod
    def from_protocol(cls, decoys: Mapping[str, object]) -> DecoySpec:
        """Build the spec from `protocol.decoys`; `pi` and `rate_per_h` are required."""
        unknown = sorted(set(decoys) - _SPEC_KEYS)
        missing = sorted({"pi", "rate_per_h"} - set(decoys))
        if unknown or missing:
            raise ValueError(f"protocol.decoys: unknown keys {unknown}, missing keys {missing}")
        window = cast("Sequence[int]", decoys.get("window_s", DEFAULT_WINDOW_S))
        if len(window) != 2 or any(isinstance(w, bool) or not isinstance(w, int) for w in window):
            raise ValueError(f"decoys.window_s must be two whole seconds, got {window!r}")
        pi, rate = decoys["pi"], decoys["rate_per_h"]
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in (pi, rate)):
            raise ValueError(f"decoys.pi and decoys.rate_per_h must be numbers, got {pi!r}, {rate!r}")
        return cls(float(cast("float", pi)), float(cast("float", rate)), (window[0], window[1]))


@dataclass(frozen=True, order=True)
class SyntheticChange:
    """One synthetic change. `is_true` is ground truth: it goes to the answer key, never to an event."""

    t_ns: int
    entity: str
    kind: str
    is_true: bool


def generate(
    case_id: str,
    root_service: str,
    t_inject_ns: int,
    services: Sequence[str],
    spec: DecoySpec,
) -> list[SyntheticChange]:
    """The synthetic changes of one fault case, sorted by (t_ns, entity, kind).

    With probability `spec.pi` one true change on `root_service` at `t_inject − U(0, 120 s)`;
    Poisson(`rate_per_h` × window hours) decoys at uniform times in the window, each on a uniform
    non-root service of `services` (the case manifest's). Times are whole nanoseconds drawn as
    integers, so no float rounding enters them.
    """
    gen = rng(case_id, RNG_PURPOSE)
    # Drawn for every case, emitted or not, so decoys do not depend on π (module docstring).
    u = float(gen.random())
    lead_ns = int(gen.integers(0, TRUE_LEAD_MAX_S * NS_PER_S, endpoint=True))
    true_kind = KINDS[int(gen.integers(len(KINDS)))]
    out: list[SyntheticChange] = []
    if u < spec.pi:
        out.append(SyntheticChange(t_inject_ns - lead_ns, root_service, true_kind, True))

    others = sorted(set(services) - {root_service})
    lo, hi = spec.window_s
    n = int(gen.poisson(spec.rate_per_h * (hi - lo) / S_PER_H)) if others and spec.rate_per_h > 0 else 0
    for _ in range(n):
        t_ns = t_inject_ns + int(gen.integers(lo * NS_PER_S, hi * NS_PER_S, endpoint=True))
        entity = others[int(gen.integers(len(others)))]
        out.append(SyntheticChange(t_ns, entity, KINDS[int(gen.integers(len(KINDS)))], False))
    return sorted(set(out))  # two decoys on one (t_ns, entity, kind) are one event


def events_table(changes: Sequence[SyntheticChange]) -> pa.Table:
    """`telemetry.events` rows (03 §2.5) for `changes`: one shape for true changes and decoys."""
    n = len(changes)
    columns = {
        "t_ns": [c.t_ns for c in changes],
        "entity": [c.entity for c in changes],
        "kind": [c.kind for c in changes],
        "source_system": [SOURCE_SYSTEM] * n,
        "detail_json": [DETAIL_JSON] * n,
        "actor": [None] * n,
    }
    return pa.table(columns, schema=io.arrow_schema(EVENTS))


def decoy_changes_json(changes: Sequence[SyntheticChange]) -> str:
    """The answer key's `decoy_changes_json` (03 §13.1): canonical `[{t_ns, entity, kind, is_true}]`."""
    return canonical_json_str(
        [{"t_ns": c.t_ns, "entity": c.entity, "kind": c.kind, "is_true": c.is_true} for c in sorted(changes)]
    )


def overlay_path(experiment_id: str, case_id: str, data_root: Path | None = None) -> Path:
    """`${VEYLTRACE_DATA}/overlays/<experiment_id>/<case_id>/events.parquet` (01 §3.10): under the
    data root, never under bench/ or lab/, because Infralume may not read there."""
    if _EXPERIMENT_ID.fullmatch(experiment_id) is None:
        raise ValueError(f"not an experiment id: {experiment_id!r}")
    if not is_case_id(case_id):
        raise ValueError(f"not a 12-hex case_id: {case_id!r}")
    root = default_data_root() if data_root is None else data_root
    return root / OVERLAY_DIR / experiment_id / case_id / OVERLAY_FILE


def write_overlay(
    experiment_id: str,
    case_id: str,
    changes: Sequence[SyntheticChange],
    data_root: Path | None = None,
) -> tuple[Path, str]:
    """Write the case's overlay through core io (validated, sorted); return its path and sha256.

    A case without changes still gets a zero-row file, so every case of a cell has an overlay.
    """
    path = overlay_path(experiment_id, case_id, data_root)
    return path, io.write_path(EVENTS, events_table(changes), path)
