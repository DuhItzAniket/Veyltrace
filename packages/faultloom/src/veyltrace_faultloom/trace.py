"""Trace evidence atoms (06 §3.4): `spectrum`, `critical_path_share`, `self_time_share`, `edge_gap`.

Why: CP-weighted Ochiai (`spectrum`) ranks services by how much of the slow traces' critical path
they own (cp_sbfl ranker), `self_time_share` is trial T5's latency accounting, and `edge_gap`
carries network faults, which widen the caller-callee gap while the callee's own time stays flat.
All read Signalyth's pre-aggregated baseline/incident tables as given (06 §2.1). A case without
traces gives none of them (06 §6).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final

from veyltrace_core.errors import ConfigError
from veyltrace_faultloom.atoms import Atom, engine_atom
from veyltrace_faultloom.change import median
from veyltrace_faultloom.inputs import CriticalPathRow, EdgeStat, EvidenceInputs

__all__ = ["critical_path_atoms", "edge_gap_atoms", "self_time_atoms", "spectrum_atoms"]

_BASE: Final = "baseline"
_INC: Final = "incident"
#: Spectrum formulas 06 §3.4 defines; 06 §4's `dstar2` ablation has no formula in 06 yet.
_FORMULAS: Final = frozenset({"ochiai"})
_WEIGHTINGS: Final = frozenset({"critical_path", "none"})
_QUANTILES: Final = ("p50", "p99")


def _rows(view: EvidenceInputs, window: str) -> Mapping[str, CriticalPathRow]:
    return {r.service: r for r in view.critical_path if r.window == window}


def spectrum_atoms(view: EvidenceInputs, formula: str, weighting: str) -> list[Atom]:
    """CP-weighted Ochiai over slow incident traces for every c in U (06 §3.4 "Spectrum").

    e_f = cp_share_sum_slow[inc, c]; cov = traces_total[inc] * cp_share_mean[inc, c];
    F = max_s traces_slow[inc, s]; value = e_f / sqrt(F * cov), 0 when e_f = 0 or F = 0.
    weighting none: e_f = traces_slow, cov = traces. Missing row = 0 (06 §3.9).
    """
    if formula not in _FORMULAS or weighting not in _WEIGHTINGS:
        msg = f"faultloom.spectrum: formula {formula!r} / weighting {weighting!r} is not defined in 06 §3.4"
        raise ConfigError(msg)
    inc = _rows(view, _INC)
    total = max((r.traces_total for r in inc.values()), default=0)
    if not view.sources.traces or total == 0:  # no eligible incident trace: no spectrum (06 §3.9)
        return []
    slow = max(r.traces_slow for r in inc.values())
    args = {"formula": formula, "weighting": weighting, "window": _INC}
    atoms: list[Atom] = []
    for c in view.universe:
        row = inc.get(c)
        if row is None:
            e_f, cov, refs = 0.0, 0.0, ()
        elif weighting == "none":
            e_f, cov, refs = float(row.traces_slow), float(row.traces), (row.ref,)
        else:
            e_f, cov, refs = row.cp_share_sum_slow, total * row.cp_share_mean, (row.ref,)
        value = 0.0 if e_f <= 0 or slow <= 0 or cov <= 0 else e_f / math.sqrt(slow * cov)
        atoms.append(engine_atom("spectrum", c, args, value=value, unit=None, refs=refs))
    return atoms


def critical_path_atoms(view: EvidenceInputs) -> list[Atom]:
    """`critical_path_share{window}` = cp_share_mean, 0 when c is absent, per window with traces
    (traces_total > 0, 06 §3.9)."""
    if not view.sources.traces:
        return []
    atoms: list[Atom] = []
    for window in (_BASE, _INC):
        rows = _rows(view, window)
        if not rows or max(r.traces_total for r in rows.values()) == 0:
            continue
        for c in view.universe:
            row = rows.get(c)
            value, refs = (0.0, ()) if row is None else (row.cp_share_mean, (row.ref,))
            atoms.append(
                engine_atom("critical_path_share", c, {"window": window}, value=value, unit=None, refs=refs)
            )
    return atoms


def self_time_atoms(view: EvidenceInputs, quantile: str, min_total_ms: float) -> list[Atom]:
    """`self_time_share`: c's share of the positive critical-path self-time increase over U
    (06 §3.4), emitted when that total is >= `min_total_ms`."""
    if quantile not in _QUANTILES:
        msg = f"faultloom.self_time.quantile must be one of {_QUANTILES}, got {quantile!r}"
        raise ConfigError(msg)
    base, inc = _rows(view, _BASE), _rows(view, _INC)

    ms = {
        w: {s: r.cp_self_ms_p50 if quantile == "p50" else r.cp_self_ms_p99 for s, r in rows.items()}
        for w, rows in ((_BASE, base), (_INC, inc))
    }
    rise = {s: max(0.0, ms[_INC].get(s, 0.0) - ms[_BASE].get(s, 0.0)) for s in view.universe}
    total = math.fsum(rise[s] for s in view.universe)
    if total < min_total_ms or total <= 0:
        return []
    args = {"quantile": quantile, "window": _INC}
    atoms: list[Atom] = []
    for c in view.universe:
        refs = tuple(r.ref for r in (base.get(c), inc.get(c)) if r is not None)
        atoms.append(engine_atom("self_time_share", c, args, value=rise[c] / total, unit=None, refs=refs))
    return atoms


def _gap(row: EdgeStat, quantile: str) -> float | None:
    return row.p50_gap_ms if quantile == "p50" else row.p99_gap_ms


def edge_gap_atoms(view: EvidenceInputs, min_calls: int) -> list[Atom]:
    """`edge_gap{direction, quantile}`: median Δgap over c's qualifying edges (06 §3.4 "Edge gap").

    Qualifying: incident calls >= `min_calls` and a non-null gap in both windows.
    """
    pairs: dict[tuple[str, str], dict[str, EdgeStat]] = {}
    for e in view.edge_stats:
        pairs.setdefault((e.caller, e.callee), {})[e.window] = e
    atoms: list[Atom] = []
    for c in view.universe:
        for direction in ("in", "out"):
            for q in _QUANTILES:
                deltas: list[float] = []
                refs: list[str] = []
                for (caller, callee), by_window in sorted(pairs.items()):
                    if (callee if direction == "in" else caller) != c:
                        continue
                    b, i = by_window.get(_BASE), by_window.get(_INC)
                    if b is None or i is None or i.calls < min_calls:
                        continue
                    gb, gi = _gap(b, q), _gap(i, q)
                    if gb is not None and gi is not None:
                        deltas.append(gi - gb)
                        refs += (b.ref, i.ref)
                if deltas:
                    args = {"direction": direction, "quantile": q, "window": _INC}
                    atoms.append(engine_atom("edge_gap", c, args, value=median(deltas), unit="ms", refs=refs))
    return atoms
