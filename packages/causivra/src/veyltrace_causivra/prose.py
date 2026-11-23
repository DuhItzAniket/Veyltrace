"""Template prose of the card summary (10 §3.5): the AI-off summary and the narration fallback.

The sentences use the same placeholder grammar and filler as LLM narration (X-09), so they carry
no number or entity name of their own and every sentence must pass the claim checker. A sentence
whose atom (`{E*}`) or runner-up is missing is skipped, never filled with a guess.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from veyltrace_causivra.placeholders import FillContext, fill
from veyltrace_contracts import models

__all__ = ["ASKS_SENTENCE", "SENTENCES", "join_phrases", "strongest", "summary", "template_sentences"]

_SIGNAL: Final = "Its strongest internal signal was {E*.label} at {E*.value} {E*.unit}."
_MARGIN: Final = (
    "Confidence is {CONF.level}; its verified score leads {RUNNER_UP} by a relative margin of {CONF.margin}."
)
#: The INCONCLUSIVE sentence that introduces the asks; `{ASK_PHRASES}` is replaced (before
#: filling) by the `ask_phrases.<kind>` words of the kinds the verdict's asks carry (10 §3.5).
ASK_PHRASES: Final = "{ASK_PHRASES}"
ASKS_SENTENCE: Final = "The asks below list what would settle it: " + ASK_PHRASES + "."
#: Sentences per status, in order (10 §3.5). `{E*}` is the root's strongest internal_anomaly atom
#: (`strongest`); a sentence that needs a missing atom, root or runner-up is skipped.
SENTENCES: Final[dict[str, tuple[str, ...]]] = {
    "CONFIRMED": (
        "{ROOT} is the only member of the candidate set and passed every mandatory trial.",
        _SIGNAL,
        _MARGIN,
    ),
    "LIKELY": (
        "{ROOT} is the most likely root cause; the candidate set has {CONF.set_size}.",
        _SIGNAL,
        _MARGIN,
    ),
    "INCONCLUSIVE": (
        "No single root cause could be established; the candidate set has {CONF.set_size}.",
        "The leading candidate is {ROOT}.",
        ASKS_SENTENCE,
    ),
    "NO_FAULT": (
        "No anomaly above threshold was found at the entry service or inside any service.",
        "The candidate set is empty and no root cause is named.",
    ),
}
INTERNAL_KIND: Final = "internal_anomaly"


def strongest(atom_ids: Iterable[str], ctx: FillContext) -> str | None:
    """The atom with the highest value, ties by `atom_id`: FaultLoom's best-atom rule (06 §3.7).

    A root can carry several internal atoms (one per family, detector and source), so table order
    alone could call a weaker one the strongest. An atom without a value ranks last.
    """

    def rank(atom_id: str) -> tuple[bool, float, str]:
        value = ctx.table[atom_id].value
        return (value is None, -value if value is not None else 0.0, atom_id)

    return min(atom_ids, key=rank, default=None)


def join_phrases(phrases: list[str]) -> str:
    """ "a", "a and b", "a, b and c"."""
    return phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]


def summary(
    verdict: models.Verdict,
    ctx: FillContext,
    evidence_kinds: dict[str, str],
    ask_phrases: Mapping[str, str],
) -> list[dict[str, Any]]:
    """card.summary for template prose: `template_sentences`, filled."""
    return [
        {"text": fill(text, cites, ctx), "cites": cites}
        for text, cites in template_sentences(verdict, ctx, evidence_kinds, ask_phrases)
    ]


def template_sentences(
    verdict: models.Verdict,
    ctx: FillContext,
    evidence_kinds: dict[str, str],
    ask_phrases: Mapping[str, str],
) -> list[tuple[str, list[str]]]:
    """The raw template sentences and their cites, before filling: what the claim checker reads
    (10 §7 "Template safety"). `evidence_kinds` maps each table atom to its kind.

    The asks sentence names only the ask kinds the verdict carries, each once in first-occurrence
    order, so a verdict with only context asks never mentions telemetry or trials; without asks it
    is skipped.

    Cites: the strongest-signal sentence cites its atom; the other sentences cite the leader's table
    atoms (the root, or ranked[0] without one), so a sentence is uncited only when no citable atom
    exists (10 §3.5). NO_FAULT sentences state no number and name no candidate, so they cite nothing
    even when the table has atoms.
    """
    leader = ctx.root_service or (verdict.ranked[0].service if verdict.ranked else None)
    leader_atoms = [a for a, atom in ctx.table.items() if atom.candidate == leader]
    signal = strongest((a for a in leader_atoms if evidence_kinds.get(a) == INTERNAL_KIND), ctx)
    kinds = list(dict.fromkeys(ask.kind for ask in verdict.asks))
    out: list[tuple[str, list[str]]] = []
    for template in SENTENCES[verdict.status]:
        text, cites = template, list(leader_atoms)
        if ASK_PHRASES in template:
            if not kinds:
                continue
            text = template.replace(ASK_PHRASES, join_phrases([ask_phrases[k] for k in kinds]))
        if "{E*" in template:
            if signal is None:
                continue
            text, cites = template.replace("{E*", "{" + signal), [signal]
        if ("{RUNNER_UP" in text and ctx.runner_up is None) or ("{ROOT" in text and ctx.root_service is None):
            continue
        if verdict.status == "NO_FAULT":
            cites = []
        out.append((text, cites))
    return out
