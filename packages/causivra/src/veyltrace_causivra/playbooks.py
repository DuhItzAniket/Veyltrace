"""Deterministic playbooks: load `playbooks.yaml`, pick the playbooks for a verdict, fill the steps
(10 §3.6).

Why a data file: the step texts are advice a reviewer edits, not logic. They live next to the code
(package data, so an installed wheel ships them), are checked on load (ids, no digits, only the
`{ROOT}` and `{ROOT.component}` placeholders) and are filled by the same filler as all card prose.
A step may be tied to an ask kind (`{ask_kind, text}`): it is advice about that kind of ask, so it
is shown only when the verdict carries one (PB-INCONC-01, since #204 added `context` asks). A step
written as `{when: candidate_set, text}` is about the members of the candidate set, so it is shown
only when the set is non-empty.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final, cast, get_args

from veyltrace_causivra.placeholders import FillContext, fill, placeholders
from veyltrace_contracts import models
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.yaml12 import load_yaml_bytes

__all__ = ["PLAYBOOKS_FILE", "Playbook", "load_playbooks", "next_steps", "select"]

PLAYBOOKS_FILE: Final = Path(__file__).with_name("playbooks.yaml")
#: card.next_steps[].playbook_id pattern (03 §11.1).
_ID_RE: Final = re.compile(r"PB-[A-Z]+-[0-9]{2}")
_STEP_PLACEHOLDERS: Final = frozenset({"ROOT", "ROOT.component"})
NO_FAULT_ID: Final = "PB-NOFAULT-01"
INCONCLUSIVE_ID: Final = "PB-INCONC-01"
UNKNOWN_ID: Final = "PB-UNK-01"
CHANGE_ID: Final = "PB-CHANGE-01"
CHANGE_MODE: Final = "change"
CHANGE_TRIAL: Final = "T6"
_ASK_KINDS: Final = frozenset(get_args(models.AskKind))
_TIED_KEYS: Final = frozenset({"ask_kind", "text"})
_WHEN_KEYS: Final = frozenset({"when", "text"})
#: Conditions a `{when, text}` step may name: `candidate_set` = the verdict's set is non-empty.
NONEMPTY_SET: Final = "candidate_set"
_WHENS: Final = frozenset({NONEMPTY_SET})


@dataclass(frozen=True)
class Playbook:
    """`steps` are the step texts in file order; `ask_kinds[i]` is the ask kind step i is tied to and
    `whens[i]` the condition it needs; both None for a step that is always shown."""

    id: str
    fault_classes: tuple[str, ...]
    steps: tuple[str, ...]
    ask_kinds: tuple[str | None, ...]
    whens: tuple[str | None, ...]


def _step(raw: object, pb_id: str, source: str) -> tuple[str, str | None, str | None]:
    """One step entry as (text, ask kind, condition): a text, a mapping `{ask_kind, text}` tying the
    text to an ask kind, or `{when, text}` naming the condition it needs."""
    if not isinstance(raw, Mapping):
        return (raw if isinstance(raw, str) else ""), None, None  # the caller rejects a non-text
    tied = cast(Mapping[str, Any], raw)
    text = tied.get("text")
    when, kind = tied.get("when"), tied.get("ask_kind")
    if frozenset(tied) == _WHEN_KEYS and isinstance(text, str) and isinstance(when, str) and when in _WHENS:
        return text, None, when
    known = isinstance(kind, str) and kind in _ASK_KINDS
    if frozenset(tied) != _TIED_KEYS or not known or not isinstance(text, str):
        raise ConfigError(
            f"{source}: {pb_id} step {raw!r} must be a text, {{ask_kind, text}} with ask_kind in "
            f"{sorted(_ASK_KINDS)}, or {{when, text}} with when in {sorted(_WHENS)}"
        )
    return text, cast(str, kind), None


def _parse(raw: object, source: str) -> dict[str, Playbook]:
    entries = cast(Mapping[str, Any], raw).get("playbooks") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{source}: needs a non-empty `playbooks` list")
    out: dict[str, Playbook] = {}
    for entry in cast(list[object], entries):
        if not isinstance(entry, Mapping):
            raise ConfigError(f"{source}: playbook entry {entry!r} must be a mapping")
        entry = cast(Mapping[str, Any], entry)
        pb_id, classes, steps = entry.get("id"), entry.get("fault_classes"), entry.get("steps")
        if not isinstance(pb_id, str) or _ID_RE.fullmatch(pb_id) is None or pb_id in out:
            raise ConfigError(f"{source}: bad or duplicate playbook id {pb_id!r}")
        if not isinstance(classes, list) or not isinstance(steps, list) or not steps:
            raise ConfigError(f"{source}: {pb_id} needs fault_classes and a non-empty steps list")
        raws = cast(list[object], steps)
        parsed = [_step(raw, pb_id, source) for raw in raws]
        for (text, _, _), raw in zip(parsed, raws, strict=True):
            if not text or re.search(r"[0-9]", text):
                raise ConfigError(f"{source}: {pb_id} step {raw!r} must be text without digits")
            if not set(placeholders(text)) <= _STEP_PLACEHOLDERS:
                raise ConfigError(f"{source}: {pb_id} steps may use only {{ROOT}} and {{ROOT.component}}")
        kinds = [k for _, k, _ in parsed if k is not None]
        if len(kinds) != len(set(kinds)):
            raise ConfigError(f"{source}: {pb_id} ties more than one step to the same ask kind")
        out[pb_id] = Playbook(
            pb_id,
            tuple(str(c) for c in cast(list[object], classes)),
            tuple(t for t, _, _ in parsed),
            tuple(k for _, k, _ in parsed),
            tuple(w for _, _, w in parsed),
        )
    for required in (NO_FAULT_ID, INCONCLUSIVE_ID, UNKNOWN_ID, CHANGE_ID):
        if required not in out:
            raise ConfigError(f"{source}: missing playbook {required}")
    return out


@cache
def load_playbooks(path: Path = PLAYBOOKS_FILE) -> Mapping[str, Playbook]:
    """The checked playbooks of `path` (cached per path)."""
    return _parse(load_yaml_bytes(textio.read_bytes(path), source=path.name), path.name)


def select(verdict: models.Verdict, playbooks: Mapping[str, Playbook]) -> list[str]:
    """Playbook ids for the verdict, in the 10 §3.6 order."""
    if verdict.status == "NO_FAULT":
        return [NO_FAULT_ID]
    root = verdict.root
    if verdict.status == "INCONCLUSIVE" or root is None:
        return [INCONCLUSIVE_ID]
    by_class = next((p.id for p in playbooks.values() if root.fault_class in p.fault_classes), UNKNOWN_ID)
    ranked = next((r for r in verdict.ranked if r.service == root.service), None)
    passed_t6 = ranked is not None and any(t.id == CHANGE_TRIAL and t.result == "pass" for t in ranked.trials)
    return [by_class, CHANGE_ID] if root.mode == CHANGE_MODE or passed_t6 else [by_class]


def _shown(playbook: Playbook, kinds: Sequence[str], has_set: bool) -> list[str]:
    """The step texts shown for a verdict whose asks have `kinds` (each once, in first-occurrence
    order) and whose candidate set is non-empty when `has_set`. Untied steps keep file order; a
    `candidate_set` step is dropped for an empty set (no placeholder line). Tied steps are shown only
    for a kind in `kinds`, as one block at the first tied step's place and in `kinds` order, so the
    advice follows the asks.
    """
    tied = {k: t for t, k in zip(playbook.steps, playbook.ask_kinds, strict=True) if k is not None}
    shown: list[str] = []
    block_placed = False
    for text, kind, when in zip(playbook.steps, playbook.ask_kinds, playbook.whens, strict=True):
        if when == NONEMPTY_SET and not has_set:
            continue
        if kind is None:
            shown.append(text)
        elif not block_placed:
            shown += [tied[k] for k in kinds if k in tied]
            block_placed = True
    return shown


def next_steps(
    verdict: models.Verdict, ctx: FillContext, playbooks: Mapping[str, Playbook]
) -> list[dict[str, str]]:
    """card.next_steps: each selected playbook's shown steps (`_shown`), filled."""
    selected: Sequence[str] = select(verdict, playbooks)
    kinds = list(dict.fromkeys(ask.kind for ask in verdict.asks))
    return [
        {"text": fill(step, [], ctx), "playbook_id": pb_id}
        for pb_id in selected
        for step in _shown(playbooks[pb_id], kinds, bool(verdict.candidate_set))
    ]
