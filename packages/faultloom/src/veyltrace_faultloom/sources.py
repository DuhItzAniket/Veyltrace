"""`atom_sources(atom)`: the telemetry sources behind an atom (06 §3.3), for Causentra's trial T9.

Why: T9 re-ranks with each source left out, so it must know which sources every atom rests on.
There is no sources column in `evidence` (03 §7): the sources are the `source` part of every series
reference plus the fixed tag of the kind (06 §3.4 "Sources" column). A kind with neither
(onset_precedence, propagation) rests on no single source.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from veyltrace_core.canonical import JSONLike
from veyltrace_core.errors import ContractValidationError

__all__ = ["KIND_SOURCES", "atom_sources"]

#: Fixed source tag per kind (06 §3.4 "Sources"); kinds marked "from refs" or "—" have none.
KIND_SOURCES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "change_proximity": frozenset({"events"}),
        "spectrum": frozenset({"traces"}),
        "critical_path_share": frozenset({"traces"}),
        "self_time_share": frozenset({"traces"}),
        "edge_gap": frozenset({"traces"}),
        "log_new_template": frozenset({"logs"}),
        "log_error_rate": frozenset({"logs"}),
    }
)
#: series_id = "{service}|{component}|{signal}|{source}" (03 §3.1): three separators.
_SERIES_SEPARATORS: Final = 3


def atom_sources(atom: Mapping[str, JSONLike]) -> frozenset[str]:
    """Sources of every series in `refs` plus the kind's tag; `peer_contrast{source: changes}` is events."""
    refs = atom["refs"]
    if not isinstance(refs, list | tuple):
        raise ContractValidationError("evidence", f"refs must be a list, got {type(refs).__name__}")
    listed = [str(r) for r in refs]
    found = {r.rsplit("|", 1)[1] for r in listed if r.count("|") == _SERIES_SEPARATORS}
    kind = str(atom["kind"])
    if kind == "peer_contrast" and json.loads(str(atom["args_json"])).get("source") == "changes":
        found.add("events")
    return frozenset(found) | KIND_SOURCES.get(kind, frozenset())
