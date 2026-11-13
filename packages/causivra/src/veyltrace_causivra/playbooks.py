"""Deterministic playbooks: load `playbooks.yaml`, pick the playbooks for a verdict, fill the steps
(10 §3.6).

Why a data file: the step texts are advice a reviewer edits, not logic. They live next to the code
(package data, so an installed wheel ships them), are checked on load (ids, no digits, only the
`{ROOT}` and `{ROOT.component}` placeholders) and are filled by the same filler as all card prose.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final, cast

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


@dataclass(frozen=True)
class Playbook:
    id: str
    fault_classes: tuple[str, ...]
    steps: tuple[str, ...]


def _parse(raw: object, source: str) -> dict[str, Playbook]:
    entries = cast(Mapping[str, Any], raw).get("playbooks") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{source}: needs a non-empty `playbooks` list")
    out: dict[str, Playbook] = {}
    for entry in cast(list[Any], entries):
        pb_id, classes, steps = entry.get("id"), entry.get("fault_classes"), entry.get("steps")
        if not isinstance(pb_id, str) or _ID_RE.fullmatch(pb_id) is None or pb_id in out:
            raise ConfigError(f"{source}: bad or duplicate playbook id {pb_id!r}")
        if not isinstance(classes, list) or not isinstance(steps, list) or not steps:
            raise ConfigError(f"{source}: {pb_id} needs fault_classes and a non-empty steps list")
        for step in cast(list[object], steps):
            if not isinstance(step, str) or re.search(r"[0-9]", step):
                raise ConfigError(f"{source}: {pb_id} step {step!r} must be text without digits")
            if not set(placeholders(step)) <= _STEP_PLACEHOLDERS:
                raise ConfigError(f"{source}: {pb_id} steps may use only {{ROOT}} and {{ROOT.component}}")
        out[pb_id] = Playbook(
            pb_id, tuple(str(c) for c in cast(list[object], classes)), tuple(cast(list[str], steps))
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


def next_steps(
    verdict: models.Verdict, ctx: FillContext, playbooks: Mapping[str, Playbook]
) -> list[dict[str, str]]:
    """card.next_steps: each selected playbook's steps in file order, filled."""
    selected: Sequence[str] = select(verdict, playbooks)
    return [
        {"text": fill(step, [], ctx), "playbook_id": pb_id}
        for pb_id in selected
        for step in playbooks[pb_id].steps
    ]
