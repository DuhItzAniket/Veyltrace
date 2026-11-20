"""Trials of 09 §3.4: T1–T4 (mandatory, every candidate) and the supporting trials T5–T9.

Each trial returns `pass`, `fail` or `untestable` with a 09 §3.4 reason and the atom ids it used.
A trial whose precondition is false (T5 without traces, T7 without a `peer_contrast` atom) is not
applicable: it is omitted from `trials[]` and contributes no factor (T9 needs ≥ 2 sources). They
are declared under the entry-point group `veyltrace.trials` (09 §5). T10 is `decision.claim_check`
(proposal origin only). Every value is compared at 9 decimals, the precision the verdict shows.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from veyltrace_causatrix.views import Atom, EvidenceView, GraphView
from veyltrace_causentra.config import CausentraConfig
from veyltrace_causentra.inputs import DECIMALS, CausentraInputs
from veyltrace_causentra.loso import Ablation, ablations
from veyltrace_contracts import models

PASS: Final = "pass"
FAIL: Final = "fail"
UNTESTABLE: Final = "untestable"


@dataclass(frozen=True)
class TrialInputs:
    """What the trials read: the views, sources, alignment tolerance and the trial thresholds."""

    ev: EvidenceView
    graph: GraphView
    sources: models.Sources
    tol_ms: float
    k_anom: float
    t2_min_fraction: float
    t3_min_path_fraction: float
    t5_min_share: float
    t6_min_proximity: float
    t7_min_gap: float
    k: int
    ablations: tuple[Ablation, ...]


@dataclass(frozen=True)
class TrialResult:
    """One `ranked[].trials[]` entry (03 §10): reason is null on pass; atoms are sorted ids."""

    id: str
    result: str
    reason: str | None
    atoms: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {"id": self.id, "result": self.result, "reason": self.reason, "atoms": list(self.atoms)}


def _always(_c: str, _t: TrialInputs) -> bool:
    return True


@dataclass(frozen=True)
class Trial:
    """A trial: `check` runs it on one candidate when `applies` (09 §3.4 "Applicable") holds."""

    id: str
    check: Callable[[str, TrialInputs], TrialResult]
    applies: Callable[[str, TrialInputs], bool] = _always


def trial_inputs(inp: CausentraInputs, cfg: CausentraConfig) -> TrialInputs:
    return TrialInputs(
        inp.ev,
        inp.graph,
        inp.manifest.sources,
        inp.tol_ms,
        cfg.k_anom,
        cfg.t2_min_fraction,
        cfg.t3_min_path_fraction,
        cfg.t5_min_share,
        cfg.t6_min_proximity,
        cfg.t7_min_gap,
        inp.slate.k,
        ablations(inp.ev, inp.graph, inp.manifest.sources, inp.causatrix),
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


def _at_least(atoms: Iterable[Atom], threshold: float) -> bool:
    """max value ≥ threshold, both at 9 decimals (09 §5); False without atoms."""
    values = [a.value for a in atoms]
    return bool(values) and round(max(values), DECIMALS) >= round(threshold, DECIMALS)


def latency_accounting(c: str, t: TrialInputs) -> TrialResult:
    """T5: c's critical-path self-time increase is a large enough share of the entry latency increase."""
    shares = t.ev.atoms_of(c, "self_time_share")
    if not shares:  # FaultLoom writes none below self_time.min_total_increase_ms (06 §3.4)
        return _result("T5", UNTESTABLE, "no_latency_increase", ())
    ok = _at_least(shares, t.t5_min_share)
    return _result("T5", PASS if ok else FAIL, None if ok else "share_below_min", shares)


def change_alignment(c: str, t: TrialInputs) -> TrialResult:
    """T6: a change on c came at most about τ_change before its onset (CH(c) ≥ e⁻¹)."""
    if not t.sources.events:
        return _result("T6", UNTESTABLE, "no_events", ())
    changes = t.ev.atoms_of(c, "change_proximity")
    ok = _at_least(changes, t.t6_min_proximity)
    return _result("T6", PASS if ok else FAIL, None if ok else "no_recent_change", changes)


def peer_contrast(c: str, t: TrialInputs) -> TrialResult:
    """T7: c's affected component (or changed replica) stands out from its peers."""
    peers = t.ev.atoms_of(c, "peer_contrast")
    ok = _at_least(peers, t.t7_min_gap)
    return _result("T7", PASS if ok else FAIL, None if ok else "peers_alike", peers)


def intervention(c: str, t: TrialInputs) -> TrialResult:
    """T8: c's anomaly persists after regressing out its parents (stat_resid ≥ k_anom)."""
    tests = t.ev.atoms_of(c, "intervention")
    if not tests:  # CI test untestable, or c beyond intervention.max_candidates (06 §3.6)
        return _result("T8", UNTESTABLE, "intervention_unavailable", ())
    ok = _at_least(tests, t.k_anom)
    return _result("T8", PASS if ok else FAIL, None if ok else "explained_by_parents", tests)


def leave_one_source_out(c: str, t: TrialInputs) -> TrialResult:
    """T9: c stays within the slate's top K when each present source is dropped (first offender,
    sources sorted, names the failure). No atoms: the evidence is the re-ranking itself."""
    for source, order in t.ablations:
        if c not in order[: t.k]:
            return _result("T9", FAIL, f"drops_out_without:{source}", ())
    return _result("T9", PASS, None, ())


def _has_traces(_c: str, t: TrialInputs) -> bool:
    return t.sources.traces


def _has_peers(c: str, t: TrialInputs) -> bool:
    return bool(t.ev.atoms_of(c, "peer_contrast"))


def _multi_source(_c: str, t: TrialInputs) -> bool:
    return bool(t.ablations)  # one re-ranking per present source, none below 2 sources


T1: Final = Trial("T1", origin)
T2: Final = Trial("T2", precedence)
T3: Final = Trial("T3", propagation)
T4: Final = Trial("T4", silence_check)
T5: Final = Trial("T5", latency_accounting, _has_traces)
T6: Final = Trial("T6", change_alignment)
T7: Final = Trial("T7", peer_contrast, _has_peers)
T8: Final = Trial("T8", intervention)
T9: Final = Trial("T9", leave_one_source_out, _multi_source)
#: The trials run on every decision-pool candidate, in numeric order (09 §3.4); T10 is
#: decision.claim_check.
EVALUATED: Final = (T1, T2, T3, T4, T5, T6, T7, T8, T9)


def run_trials(c: str, t: TrialInputs) -> tuple[TrialResult, ...]:
    """Every applicable trial of candidate c, in T1…T10 order (03 §10)."""
    return tuple(trial.check(c, t) for trial in EVALUATED if trial.applies(c, t))
