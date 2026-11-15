"""Call edges (02 §3.3) and CRISP-style critical paths with the slow-trace spectrum (02 §3.4).

Both are per alert window (`baseline`, `incident`; 03 §2.6), so only these tables move with the
windows. An edge is a caller → callee pair whose child is an entry span; its gap columns exist only
when a client-like span wraps the child. The critical path walks back from each span's end, taking
the child that finished last before the current point; time in client-like spans is gap, charged
to no service, so per trace Σ self + gap = root duration (property-tested).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from veyltrace_core import io
from veyltrace_signalyth.spans import MS, Forest, TraceRules, sample_hash, tree_roots

__all__ = ["TracePath", "critical_path_rows", "edge_rows", "trace_paths", "walk"]

type Vec = np.ndarray[Any, Any]
WINDOWS: Final = ("baseline", "incident")
P95: Final = 0.95


def _window(t: Vec, windows: dict[str, tuple[int, int]]) -> Vec:
    """Window name per time (half-open intervals), '' outside both."""
    out = np.full(t.size, "", dtype=object)
    for name in WINDOWS:
        lo, hi = windows[name]
        out[(t >= lo) & (t < hi)] = name
    return out


def _q(values: list[float], min_n: int) -> tuple[float | None, float | None]:
    if len(values) < min_n:
        return None, None
    q = np.quantile(np.asarray(values, dtype=np.float64), (0.5, 0.99), method="linear")
    return float(q[0]), float(q[1])


def edge_rows(f: Forest, rules: TraceRules, windows: dict[str, tuple[int, int]]) -> dict[str, list[Any]]:
    """`signal_cube.edges` columns: one row per (caller, callee, window) with calls ≥ 1."""
    kids = np.nonzero(f.entry & (f.parent >= 0))[0]
    parents = f.parent[kids]
    win = _window(f.start[kids], windows)
    groups: dict[tuple[str, str, str], list[int]] = {}
    for k, p, w in zip(kids.tolist(), parents.tolist(), win.tolist(), strict=True):
        if w:
            key = (f.services[int(f.service[p])], f.services[int(f.service[k])], str(w))
            groups.setdefault(key, []).append(int(k))
    cols: dict[str, list[Any]] = {k: [] for k in io.arrow_schema("signal_cube.edges").names}
    for (caller, callee, window), members in sorted(groups.items()):
        k = np.asarray(members, dtype=np.int64)
        p = f.parent[k]
        wrapped = f.client[p]
        errors = f.error[k] | (wrapped & f.error[p])
        child_ms = ((f.end[k] - f.start[k]) / MS).tolist()
        client_ms = ((f.end[p] - f.start[p])[wrapped] / MS).tolist()
        gap_ms = (((f.end[p] - f.start[p]) - (f.end[k] - f.start[k]))[wrapped] / MS).tolist()
        n = rules.min_spans_per_quantile
        row = (
            caller,
            callee,
            window,
            int(k.size),
            float(errors.mean()),
            *_q(client_ms, n),
            *_q(child_ms, n),
            *_q(gap_ms, n),
        )
        for name, value in zip(cols, row, strict=True):
            cols[name].append(value)
    return cols


def walk(f: Forest, kids: dict[int, list[int]], root: int, tol: int) -> tuple[dict[int, int], int]:
    """(critical-path self ns per service code, gap ns) of the tree under `root` (02 §3.4)."""
    self_ns: dict[int, int] = {}
    gap = 0

    def charge(s: int, length: int) -> None:
        nonlocal gap
        if length <= 0:
            return
        if f.client[s]:
            gap += length
        else:
            self_ns[int(f.service[s])] = self_ns.get(int(f.service[s]), 0) + length

    stack = [(root, int(f.start[root]), int(f.end[root]))]
    while stack:
        s, lo, hi = stack.pop()
        t = hi
        for c in kids.get(s, ()):
            if t <= lo:
                break
            c_end, c_start = int(f.end[c]), int(f.start[c])
            if c_end - t > tol:
                continue  # ends after the current point: it overlaps the path, skip it
            e, b = min(c_end, t), max(c_start, lo)
            if e <= lo or b >= e:
                continue
            charge(s, t - e)
            stack.append((c, b, e))
            t = b
        charge(s, t - lo)
    return self_ns, gap


@dataclass(frozen=True)
class TracePath:
    """One eligible trace's critical path: window, root (service, operation), root duration,
    and CP self ns per service code."""

    window: str
    root_key: tuple[int, str]
    duration: int
    self_ns: dict[int, int]
    services: frozenset[int]


def trace_paths(
    f: Forest, rules: TraceRules, windows: dict[str, tuple[int, int]], case_id: str
) -> list[TracePath]:
    """Critical paths of the eligible traces, at most `cp.max_traces_per_window` per window chosen
    by ascending sha256(case_id ‖ trace_id) (no RNG)."""
    n = f.size
    if n == 0:
        return []
    top = tree_roots(f.parent, f.trace, f.trace_ids)  # fails on a parent cycle, never loops
    tree = np.bincount(top, minlength=n)
    per_trace = np.bincount(f.trace)
    roots = np.nonzero(f.parent < 0)[0]
    dur = f.end - f.start
    # primary root per trace: longest, then earliest start, then smallest span_id (sorted order)
    best: dict[int, int] = {}
    for r in roots.tolist():
        t, cur = int(f.trace[r]), best.get(int(f.trace[r]))
        if cur is None or dur[r] > dur[cur]:
            best[t] = r
    order = np.lexsort(
        (f.span_ids.astype(str), -f.start, -f.end, f.parent)
    )  # by parent: end desc, start desc, id
    kids: dict[int, list[int]] = {}
    for c in order.tolist():
        if f.parent[c] >= 0:
            kids.setdefault(int(f.parent[c]), []).append(c)
    chosen: dict[str, list[tuple[int, int]]] = {w: [] for w in WINDOWS}
    for t, r in best.items():
        win = _window(f.start[r : r + 1], windows)[0]
        if win and dur[r] > 0 and tree[r] >= rules.min_tree_fraction * per_trace[t]:
            chosen[win].append((sample_hash(case_id, f.trace_ids[t]), r))
    span_of_trace = np.argsort(f.trace, kind="stable")
    bounds = np.searchsorted(f.trace[span_of_trace], np.arange(len(f.trace_ids) + 1))
    out: list[TracePath] = []
    for win in WINDOWS:
        for _, r in sorted(chosen[win])[: rules.max_traces_per_window]:
            t = int(f.trace[r])
            members = span_of_trace[bounds[t] : bounds[t + 1]]
            self_ns, _ = walk(f, kids, r, rules.skew_tolerance_ns)
            key = (int(f.service[r]), str(f.operation[r]))
            out.append(TracePath(win, key, int(dur[r]), self_ns, frozenset(f.service[members].tolist())))
    return out


def critical_path_rows(f: Forest, paths: list[TracePath], min_n: int) -> dict[str, list[Any]]:
    """`signal_cube.critical_path` columns: per (window, service seen in the window's eligible traces)."""
    cols: dict[str, list[Any]] = {k: [] for k in io.arrow_schema("signal_cube.critical_path").names}
    baseline: dict[tuple[int, str], list[float]] = {}
    for p in paths:
        if p.window == "baseline":
            baseline.setdefault(p.root_key, []).append(float(p.duration))
    p95 = {k: float(np.quantile(v, P95, method="linear")) for k, v in baseline.items() if len(v) >= min_n}
    for win in WINDOWS:
        members = [p for p in paths if p.window == win]
        services = sorted({s for p in members for s in p.services}, key=lambda s: f.services[s])
        for svc in services:
            on = [p for p in members if p.self_ns.get(svc, 0) > 0]
            slow = [p for p in on if p.root_key in p95 and p.duration > p95[p.root_key]]
            selfs = [p.self_ns[svc] / MS for p in on]
            q50, q99 = _q(selfs, 1)
            row = (win, f.services[svc], len(on), q50 or 0.0, q99 or 0.0,
                   sum(p.self_ns[svc] / p.duration for p in on) / len(members), len(members), len(slow),
                   sum(p.self_ns[svc] / p.duration for p in slow))  # fmt: skip
            for name, value in zip(cols, row, strict=True):
                cols[name].append(value)
    return cols
