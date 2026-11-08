"""Template prose of the card summary (10 §3.5): the AI-off summary and the narration fallback.

The sentences use the same placeholder grammar and filler as LLM narration (X-09), so they carry
no number or entity name of their own and every sentence must pass the claim checker. A sentence
whose atom (`{E*}`) or runner-up is missing is skipped, never filled with a guess.
"""

from __future__ import annotations

from typing import Any, Final

from veyltrace_causivra.placeholders import FillContext, fill
from veyltrace_contracts import models

__all__ = ["SENTENCES", "summary"]

_SIGNAL: Final = "Its strongest internal signal was {E*.label} at {E*.value} {E*.unit}."
_MARGIN: Final = (
    "Confidence is {CONF.level}; its verified score leads {RUNNER_UP} by a relative margin of {CONF.margin}."
)
#: Sentences per status, in order (10 §3.5). `{E*}` is the first internal_anomaly atom of the root
#: in table order; a sentence that needs a missing atom, root or runner-up is skipped.
SENTENCES: Final[dict[str, tuple[str, ...]]] = {
    "CONFIRMED": (
        "{ROOT} is the only member of the candidate set and passed every mandatory trial.",
        _SIGNAL,
        _MARGIN,
    ),
    "LIKELY": (
        "{ROOT} is the most likely root cause; the candidate set has {CONF.set_size} services.",
        _SIGNAL,
        _MARGIN,
    ),
    "INCONCLUSIVE": (
        "No single root cause could be established; the candidate set has {CONF.set_size} services.",
        "The leading candidate is {ROOT}.",
        "The asks below list the telemetry or trials that would settle it.",
    ),
    "NO_FAULT": (
        "No anomaly above threshold was found at the entry service or inside any service.",
        "The candidate set is empty and no root cause is named.",
    ),
}
INTERNAL_KIND: Final = "internal_anomaly"


def summary(
    verdict: models.Verdict, ctx: FillContext, evidence_kinds: dict[str, str]
) -> list[dict[str, Any]]:
    """card.summary for template prose. `evidence_kinds` maps each table atom to its kind.

    Cites: the strongest-signal sentence cites its atom; the other sentences cite the leader's table
    atoms (the root, or ranked[0] without one), so a sentence is uncited only when no citable atom
    exists (10 §3.5). NO_FAULT sentences name no candidate and cite nothing.
    """
    leader = ctx.root_service or (verdict.ranked[0].service if verdict.ranked else None)
    leader_atoms = [a for a, atom in ctx.table.items() if atom.candidate == leader]
    signal = next((a for a in leader_atoms if evidence_kinds.get(a) == INTERNAL_KIND), None)
    out: list[dict[str, Any]] = []
    for template in SENTENCES[verdict.status]:
        text, cites = template, list(leader_atoms)
        if "{E*" in template:
            if signal is None:
                continue
            text, cites = template.replace("{E*", "{" + signal), [signal]
        if ("{RUNNER_UP" in text and ctx.runner_up is None) or ("{ROOT" in text and ctx.root_service is None):
            continue
        if verdict.status == "NO_FAULT":
            cites = []
        out.append({"text": fill(text, cites, ctx), "cites": cites})
    return out
