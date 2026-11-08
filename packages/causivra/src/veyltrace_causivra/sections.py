"""Card sections from 10 §3.1 steps 4–7: timeline, propagation path, why-not and asks.

Each is a pure function of the verdict, run artifacts and the card settings; prose goes through
the placeholder filler, so every name in it is a resolved `{SVC:…}` and every cite an atom of the
evidence table. Lists are sorted as 10 §2.2 states.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from veyltrace_causivra.assemble import CardSettings, args_of
from veyltrace_causivra.placeholders import FillContext, fill
from veyltrace_contracts import models

__all__ = ["WHY_NOT_FAILED", "WHY_NOT_PASSED", "WHY_NOT_UNTESTED", "asks", "path", "timeline", "why_not"]

#: onset_precedence scopes that speak about a service's own onset (timeline cites, 10 §3.1 step 4).
ONSET_SCOPES: Final = frozenset({"self", "internal_vs_external"})
PROPOSAL_MANDATORY: Final = "T10"  # mandatory for proposal-origin candidates (09 §3.4)

#: Why-not text by the runner-up's first failing trial (10 §3.1 step 6; trial meaning from 09 §3.4).
WHY_NOT_FAILED: Final[Mapping[str, str]] = {
    "T1": "{SVC:x} showed no internal anomaly that its callees do not explain (failed T1, origin).",
    "T2": "{SVC:x} started after its dependents (failed T2, precedence).",
    "T3": "No anomalous path leads from {SVC:x} to the entry services (failed T3, propagation).",
    "T4": (
        "A service that {SVC:x} calls went silent, so {SVC:x} may be its victim (failed T4, silence check)."
    ),
    "T5": (
        "{SVC:x} self-time explains too little of the entry latency increase (failed T5, latency accounting)."
    ),
    "T6": "No change on {SVC:x} preceded the onset closely enough (failed T6, change alignment).",
    "T7": "{SVC:x} behaves like its peers (failed T7, peer contrast).",
    "T8": "The parents of {SVC:x} explain its anomaly (failed T8, intervention).",
    "T9": (
        "{SVC:x} leaves the top candidates when one telemetry source is dropped (failed T9, source ablation)."
    ),
    "T10": "A proposed claim about {SVC:x} did not hold (failed T10, claim checks).",
}
WHY_NOT_PASSED: Final = (
    "{SVC:x} passed the mandatory trials but its verified score did not exceed the leader's."
)
WHY_NOT_UNTESTED: Final = (
    "{SVC:x} failed no trial, but some of its mandatory trials were untestable, "
    "and its verified score did not exceed the leader's."
)


# --- step 4: timeline ----------------------------------------------------------------------------
def timeline(
    verdict: models.Verdict,
    alert: models.Alert,
    onsets: models.Onsets | None,
    changes: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Alert, incident onset, the root's onsets and the pool's changes inside the windows."""
    label = f"alert ({alert.protocol}{', windows clamped' if alert.clamped else ''})"
    entries: list[dict[str, Any]] = [{"t_ns": alert.t_alert_ns, "label": label, "cites": []}]
    if onsets is not None:
        entries.append({"t_ns": onsets.t_onset_ns, "label": "incident onset", "cites": []})
        root = verdict.root
        own = [o for o in onsets.per_service if root is not None and o.service == root.service]
        if root is not None and own:
            cites = sorted(
                str(r["atom_id"])
                for r in rows
                if r["kind"] == "onset_precedence"
                and r["candidate"] == root.service
                and args_of(r).get("scope") in ONSET_SCOPES
            )
            for which, t_ns in (
                ("internal", own[0].internal_onset_ns),
                ("external", own[0].external_onset_ns),
            ):
                if t_ns is not None:
                    entries.append({"t_ns": t_ns, "label": f"{root.service} {which} onset", "cites": cites})
    pool = {r.service for r in verdict.ranked} | {r.component for r in verdict.ranked if r.component}
    start, end = alert.windows.baseline[0], alert.windows.incident[1]  # half-open [start, end)
    for change in changes:
        t_ns = int(change["t_ns"])
        if str(change["entity"]) in pool and start <= t_ns < end:
            change_id = str(change["change_id"])
            cites = sorted(
                str(r["atom_id"])
                for r in rows
                if r["kind"] == "change_proximity" and args_of(r).get("change_id") == change_id
            )
            entries.append(
                {"t_ns": t_ns, "label": f"{change['entity']} {change['kind']} change", "cites": cites}
            )
    return sorted(entries, key=lambda e: (e["t_ns"], e["label"]))


# --- step 5: path --------------------------------------------------------------------------------
def path(verdict: models.Verdict, paths: Sequence[Mapping[str, Any]]) -> list[str]:
    """`graph.paths.nodes` of the root at path_rank 1; [] when there is no root or no path."""
    if verdict.root is None:
        return []
    best = [p for p in paths if p["candidate"] == verdict.root.service and p["path_rank"] == 1]
    return [str(n) for n in best[0]["nodes"]] if best else []


# --- step 6: why-not -----------------------------------------------------------------------------
def why_not(verdict: models.Verdict, ctx: FillContext, settings: CardSettings) -> list[dict[str, Any]]:
    """Runner-ups ranked[1 … why_not.max]; empty for NO_FAULT (no root to compare against)."""
    if verdict.status == "NO_FAULT":
        return []
    out: list[dict[str, Any]] = []
    for runner in verdict.ranked[1 : 1 + settings.why_not_max]:
        failed = next((t for t in runner.trials if t.result == "fail"), None)
        mandatory = set(settings.mandatory)
        if runner.origin == "proposal":
            mandatory.add(PROPOSAL_MANDATORY)
        if failed is not None:
            template, cites = WHY_NOT_FAILED[failed.id], [a for a in failed.atoms if a in ctx.table]
        elif all(t.result == "pass" for t in runner.trials if t.id in mandatory):
            template, cites = WHY_NOT_PASSED, []
        else:
            template, cites = WHY_NOT_UNTESTED, []
        if not cites:
            first = next((a for a, atom in ctx.table.items() if atom.candidate == runner.service), None)
            cites = [first] if first is not None else []
        text = fill(template.replace("{SVC:x}", "{SVC:" + runner.service + "}"), cites, ctx)
        out.append({"service": runner.service, "text": text, "cites": cites})
    return out


# --- step 7: asks --------------------------------------------------------------------------------
def asks(verdict: models.Verdict, settings: CardSettings) -> list[dict[str, str]]:
    """verdict.asks rendered by the `asks.<kind>` templates, in verdict order."""
    return [
        {"text": settings.asks[a.kind].format_map({"kind": a.kind, "target": a.target, "why": a.why})}
        for a in verdict.asks
    ]
