"""The predicate library (06 §3.5): the only checks Relentra may request, with fixed polarity.

Why: proposals are data and predicates are code. The claim pass runs a requested predicate for every
claim-pass pool candidate, so a model chooses which check runs but can never favour a candidate
(02 §2 P2). Predicates read the same inputs and engine atoms as FaultLoom's own evidence, so a claim
holds only if FaultLoom can recompute it (02 §3.1). Polarity is code and equals 03 §7; weights are
Causentra's config and are never read here. `validate` is pure, so Causentra re-derives rejection
reasons with it (06 §3.6 step 5; R-08f). Not evaluable is `holds = None`, never a healthy False.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from veyltrace_faultloom.atoms import Atom
from veyltrace_faultloom.change import owners
from veyltrace_faultloom.inputs import EvidenceInputs

__all__ = ["LIBRARY", "ArgValue", "ClaimView", "Param", "Predicate", "PredicateResult"]

type ArgValue = float | int | str
type ParamType = Literal["float", "int", "service", "signal"]


@dataclass(frozen=True)
class Param:
    """One argument after the subject (06 §3.5); its range is config `predicates.<name>.<param>`."""

    name: str
    type: ParamType


@dataclass(frozen=True)
class PredicateResult:
    """value (0.0 when not measurable), holds (None = not evaluable), sorted unique refs."""

    value: float
    holds: bool | None
    refs: tuple[str, ...]


@dataclass(frozen=True)
class ClaimView:
    """What predicates read: the input view and the engine atoms of the main pass."""

    inputs: EvidenceInputs
    atoms: tuple[Atom, ...]

    def of(self, candidate: str, kind: str) -> list[Atom]:
        """Engine atoms of one candidate and kind, by atom_id."""
        found = [a for a in self.atoms if a["candidate"] == candidate and a["kind"] == kind]
        return sorted(found, key=lambda a: str(a["atom_id"]))


type Args = Mapping[str, ArgValue]
type Evaluator = Callable[[ClaimView, str, Args], PredicateResult]


@dataclass(frozen=True)
class Predicate:
    """A library predicate: name, params, polarity (+1 supports, -1 refutes the subject being the
    root), and the window and unit of its claim_check atoms (06 §3.5, 03 §7)."""

    name: str
    params: tuple[Param, ...]
    polarity: Literal[1, -1]
    window: Literal["baseline", "incident", "onset"]
    unit: str | None
    evaluator: Evaluator

    def evaluate(self, view: ClaimView, subject: str, args: Args) -> PredicateResult:
        """Evaluate for `subject` with validated, canonical args (floats as float, ints as int); an
        exception is a bug (06 §3.9)."""
        return self.evaluator(view, subject, args)


# --- evaluators (06 §3.5 table) ----------------------------------------------------------------
_NULL: Final = PredicateResult(0.0, None, ())


def _result(value: float, holds: bool | None, refs: list[str] | tuple[str, ...] = ()) -> PredicateResult:
    return PredicateResult(float(value), holds, tuple(sorted(set(refs))))


def _value(atom: Atom) -> float:
    value = atom["value"]
    return float(value) if isinstance(value, int | float) else math.nan


def _refs(atom: Atom) -> list[str]:
    refs = atom["refs"]
    return [str(r) for r in refs] if isinstance(refs, list | tuple) else []


def _zscore_above(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    signal = args["signal"]
    rows = [
        r
        for r in view.inputs.anomalies
        if r.service == subject and r.detector == "robust_z" and r.series_id.split("|")[2] == signal
    ]
    if not rows:
        return _NULL
    top = max(r.score for r in rows)
    return _result(top, top >= float(args["k"]), [r.series_id for r in rows if r.score == top])


def _onset_before(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    of = view.inputs.onset_of
    a, b = of.get(subject), of.get(str(args["other_service"]))
    t_a, t_b = (None if a is None else a.onset_ns), (None if b is None else b.onset_ns)
    if a is None or b is None or t_a is None or t_b is None or a.service == b.service:
        return _NULL
    return _result((t_b - t_a) / 1_000_000, t_a <= t_b - view.inputs.tol_ns, (a.ref, b.ref))


def _edge_anomalous(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    callee = str(args["callee"])
    edge = next((e for e in view.inputs.edges if (e.src, e.dst) == (subject, callee)), None)
    if subject == callee or (edge is not None and edge.anomalous is None):
        return _NULL
    if edge is None:
        return _result(0.0, False)
    return _result(1.0 if edge.anomalous else 0.0, edge.anomalous, (edge.ref,))


def _atom_at_least(kind: str, param: str, window: str | None = None) -> Evaluator:
    """value = the subject's max `kind` atom (in `window`); holds = value >= args[param]."""

    def evaluate(view: ClaimView, subject: str, args: Args) -> PredicateResult:
        found = [a for a in view.of(subject, kind) if window is None or a["window"] == window]
        if not found:
            return _NULL
        top = max(_value(a) for a in found)
        refs = [r for a in found if _value(a) == top for r in _refs(a)]
        return _result(top, top >= float(args[param]), refs)

    return evaluate


def _change_before_onset(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    if not view.inputs.sources.events:
        return _NULL
    comps = {subject: view.inputs.components.get(subject, frozenset())}
    before = [
        (abs(c.delta_to_onset_ms), c.change_id)
        for c in view.inputs.changes
        if owners(c, comps) and c.delta_to_onset_ms is not None and c.delta_to_onset_ms <= 0
    ]
    if not before:
        return _result(0.0, False)
    best = min(d for d, _ in before)
    return _result(best, best <= float(args["max_ms"]), [cid for d, cid in before if d == best])


def _template_new(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    mine = [t for t in view.inputs.templates if t.service == subject]
    if not view.inputs.sources.logs or not mine:
        return _NULL
    new = [
        t.template_id for t in mine if t.count_baseline == 0 and t.count_incident >= int(args["min_count"])
    ]
    return _result(len(new), len(new) >= 1, new)


def _error_rate_above(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    into = [e for e in view.inputs.edge_stats if e.callee == subject and e.window == "incident"]
    if not view.inputs.sources.traces or not into:
        return _NULL
    rate = math.fsum(e.calls * e.error_rate for e in into) / math.fsum(e.calls for e in into)
    return _result(rate, rate >= float(args["x"]), [e.ref for e in into])


def _silent(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    found = view.of(subject, "silence")
    return _NULL if not found else _result(_value(found[0]), _value(found[0]) == 1.0, _refs(found[0]))


_CP_SHARE: Final = _atom_at_least("critical_path_share", "min_share", "incident")


def _on_critical_path(view: ClaimView, subject: str, args: Args) -> PredicateResult:
    return _CP_SHARE(view, subject, args) if view.inputs.sources.traces else _NULL


def _one(name: str, kind: ParamType) -> tuple[Param, ...]:
    return (Param(name, kind),)


#: The 10 predicates of 03 §7; each is also an entry point of group `veyltrace.predicates`.
ZSCORE_ABOVE: Final = Predicate(
    "zscore_above", (Param("signal", "signal"), Param("k", "float")), 1, "incident", "z", _zscore_above
)
ONSET_BEFORE: Final = Predicate(
    "onset_before", _one("other_service", "service"), 1, "onset", "ms", _onset_before
)
EDGE_ANOMALOUS: Final = Predicate(
    "edge_anomalous", _one("callee", "service"), -1, "incident", None, _edge_anomalous
)
SELF_TIME_SHARE_ABOVE: Final = Predicate(
    "self_time_share_above", _one("x", "float"), 1, "incident", None, _atom_at_least("self_time_share", "x")
)
CHANGE_BEFORE_ONSET: Final = Predicate(
    "change_before_onset", _one("max_ms", "float"), 1, "onset", "ms", _change_before_onset
)
TEMPLATE_NEW_IN_INCIDENT: Final = Predicate(
    "template_new_in_incident", _one("min_count", "int"), 1, "incident", "count", _template_new
)
ERROR_RATE_ABOVE: Final = Predicate(
    "error_rate_above", _one("x", "float"), 1, "incident", None, _error_rate_above
)
SILENT: Final = Predicate("silent", (), 1, "incident", None, _silent)
ON_CRITICAL_PATH: Final = Predicate(
    "on_critical_path", _one("min_share", "float"), 1, "incident", None, _on_critical_path
)
PEER_GAP_ABOVE: Final = Predicate(
    "peer_gap_above", _one("x", "float"), 1, "incident", "z", _atom_at_least("peer_contrast", "x")
)
_ALL: Final = (ZSCORE_ABOVE, ONSET_BEFORE, EDGE_ANOMALOUS, SELF_TIME_SHARE_ABOVE, CHANGE_BEFORE_ONSET, SILENT)
_ALL_2: Final = (TEMPLATE_NEW_IN_INCIDENT, ERROR_RATE_ABOVE, ON_CRITICAL_PATH, PEER_GAP_ABOVE)
#: The library by name, A→Z.
LIBRARY: Final[Mapping[str, Predicate]] = MappingProxyType(
    {p.name: p for p in sorted((*_ALL, *_ALL_2), key=lambda p: p.name)}
)
