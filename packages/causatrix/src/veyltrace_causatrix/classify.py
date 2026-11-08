"""classify(): the mode and fault-class rule table R1–R6 and the indicator (07 §3.5–§3.6).

It answers "if this service were the root, which fault would it be". Rules are evaluated in order
and the first match wins; none has been measured on RCAEval yet, so their accuracy is an output of
the evaluation (fault-type accuracy, 04 §7), not an assumption. Pure: Causentra calls it for
proposal-origin candidates (09 §3.9) and for the indicators of `ranks_rcaeval` (09 §3.12).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from veyltrace_causatrix.config import FAMILIES, CausatrixConfig
from veyltrace_causatrix.views import CHANGE, EXTERNAL, ROBUST_Z, Atom, EvidenceView, GraphView, component_of

__all__ = ["Classification", "classify"]

#: R2: resource families and their fault class (net → socket, 03 §1).
RESOURCE: Final = {"cpu": "cpu", "mem": "mem", "disk": "disk", "net": "socket"}
#: R3: internal families that point at the service's own code.
CODE_FAMILIES: Final = frozenset({"logs", "self_time", "other"})
#: R4: graph node kinds of a dependency.
DEPENDENCY_KINDS: Final = frozenset({"db", "cache", "queue", "external"})
#: R1: change event kinds that make the fault class `config`.
CONFIG_EVENTS: Final = frozenset({"config", "flag"})
LOG_NEW_TEMPLATE: Final = "log_new_template"
EDGE_GAP: Final = "edge_gap"
UNKNOWN: Final = "unknown"


@dataclass(frozen=True)
class Classification:
    """mode and fault_class (03 §1), the RCAEval indicator, and the candidate component."""

    mode: str
    fault_class: str
    indicator: str
    component: str | None


def _max(atoms: Iterable[Atom]) -> float | None:
    values = [a.value for a in atoms]
    return max(values) if values else None


def _family(atom: Atom | None) -> str:
    family = atom.args.get("family") if atom is not None else None
    return family if isinstance(family, str) and family in FAMILIES else "other"


def _rules_2_to_5(service: str, ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> tuple[str, str]:
    """(mode, fault_class) of the first matching rule among R2–R5, else R6."""
    f, k = ev.of(service), cfg.k_anom
    top_family = _family(f.top_internal)
    errors = [a for a in ev.atoms_of(service, EXTERNAL) if a.args.get("family") == "errors"]
    if f.internal >= k and top_family in RESOURCE:  # R2
        return "resource", RESOURCE[top_family]
    new_errors = _max(
        a for a in ev.atoms_of(service, LOG_NEW_TEMPLATE) if a.args.get("error_level_only") is True
    )
    if (f.internal >= k and top_family in CODE_FAMILIES) or (new_errors or 0.0) >= 1:  # R3
        if (new_errors or 0.0) >= 1:
            return "code", "exception"
        error_z = _max(a for a in errors if a.args.get("detector") == ROBUST_Z) or 0.0
        return "code", "error" if error_z >= k else UNKNOWN
    if graph.kinds.get(service) in DEPENDENCY_KINDS and (f.silent == 1.0 or f.external >= k):  # R4
        return "dependency", "dependency"
    gaps = [a for a in ev.atoms_of(service, EDGE_GAP) if a.args.get("direction") == "in"]
    p50 = _max(a for a in gaps if a.args.get("quantile") == "p50")
    p99 = _max(a for a in gaps if a.args.get("quantile") == "p99")
    if f.internal < k and (f.external >= k or (p50 is not None and p50 >= cfg.edge_gap_min_ms)):  # R5
        tail = p50 is not None and p99 is not None and p99 > 0 and p50 / p99 <= cfg.tail_ratio
        loss = (_max(errors) or 0.0) >= k or tail
        return "network", "loss" if loss else "delay"
    return UNKNOWN, UNKNOWN  # R6


def classify(service: str, ev: EvidenceView, graph: GraphView, cfg: CausatrixConfig) -> Classification:
    """Rules R1–R6 (07 §3.5), the indicator (§3.6) and the component (§2.2) of `service`."""
    f, k = ev.of(service), cfg.k_anom
    mode, fault_class = _rules_2_to_5(service, ev, graph, cfg)
    changes = ev.atoms_of(service, CHANGE)
    anomalous = max(f.internal, f.external) >= k or f.silent == 1.0
    if changes and f.change >= cfg.change_min_proximity and anomalous:  # R1
        strongest = min(changes, key=lambda a: (-a.value, a.atom_id))
        fault_class = "config" if strongest.args.get("event_kind") in CONFIG_EVENTS else fault_class
        mode = "change"
    if mode == "network":
        family = "latency"  # RCAEval scores DELAY and LOSS against latency (07 §3.6 step 1)
    elif f.internal >= k:
        family = _family(f.top_internal)
    elif f.external > 0:
        family = _family(f.top_external)
    else:
        family = "other"
    return Classification(mode, fault_class, cfg.indicator(family), component_of(service, ev))
