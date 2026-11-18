"""The messages of `brief` mode (08 §3.2 steps 2 and 5, §3.5).

Templates are plain files filled with `string.Template`, so they hold no logic and any edit shows up
in `prompt_sha256`. Files are read with CRLF turned into LF, so a Windows checkout renders and hashes
like Linux. The prompt adds no numbers of its own beyond the fused scores of the pool context.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Final

from veyltrace_contracts import models
from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json_str
from veyltrace_core.hashing import sha256_text_lf
from veyltrace_llm.request import Message
from veyltrace_relentra.settings import BriefSettings

__all__ = [
    "FittedPrompt",
    "PromptFiles",
    "estimate_tokens",
    "fit_prompt",
    "load_prompt_files",
    "pool_context",
    "render_messages",
    "repair_messages",
]

_PACKAGE: Final = Path(__file__).parent
_TEMPLATES: Final[tuple[str, ...]] = ("prompts/system.md", "prompts/brief_user.md", "prompts/repair.md")
#: The brief built from the graph: for unknown systems and live snapshots (08 §3.5).
GENERATED_BRIEF: Final = "other"
LIVE_DATASET: Final = "live"
_NO_POOL: Final = "(none)"


def _read(name: str) -> str:
    return textio.read_text(_PACKAGE / name).replace("\r\n", "\n").strip("\n")


@dataclass(frozen=True)
class PromptFiles:
    """The templates and the system brief of one run, with the hashes of the files read."""

    system: str
    user: Template
    repair: Template
    brief: str
    hashes: tuple[tuple[str, str], ...]


def load_prompt_files(
    system: str, dataset: str, nodes: Iterable[str], settings: BriefSettings
) -> PromptFiles:
    """Read the templates and the brief for `system`. With `prompt.include_brief` off the brief is
    empty and no brief file is read (the ablation of 08 §9)."""
    names: list[str] = list(_TEMPLATES)
    brief = ""
    if settings.include_brief:
        stem = GENERATED_BRIEF if dataset == LIVE_DATASET else system
        names.append(f"briefs/{stem}.md")
        brief = _read(names[-1])
        if stem == GENERATED_BRIEF:
            brief = Template(brief).substitute(services=", ".join(sorted(set(nodes))))
    return PromptFiles(
        system=_read(_TEMPLATES[0]),
        user=Template(_read(_TEMPLATES[1])),
        repair=Template(_read(_TEMPLATES[2])),
        brief=brief,
        hashes=tuple((name, sha256_text_lf(_PACKAGE / name)) for name in names),
    )


def pool_context(slate: models.Slate, n: int) -> str:
    """The next `n` services by fused score that are not on the cards (08 §3.5 section 4)."""
    shown = {c.service for c in slate.candidates}
    rest = [s for s in slate.all_scores if s.service not in shown][:n]
    return "\n".join(f"{s.service} fused={s.fused_score:.3g}" for s in rest) or _NO_POOL


def render_messages(
    files: PromptFiles, deck_text: str, pool: str, schema: Mapping[str, Any]
) -> tuple[Message, Message]:
    """The system and user messages of call A, sections in the order of 08 §3.5."""
    user = files.user.substitute(
        brief=files.brief, deck=deck_text.rstrip("\n"), pool=pool, schema=canonical_json_str(dict(schema))
    )
    return Message("system", files.system), Message("user", user)


def estimate_tokens(messages: Iterable[Message], chars_per_token: float) -> int:
    """`ceil(utf8_bytes / prompt.chars_per_token)` over all messages (08 §3.2 step 2)."""
    return math.ceil(sum(len(m.content.encode("utf-8")) for m in messages) / chars_per_token)


@dataclass(frozen=True)
class FittedPrompt:
    messages: tuple[Message, ...]
    k: int
    tokens: int


def fit_prompt(build: Callable[[int], Sequence[Message]], settings: BriefSettings) -> FittedPrompt | None:
    """The messages at the largest `k` from `cards.k` down to `cards.k_min` that fit
    `budget.max_prompt_tokens`, or None when even `k_min` does not fit."""
    for k in range(settings.cards_k, settings.cards_k_min - 1, -1):
        messages = tuple(build(k))
        tokens = estimate_tokens(messages, settings.chars_per_token)
        if tokens <= settings.max_prompt_tokens:
            return FittedPrompt(messages, k, tokens)
    return None


def repair_messages(
    files: PromptFiles, messages: Sequence[Message], output: str, errors: Iterable[object]
) -> tuple[Message, ...]:
    """The same messages plus the model's output and the code-generated errors (08 §3.2 step 5)."""
    listed = "\n".join(f"- {e}" for e in errors)
    return (
        *messages,
        Message("assistant", output),
        Message("user", files.repair.substitute(errors=listed)),
    )
