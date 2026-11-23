"""LLM narration of the card summary (10 §3.2): at most two calls, then template prose.

Why the model sees no values: it writes `{E<atom>.value}` and code fills it, so every digit on the
card comes from an atom. Each sentence passes the claim checker before filling; one repair names
each failing sentence's rule and token. A second failure, a provider error or the latency budget
(recorded latency only, so replay reproduces it) gives template prose, as with AI off.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Final, cast

from veyltrace_causivra.checker import CheckerSettings, Finding, check_sentence
from veyltrace_causivra.placeholders import FillContext, fill
from veyltrace_contracts import models
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_json, sha256_text_lf
from veyltrace_llm.client import JsonReply, LLMClient
from veyltrace_llm.errors import ProviderError
from veyltrace_llm.request import Message

__all__ = ["PROMPTS", "PURPOSE", "Narration", "NarrationSettings", "narrate", "narration_settings", "schema"]

#: The cassette purpose of every narration call, the repair included (10 §3.2 step 3).
PURPOSE: Final = "causivra.narrate"
PROMPTS: Final = ("prompts/system.md", "prompts/narrate.md", "prompts/repair.md")
_PACKAGE: Final = Path(__file__).parent
#: Fixed schema limits (10 §3.2 step 2); a sentence's text limit is the checker's `max_chars` (C8).
MIN_SENTENCES: Final = 2
MAX_CITES: Final = 4


@dataclass(frozen=True)
class NarrationSettings:
    """`narration.*` of config/causivra.yaml (10 §4) that the call loop reads."""

    max_sentences: int
    max_attempts: int
    budget_ms: float


@dataclass(frozen=True)
class Narration:
    """The narrated summary (None → template prose) and the card's `narrator` block (03 §11.1)."""

    summary: list[dict[str, Any]] | None
    narrator: dict[str, Any]
    prompts: tuple[tuple[str, str], ...]
    schema_sha256: str


def _at_least(value: object, low: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= low else None


def narration_settings(section: Mapping[str, Any]) -> NarrationSettings:
    raw: object = section.get("narration")
    narration: Mapping[str, object] = cast(Mapping[str, object], raw) if isinstance(raw, Mapping) else {}
    sentences = _at_least(narration.get("max_sentences"), MIN_SENTENCES)
    attempts = _at_least(narration.get("max_attempts"), 1)
    budget = narration.get("budget_ms")
    if sentences is None or attempts is None:
        raise ConfigError(
            f"causivra.narration: max_sentences ≥ {MIN_SENTENCES} and max_attempts ≥ 1 must be ints"
        )
    if isinstance(budget, bool) or not isinstance(budget, int | float) or budget <= 0:
        raise ConfigError(f"causivra.narration.budget_ms must be a positive number, got {budget!r}")
    return NarrationSettings(sentences, attempts, float(budget))


def _read(name: str) -> str:
    return textio.read_text(_PACKAGE / name).replace("\r\n", "\n").strip("\n")


def schema(atom_ids: Sequence[str], max_sentences: int, max_chars: int) -> dict[str, Any]:
    """The per-case reply schema of 10 §3.2 step 2; cites are the evidence table's atoms."""
    sentence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "cites"],
        "properties": {
            "text": {"type": "string", "maxLength": max_chars},
            "cites": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CITES,
                "items": {"enum": sorted(atom_ids)},
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["sentences"],
        "properties": {
            "sentences": {
                "type": "array",
                "minItems": MIN_SENTENCES,
                "maxItems": max_sentences,
                "items": sentence,
            }
        },
    }


def _verdict_lines(verdict: models.Verdict, ctx: FillContext, path: Sequence[str]) -> tuple[str, list[str]]:
    """The verdict part of the input, with roles as placeholders, and the placeholders it allows."""
    allowed = ["{STATUS}", "{CONF.level}", "{CONF.set_size}", "{CONF.margin}"]
    lines = [f"Status: {verdict.status}", f"Confidence: {ctx.conf_level}; candidate set: {{CONF.set_size}}"]
    if ctx.root_service is None:
        lines.append("Root: none")
    else:
        lines.append(
            "Root: {ROOT}, fault class {ROOT.fault_class}, indicator {ROOT.indicator}, mode {ROOT.mode}"
        )
        allowed += ["{ROOT}", "{ROOT.component}", "{ROOT.fault_class}", "{ROOT.indicator}", "{ROOT.mode}"]
        leader = next((r for r in verdict.ranked if r.service == ctx.root_service), None)
        trials = ", ".join(f"{t.id} {t.result}" for t in leader.trials) if leader else ""
        lines.append(f"Root trials: {trials or 'none'}")
    if ctx.runner_up is not None:
        lines.append("Runner-up: {RUNNER_UP}, fault class {RUNNER_UP.fault_class}")
        allowed += ["{RUNNER_UP}", "{RUNNER_UP.fault_class}", "{RUNNER_UP.indicator}"]
    if path:
        lines.append("Path: " + " -> ".join(f"{{SVC:{node}}}" for node in path))
    if ctx.onset_ns is not None:
        allowed.append("{ONSET}")
    return "\n".join(lines), allowed


def _messages(
    verdict: models.Verdict,
    ctx: FillContext,
    kinds: Mapping[str, str],
    path: Sequence[str],
    settings: NarrationSettings,
    checker: CheckerSettings,
) -> tuple[Message, Message]:
    """System and user messages (10 §3.2 step 1): no atom value is shown."""
    text, allowed = _verdict_lines(verdict, ctx, path)
    rows = [
        f"{a} | {atom.label} | {kinds.get(a, '')} | {atom.unit or ''}"
        for a, atom in sorted(ctx.table.items())
    ]
    user = Template(_read(PROMPTS[1])).substitute(
        verdict=text,
        evidence="\n".join(rows) or "(empty)",
        placeholders=", ".join(allowed),
        max_sentences=settings.max_sentences,
        max_words=checker.max_words,
    )
    return Message("system", _read(PROMPTS[0])), Message("user", user)


def _problems(
    reply: JsonReply, ctx: FillContext, entities: frozenset[str], checker: CheckerSettings, max_sentences: int
) -> tuple[list[dict[str, Any]], list[str], int]:
    """The reply's sentences, its problems for the repair prompt, and how many sentences failed."""
    value: object = reply.value
    raw = cast(Mapping[str, object], value).get("sentences") if isinstance(value, Mapping) else None
    items = cast(list[object], raw) if isinstance(raw, list) else None
    if items is None or not MIN_SENTENCES <= len(items) <= max_sentences:
        why = reply.parse_error or f"expected an object with {MIN_SENTENCES} to {max_sentences} sentences"
        return [], [f"reply: {why}"], 0
    sentences: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, item in enumerate(items, start=1):
        empty: Mapping[str, object] = {}
        fields = cast(Mapping[str, object], item) if isinstance(item, Mapping) else empty
        text, cites = fields.get("text"), fields.get("cites")
        if not isinstance(text, str) or not isinstance(cites, list):
            problems.append(f"sentence {i}: not an object with text and cites")
            continue
        cite_list = [str(c) for c in cast(list[object], cites)]
        found: Finding | None = check_sentence(text, cite_list, ctx, entities, checker)
        if found is not None:
            problems.append(f"sentence {i}: {found.rule} at {found.token!r}: {found.detail}")
            continue
        sentences.append({"text": text, "cites": cite_list})
    return sentences, problems, len(problems)


def narrate(
    *,
    verdict: models.Verdict,
    ctx: FillContext,
    kinds: Mapping[str, str],
    path: Sequence[str],
    entities: frozenset[str],
    client: LLMClient,
    params: Mapping[str, Any],
    settings: NarrationSettings,
    checker: CheckerSettings,
) -> Narration:
    """Narrate the summary (10 §3.2 steps 3–6). `params` are the sampler parameters with the seed."""
    reply_schema = schema(list(ctx.table), settings.max_sentences, checker.max_chars)
    messages: Sequence[Message] = _messages(verdict, ctx, kinds, path, settings, checker)
    attempts, failures, latency = 0, 0, 0.0
    summary: list[dict[str, Any]] | None = None
    while attempts < settings.max_attempts:
        attempts += 1
        try:
            reply = client.call_json(PURPOSE, messages, reply_schema, params)
        except ProviderError:
            break
        latency += reply.completion.latency_ms
        if latency > settings.budget_ms:  # 10 §6: budget exceeded → stop, template prose
            break
        sentences, problems, failed = _problems(reply, ctx, entities, checker, settings.max_sentences)
        failures += failed
        if not problems:
            summary = [{"text": fill(s["text"], s["cites"], ctx), "cites": s["cites"]} for s in sentences]
            break
        errors = "\n".join(f"- {p}" for p in problems)
        repair = Template(_read(PROMPTS[2])).substitute(errors=errors)
        content = reply.completion.content or ""
        messages = (*messages, Message("assistant", content), Message("user", repair))
    narrator = {
        "path": "llm" if summary is not None else "template",
        "model": client.settings.model.name if summary is not None else None,
        "attempts": attempts,
        "checker_failures": failures,
    }
    prompts = tuple((name, sha256_text_lf(_PACKAGE / name)) for name in PROMPTS)
    return Narration(summary, narrator, prompts, sha256_json(reply_schema))
