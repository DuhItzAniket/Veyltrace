"""Trials of 09 §3.4: T1–T4 (mandatory) evaluated; T5, T6, T8 only where a fact fixes them.

Each trial returns `pass`, `fail` or `untestable` with a 09 §3.4 reason and the atom ids it used;
T1–T4 apply to every candidate. They are declared under the entry-point
group `veyltrace.trials` (09 §5). Until R-12 evaluates T5–T10, `pending()` writes only the
`untestable` results an existence fact fixes (as the R-00 stub did); those are supporting trials,
whose untestable factor is 1.0, so they never move V.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from veyltrace_causatrix.views import Atom, EvidenceView, GraphView
from veyltrace_causentra.config import CausentraConfig
from veyltrace_causentra.inputs import DECIMALS, CausentraInputs
from veyltrace_contracts import models

PASS: Final = "pass"
FAIL: Final = "fail"
UNTESTABLE: Final = "untestable"


@dataclass(frozen=True)
class TrialInputs:
    """What T1–T4 read: the views, sources, alignment tolerance and the trial thresholds."""

    ev: EvidenceView
    graph: GraphView
    sources: models.Sources
    tol_ms: float
    k_anom: float
    t2_min_fraction: float
    t3_min_path_fraction: float


@dataclass(frozen=True)
class TrialResult:
    """One `ranked[].trials[]` entry (03 §10): reason is null on pass; atoms are sorted ids."""

    id: str
    result: str
    reason: str | None
    atoms: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {"id": self.id, "result": self.result, "reason": self.reason, "atoms": list(self.atoms)}


@dataclass(frozen=True)
class Trial:
    id: str
    check: Callable[[str, TrialInputs], TrialResult]


def trial_inputs(inp: CausentraInputs, cfg: CausentraConfig) -> TrialInputs:
    return TrialInputs(
        inp.ev,
        inp.graph,
        inp.manifest.sources,
        inp.tol_ms,
        cfg.k_anom,
        cfg.t2_min_fraction,
        cfg.t3_min_path_fraction,
    )


def _result(tid: str, result: str, reason: str | None, atoms: Iterable[Atom | None]) -> TrialResult:
    return TrialResult(tid, result, reason, tuple(sorted({a.atom_id for a in atoms if a is not None})))


def _scoped(ev: EvidenceView, service: str, kind: str, scope: str) -> list[Atom]:
    return [a for a in ev.atoms_of(service, kind) if a.args.get("scope") == scope]


def origin(c: str, t: TrialInputs) -> TrialResult:
    """T1: an internal anomaly (or silence) not explained by a direct callee."""
    f, silence = t.ev.of(c), t.ev.atoms_of(c, "silence")
    if f.top_internal is None and not silence:
        return _result("T1", UNTESTABLE, "no_internal_series", ())
    own = [f.top_internal, *silence]
    if not (f.internal >= t.k_anom or f.silent == 1.0):
        return _result("T1", FAIL, "no_internal_anomaly", own)
    compared: list[Atom | None] = []
    for edge in t.graph.callees(c):
        d = t.ev.of(edge.dst)
        compared.append(d.top_internal)
        not_later = math.isinf(d.onset_ms) or d.onset_ms <= f.onset_ms + t.tol_ms  # missing onset: not later
        if d.internal >= f.internal and not_later:
            return _result("T1", FAIL, f"explained_by_callee:{edge.dst}", [*own, d.top_internal])
    return _result("T1", PASS, None, [*own, *compared])


def precedence(c: str, t: TrialInputs) -> TrialResult:
    """T2: the onset is not later than its anomalous dependents' onsets (aligned, with tolerance)."""
    own = _scoped(t.ev, c, "onset_precedence", "self")
    if not own:
        return _result("T2", UNTESTABLE, "no_onset", ())
    dependents = _scoped(t.ev, c, "onset_precedence", "dependents")
    if not dependents:  # no anomalous dependents: vacuously first
        return _result("T2", PASS, None, own)
    ok = round(max(a.value for a in dependents), DECIMALS) >= t.t2_min_fraction
    return _result("T2", PASS if ok else FAIL, None if ok else "dependent_earlier", [*own, *dependents])


def propagation(c: str, t: TrialInputs) -> TrialResult:
    """T3: every anomalous entry is reachable from c, along an anomalous enough path."""
    if not t.graph.has_edges:
        return _result("T3", UNTESTABLE, "no_graph_edges", ())
    entry = _scoped(t.ev, c, "propagation", "entry")
    if not entry:
        return _result("T3", UNTESTABLE, "no_anomalous_entry", ())
    path = _scoped(t.ev, c, "propagation", "path")
    used = [*entry, *path]
    if round(max(a.value for a in entry), DECIMALS) < 1.0:
        return _result("T3", FAIL, "entry_unreachable", used)
    if path and round(max(a.value for a in path), DECIMALS) < t.t3_min_path_fraction:
        return _result("T3", FAIL, "path_not_anomalous", used)
    return _result("T3", PASS, None, used)


def _descendants(c: str, graph: GraphView) -> list[str]:
    seen: set[str] = set()
    frontier = [c]
    while frontier:
        nxt = sorted({e.dst for u in frontier for e in graph.callees(u)} - seen - {c})
        seen.update(nxt)
        frontier = nxt
    return sorted(seen)


def silence_check(c: str, t: TrialInputs) -> TrialResult:
    """T4: c is not a victim of a silent service it calls (directly or further down)."""
    own = t.ev.atoms_of(c, "silence")
    if not own:
        return _result("T4", UNTESTABLE, "no_silence_status", ())
    if not t.graph.has_edges:
        return _result("T4", UNTESTABLE, "no_graph_edges", ())
    for d in _descendants(c, t.graph):
        if t.ev.of(d).silent == 1.0:
            return _result("T4", FAIL, f"silent_callee:{d}", [*own, *t.ev.atoms_of(d, "silence")])
    return _result("T4", PASS, None, own)


T1: Final = Trial("T1", origin)
T2: Final = Trial("T2", precedence)
T3: Final = Trial("T3", propagation)
T4: Final = Trial("T4", silence_check)
#: The trials R-10 evaluates, in numeric order (09 §3.4); R-12 adds T5–T10.
EVALUATED: Final = (T1, T2, T3, T4)


def pending(c: str, t: TrialInputs) -> list[TrialResult]:
    """T5, T6, T8 results that an existence fact fixes as untestable (09 §3.4); the rest omitted."""
    out: list[TrialResult] = []
    if t.sources.traces and not t.ev.atoms_of(c, "self_time_share"):
        out.append(_result("T5", UNTESTABLE, "no_latency_increase", ()))
    if not t.sources.events:
        out.append(_result("T6", UNTESTABLE, "no_events", ()))
    if not t.ev.atoms_of(c, "intervention"):
        out.append(_result("T8", UNTESTABLE, "intervention_unavailable", ()))
    return out


def run_trials(c: str, t: TrialInputs) -> tuple[TrialResult, ...]:
    """Every written trial of candidate c, in T1…T10 order (03 §10)."""
    return (*(trial.check(c, t) for trial in EVALUATED), *pending(c, t))
