"""The claim checker (10 §3.4): a narration sentence may state only what its placeholders fill.

Why: the model writes sentences, but every number and entity on the card must come from an
artifact. C1–C3 (grammar, resolvable, cited) are the filler's own rules (`placeholders.fill`). This
module runs them first, then the rules over the text outside placeholders: C4 no raw digits, C5 no
quantity words, C6 no entity names or identifiers, C7 no certainty unless the verdict is CONFIRMED,
C8 one short sentence. The first failing rule is reported at its first offending token, so the
repair prompt (10 §3.2 step 4) can name `(sentence, rule, token)`.

C3's "cites empty" clause applies to LLM sentences only: a template sentence may be uncited when no
citable atom exists (10 §3.5), so callers checking templates pass `require_cites=False`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from veyltrace_causivra.placeholders import FillContext, PlaceholderError, fill
from veyltrace_core.errors import ConfigError

__all__ = ["CheckerSettings", "Finding", "check_sentence", "checker_settings"]

Rule = Literal["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]

_BRACED: Final = re.compile(r"\{[^{}]*\}")
#: A token of the text outside placeholders: split on space and sentence punctuation; `/`, `-` and
#: `_` stay inside, so `HTTP/2`, `end-to-end` and `snake_case` are one token each.
_TOKEN: Final = re.compile(r"[^\s.,;:!?()\[\]\"'\u201c\u201d\u2018\u2019]+")  # with curly quotes
_TERMINATOR: Final = re.compile(r"[.!?]")
_SNAKE_OR_KEBAB: Final = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)+")
_CAMEL: Final = re.compile(r"[a-z][A-Z]")
CONFIRMED: Final = "CONFIRMED"


@dataclass(frozen=True)
class Finding:
    """The first rule a sentence breaks, at its first offending token ("" when no token applies)."""

    rule: Rule
    token: str
    detail: str


@dataclass(frozen=True)
class CheckerSettings:
    """`checker.*` of config/causivra.yaml (10 §4); word lists compare case-insensitively."""

    max_chars: int
    max_words: int
    allowed_digit_tokens: frozenset[str]
    quantity_words: frozenset[str]
    allowed_compound_words: frozenset[str]
    certainty_words: tuple[tuple[str, ...], ...]


def _positive(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"causivra.checker.{key} must be a positive int, got {value!r}")
    return value


def _words(raw: Mapping[str, object], key: str) -> list[str]:
    value = raw.get(key)
    items = cast(Sequence[object], value) if isinstance(value, list | tuple) else None
    if items is None or not items or not all(isinstance(w, str) and w.strip() for w in items):
        raise ConfigError(f"causivra.checker.{key} must be a non-empty list of words, got {value!r}")
    return [str(w) for w in items]


def checker_settings(section: Mapping[str, Any]) -> CheckerSettings:
    """Validate `causivra.checker`; a missing or malformed key is a ConfigError."""
    raw: object = section.get("checker")
    if not isinstance(raw, Mapping):
        raise ConfigError("config/causivra.yaml: missing section checker (10 §4)")
    checker = cast(Mapping[str, object], raw)
    return CheckerSettings(
        max_chars=_positive(checker, "max_chars"),
        max_words=_positive(checker, "max_words"),
        allowed_digit_tokens=frozenset(_words(checker, "allowed_digit_tokens")),
        quantity_words=frozenset(w.lower() for w in _words(checker, "quantity_words")),
        allowed_compound_words=frozenset(w.lower() for w in _words(checker, "allowed_compound_words")),
        certainty_words=tuple(tuple(w.lower().split()) for w in _words(checker, "certainty_words")),
    )


def _placeholder_rules(
    text: str, cites: Sequence[str], ctx: FillContext, require_cites: bool
) -> Finding | None:
    """C1–C3 through the filler; an empty cite list is C3's first clause on the LLM path."""
    try:
        fill(text, cites, ctx)
    except PlaceholderError as exc:
        if not (exc.rule == "C3" and require_cites and not cites):
            return Finding(exc.rule, exc.token, exc.detail)
    if require_cites and not cites:
        return Finding("C3", "", "an LLM sentence must cite at least one atom")
    return None


def _identifier(token: str, settings: CheckerSettings) -> bool:
    """snake/kebab or camel case and not an allowed compound word: C6's identifier shape."""
    lower = token.lower()
    shaped = _SNAKE_OR_KEBAB.fullmatch(lower) is not None or _CAMEL.search(token) is not None
    return shaped and lower not in settings.allowed_compound_words


def _token_rules(
    tokens: list[str], ctx: FillContext, entities: frozenset[str], settings: CheckerSettings
) -> Finding | None:
    """C4–C7, each over every token before the next rule.

    A digit inside an identifier-shaped token (`paymentservice-v2`) is C6's, not C4's: the token
    names an entity, which is what 10 §7's seeded case expects. Such a token is always rejected.
    """
    for token in tokens:
        digit = any(c.isdigit() for c in token)
        if digit and token not in settings.allowed_digit_tokens and not _identifier(token, settings):
            return Finding("C4", token, "raw digits outside placeholders")
    for token in tokens:
        if "%" in token:
            return Finding("C5", "%", "a percent sign outside placeholders")
        if token.lower() in settings.quantity_words:
            return Finding("C5", token, "a quantity word outside placeholders")
    for token in tokens:
        if token.lower() in entities:
            return Finding("C6", token, "an entity named outside a placeholder")
        if _identifier(token, settings):
            return Finding("C6", token, "identifier-shaped token")
    if ctx.status != CONFIRMED:
        lowered = [t.lower() for t in tokens]
        for i in range(len(lowered)):
            for phrase in settings.certainty_words:
                if tuple(lowered[i : i + len(phrase)]) == phrase:
                    return Finding("C7", " ".join(phrase), f"certainty word under {ctx.status}")
    return None


def _shape(text: str, outside: str, settings: CheckerSettings) -> Finding | None:
    """C8 on the raw sentence: length, word count, one terminator, ending in '.'."""
    if len(text) > settings.max_chars:
        return Finding("C8", "", f"more than {settings.max_chars} characters")
    if len(text.split()) > settings.max_words:
        return Finding("C8", "", f"more than {settings.max_words} words")
    terminators = _TERMINATOR.findall(outside)
    if len(terminators) > 1:
        return Finding("C8", terminators[1], "more than one sentence")
    if not text.rstrip().endswith("."):
        return Finding("C8", "", "does not end in '.'")
    return None


def check_sentence(
    text: str,
    cites: Sequence[str],
    ctx: FillContext,
    entities: Iterable[str],
    settings: CheckerSettings,
    *,
    require_cites: bool = True,
) -> Finding | None:
    """The first rule `text` breaks (C1 → C8), or None if the sentence may be filled.

    `entities` is the C6 lexicon: graph nodes, `case_manifest.services` and evidence components.
    """
    found = _placeholder_rules(text, cites, ctx, require_cites)
    if found is not None:
        return found
    outside = _BRACED.sub(" ", text)
    lexicon = frozenset(e.lower() for e in entities)
    return _token_rules(_TOKEN.findall(outside), ctx, lexicon, settings) or _shape(text, outside, settings)
