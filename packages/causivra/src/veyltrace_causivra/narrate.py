"""LLM narration of the card summary (10 §3.2): at most two calls, then template prose.

Why the model sees no values: it writes `{E<atom>.value}` and code fills it, so every digit on the
card comes from an atom. Each sentence passes the claim checker before filling; one repair names
each failing sentence's rule and token. A second failure, a provider error or the latency budget
(recorded latency only, so replay reproduces it) gives template prose, as with AI off. So does a
cassette miss in replay: the card then differs from the record, which replay reports as exit 6.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Final, cast

from veyltrace_causivra.checker import CheckerSettings, Finding, check_sentence
from veyltrace_causivra.fmt import format_number
from veyltrace_causivra.placeholders import FillContext, fill
from veyltrace_contracts import models
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_json, sha256_text_lf
from veyltrace_core.rng import seed_int
from veyltrace_llm.cassette import CassetteMiss
from veyltrace_llm.client import JsonReply, LLMClient
from veyltrace_llm.errors import ProviderError
from veyltrace_llm.request import Message

__all__ = [
    "PROMPTS",
    "PURPOSE",
    "Narration",
    "NarrationSettings",
    "narrate",
    "narration_settings",
    "sampler_params",
    "schema",
]

#: The cassette purpose of every narration call, the repair included (10 §3.2 step 3).
PURPOSE: Final = "causivra.narrate"
PROMPTS: Final = ("prompts/system.md", "prompts/narrate.md", "prompts/repair.md")
_PACKAGE: Final = Path(__file__).parent
#: Relentra's sampler keys sent as they are (08 §3.8); the seed and max_tokens are Causivra's own.
SAMPLER_KEYS: Final = ("temperature", "top_p", "top_k", "presence_penalty", "thinking")
#: Fixed schema limits (10 §3.2 step 2); a sentence's text limit is the checker's `max_chars` (C8).
MIN_SENTENCES: Final = 2
MAX_CITES: Final = 4


@dataclass(frozen=True)
class NarrationSettings:
    """`narration.*` of config/causivra.yaml (10 §4); `scope` must be `summary` in v0.1."""

    enabled: bool
    max_sentences: int
    max_attempts: int
    max_tokens: int
    budget_ms: float
    show_values: bool


@dataclass(frozen=True)
class Narration:
    """The narrated summary (None → template prose) and the card's `narrator` block (03 §11.1).

    `cassette_miss` marks a replay that asked something unrecorded (10 §6), for the card step's log.
    """

    summary: list[dict[str, Any]] | None
    narrator: dict[str, Any]
    prompts: tuple[tuple[str, str], ...]
    schema_sha256: str
    cassette_miss: bool = False


def _at_least(value: object, low: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= low else None


def narration_settings(section: Mapping[str, Any]) -> NarrationSettings:
    raw: object = section.get("narration")
    narration: Mapping[str, object] = cast(Mapping[str, object], raw) if isinstance(raw, Mapping) else {}
    sentences = _at_least(narration.get("max_sentences"), MIN_SENTENCES)
    attempts = _at_least(narration.get("max_attempts"), 1)
    tokens = _at_least(narration.get("max_tokens"), 1)
    budget = narration.get("budget_ms")
    enabled, show = narration.get("enabled"), narration.get("show_values")
    if sentences is None or attempts is None or tokens is None:
        raise ConfigError(
            f"causivra.narration: max_sentences ≥ {MIN_SENTENCES}, max_attempts ≥ 1 and max_tokens ≥ 1"
            " must be ints"
        )
    if isinstance(budget, bool) or not isinstance(budget, int | float) or budget <= 0:
        raise ConfigError(f"causivra.narration.budget_ms must be a positive number, got {budget!r}")
    if not isinstance(enabled, bool) or not isinstance(show, bool):
        raise ConfigError("causivra.narration.enabled and show_values must be bools")
    if narration.get("scope") != "summary":
        raise ConfigError(
            f"causivra.narration.scope must be 'summary' in v0.1, got {narration.get('scope')!r}"
        )
    return NarrationSettings(enabled, sentences, attempts, tokens, float(budget), show)


def sampler_params(relentra: Mapping[str, Any], case_id: str, max_tokens: int) -> dict[str, Any]:
    """The seven sampler parameters (03 §9.1): Relentra's values, seed `causivra.seed/<i>` (10 §3.2)."""
    raw: object = relentra.get("sampler")
    sampler: Mapping[str, object] = cast(Mapping[str, object], raw) if isinstance(raw, Mapping) else {}
    index = _at_least(sampler.get("seed_index"), 0)
    missing = [k for k in SAMPLER_KEYS if k not in sampler]
    if missing or index is None:
        raise ConfigError(f"relentra.sampler needs {missing or ['seed_index']} for the narration call")
    params: dict[str, Any] = {k: sampler[k] for k in SAMPLER_KEYS}
    return params | {"seed": seed_int(case_id, f"causivra.seed/{index}"), "max_tokens": max_tokens}


def _read(name: str) -> str:
    return textio.read_text(_PACKAGE / name).replace("\r\n", "\n").strip("\n")


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(properties),
        "properties": properties}  # fmt: skip


def schema(atom_ids: Sequence[str], max_sentences: int, max_chars: int) -> dict[str, Any]:
    """The per-case reply schema of 10 §3.2 step 2; cites are the evidence table's atoms."""
    cites = {"type": "array", "minItems": 1, "maxItems": MAX_CITES, "items": {"enum": sorted(atom_ids)}}
    sentence = _object({"text": {"type": "string", "maxLength": max_chars}, "cites": cites})
    sentences = {"type": "array", "minItems": MIN_SENTENCES, "maxItems": max_sentences, "items": sentence}
    return _object({"sentences": sentences})


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
    verdict: models.Verdict, ctx: FillContext, kinds: Mapping[str, str], path: Sequence[str],
    settings: NarrationSettings, checker: CheckerSettings,
) -> tuple[Message, ...]:  # fmt: skip
    """System and user messages (10 §3.2 step 1): no atom value is shown unless `show_values`."""
    text, allowed = _verdict_lines(verdict, ctx, path)
    rows = [  # values only in the show_values ablation (10 §9)
        f"{a} | {t.label} | {kinds.get(a, '')} | {t.unit or ''}"
        + (f" | {format_number(t.value, ctx.sig_digits)}" if settings.show_values else "")
        for a, t in sorted(ctx.table.items())
    ]
    user = Template(_read(PROMPTS[1])).substitute(
        atom=min(ctx.table), columns=" | value" if settings.show_values else "", verdict=text,
        evidence="\n".join(rows), placeholders=", ".join(allowed),
        max_sentences=settings.max_sentences, max_words=checker.max_words,
    )  # fmt: skip
    return Message("system", _read(PROMPTS[0])), Message("user", user)


def _problems(
    reply: JsonReply, ctx: FillContext, entities: frozenset[str], checker: CheckerSettings, max_sentences: int
) -> tuple[list[dict[str, Any]], list[str], int]:
    """The reply's sentences, its problems for the repair prompt, and how many the checker rejected."""
    value: object = reply.value
    raw = cast(Mapping[str, object], value).get("sentences") if isinstance(value, Mapping) else None
    items = cast(list[object], raw) if isinstance(raw, list) else None
    if items is None or not MIN_SENTENCES <= len(items) <= max_sentences:
        why = reply.parse_error or f"expected an object with {MIN_SENTENCES} to {max_sentences} sentences"
        return [], [f"reply: {why}"], 0
    sentences: list[dict[str, Any]] = []
    problems: list[str] = []
    rejected = 0
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
            rejected += 1
            continue
        sentences.append({"text": text, "cites": cite_list})
    return sentences, problems, rejected


def narrate(
    *, verdict: models.Verdict, ctx: FillContext, kinds: Mapping[str, str], path: Sequence[str],
    entities: frozenset[str], client: LLMClient, params: Mapping[str, Any], settings: NarrationSettings,
    checker: CheckerSettings,
) -> Narration:  # fmt: skip
    """Narrate the summary (10 §3.2 steps 3–6). `params` are the sampler parameters with the seed."""
    reply_schema = schema(list(ctx.table), settings.max_sentences, checker.max_chars)
    attempts, failures, latency, missed = 0, 0, 0.0, False
    summary: list[dict[str, Any]] | None = None
    # No atom to cite: no reply can satisfy the schema, so no call is made (template prose).
    empty: tuple[Message, ...] = ()
    messages = _messages(verdict, ctx, kinds, path, settings, checker) if ctx.table else empty
    while messages and attempts < settings.max_attempts:
        attempts += 1
        try:
            reply = client.call_json(PURPOSE, messages, reply_schema, params)
        except CassetteMiss:  # 10 §6: template prose; the card differs, so replay exits 6
            missed = True
            break
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
    return Narration(summary, narrator, prompts, sha256_json(reply_schema), missed)
