"""Deterministic card assembly, 10 §3.1 steps 1–3: settings, title, copied verdict fields and the
evidence table, plus the filler context the prose steps use (steps 4–7 are in `sections`).

Why it is all code: the card explains a verdict it must never change (package rule 1), so every
field here is a pure function of run artifacts and config. Status, root, confidence and candidate
set are copied verbatim; prose goes through the placeholder filler, so a name or number on the card
always comes from an artifact. Lists are sorted as 10 §2.2 states.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast, get_args

from veyltrace_causivra.fmt import format_number
from veyltrace_causivra.placeholders import FillContext, RunnerUp, TableAtom
from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError, ContractValidationError

__all__ = [
    "CardSettings",
    "args_of",
    "evidence_table",
    "fill_context",
    "settings_from",
    "table_atoms",
    "title",
]

DOT: Final = "·"  # the title separator of 10 §3.1 step 1
#: Leaders whose trial atoms fill the table when there is no root (10 §3.1 step 3: ranked[0…2]).
NO_ROOT_LEADERS: Final = 3


@dataclass(frozen=True)
class CardSettings:
    """config/causivra.yaml keys of the deterministic card (10 §4), plus Causentra's mandatory set."""

    evidence_max: int
    why_not_max: int
    sig_digits: int
    labels: Mapping[str, str]
    asks: Mapping[str, str]
    mandatory: frozenset[str]


def _positive(section: Mapping[str, Any], dotted: str) -> int:
    node: object = section
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise ConfigError(f"config/causivra.yaml: missing key {dotted}")
        node = cast(Mapping[str, object], node)[part]
    if isinstance(node, bool) or not isinstance(node, int) or node < 1:
        raise ConfigError(f"causivra.{dotted} must be a positive int, got {node!r}")
    return node


def _templates(section: Mapping[str, Any], key: str, required: Iterable[str]) -> dict[str, str]:
    raw: object = section.get(key)
    if not isinstance(raw, Mapping):
        raise ConfigError(f"causivra.{key} must map each kind to a template")
    found = cast(Mapping[str, object], raw)
    missing = sorted(set(required) - set(found))
    if missing or not all(isinstance(v, str) and v for v in found.values()):
        raise ConfigError(f"causivra.{key}: need a non-empty template for every kind; missing {missing}")
    return {k: str(v) for k, v in found.items()}


def settings_from(section: Mapping[str, Any], causentra: Mapping[str, Any]) -> CardSettings:
    """Validate the card keys; `causentra` is that section, read for its `mandatory` list (D-7)."""
    raw: object = causentra.get("mandatory")
    mandatory = list(cast(Sequence[object], raw)) if isinstance(raw, list | tuple) else None
    if mandatory is None or not all(isinstance(t, str) for t in mandatory):
        raise ConfigError(f"causentra.mandatory must be a list of trial ids, got {raw!r}")
    return CardSettings(
        evidence_max=_positive(section, "card.evidence_max"),
        why_not_max=_positive(section, "why_not.max"),
        sig_digits=_positive(section, "format.sig_digits"),
        labels=_templates(section, "labels", get_args(models.AtomKind)),
        asks=_templates(section, "asks", get_args(models.AskKind)),
        mandatory=frozenset(str(t) for t in mandatory),
    )


# --- step 1-2: title and copied fields -------------------------------------------------------------
def title(verdict: models.Verdict) -> str:
    """10 §3.1 step 1."""
    root, status = verdict.root, verdict.status
    if status in ("CONFIRMED", "LIKELY") and root is not None:
        return f"{status} {DOT} {root.service} {DOT} {root.fault_class}"
    if status == "INCONCLUSIVE":
        return f"INCONCLUSIVE {DOT} " + (
            f"leading candidate {root.service}" if root else "no single root cause"
        )
    if status == "NO_FAULT":
        return f"NO_FAULT {DOT} no fault detected in the incident window"
    raise ContractValidationError("verdict", f"status {status} has no root")


# --- step 3: evidence table ----------------------------------------------------------------------
def args_of(row: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(str(row["args_json"])))


def _label(row: Mapping[str, Any], templates: Mapping[str, str], sig_digits: int) -> str:
    args = args_of(row)
    shown = ", ".join(
        f"{k}={format_number(v, sig_digits) if isinstance(v, int | float) and not isinstance(v, bool) else v}"
        for k, v in sorted(args.items())
    )
    fields = {
        **{k: str(v) for k, v in args.items()},
        "candidate": str(row["candidate"]),
        "component": str(row["component"] or ""),
        "window": str(row["window"]),
        "predicate": str(row["predicate"] or ""),
        "args": shown,
    }
    template = templates[str(row["kind"])]
    try:
        return template.format_map(fields)
    except (KeyError, IndexError, ValueError) as exc:
        raise ConfigError(f"causivra.labels.{row['kind']}: {template!r} cannot be filled ({exc!r})") from exc


def _leaders(verdict: models.Verdict) -> list[models.VerdictRanked]:
    return verdict.ranked[:1] if verdict.root is not None else verdict.ranked[:NO_ROOT_LEADERS]


def evidence_table(
    verdict: models.Verdict, rows: Sequence[Mapping[str, Any]], settings: CardSettings
) -> list[dict[str, Any]]:
    """Atoms of the leaders' trials, then their holding claim checks, capped at `evidence_max`
    (trial atoms kept first), sorted by (candidate, kind, atom_id)."""
    by_id = {str(r["atom_id"]): r for r in rows}
    chosen: list[str] = []
    for leader in _leaders(verdict):
        for trial in leader.trials:
            chosen.extend(a for a in trial.atoms if a not in chosen)
    for leader in _leaders(verdict):
        holding = sorted(
            str(r["atom_id"])
            for r in rows
            if r["kind"] == "claim_check" and r["candidate"] == leader.service and r["holds"] is True
        )
        chosen.extend(a for a in holding if a not in chosen)
    missing = [a for a in chosen if a not in by_id]
    if missing:
        raise ContractValidationError("verdict", f"trials cite atoms missing from evidence: {missing[:3]}")
    picked = [by_id[a] for a in chosen[: settings.evidence_max]]
    picked.sort(key=lambda r: (str(r["candidate"]), str(r["kind"]), str(r["atom_id"])))
    return [
        {
            "atom_id": str(r["atom_id"]),
            "label": _label(r, settings.labels, settings.sig_digits),
            "value": r["value"],
            "unit": r["unit"],
        }
        for r in picked
    ]


def table_atoms(
    table: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> dict[str, TableAtom]:
    """The filler's view of the table: label, value and unit from the table, candidate and window
    from the atom row."""
    by_id = {str(r["atom_id"]): r for r in rows}
    return {
        t["atom_id"]: TableAtom(
            t["atom_id"],
            t["label"],
            t["value"],
            t["unit"],
            str(by_id[t["atom_id"]]["candidate"]),
            str(by_id[t["atom_id"]]["window"]),
        )
        for t in table
    }


def fill_context(
    verdict: models.Verdict,
    table: Mapping[str, TableAtom],
    nodes: Iterable[str],
    onsets: models.Onsets | None,
    sig_digits: int,
) -> FillContext:
    root = verdict.root
    runner = verdict.ranked[1] if len(verdict.ranked) > 1 else None  # {RUNNER_UP} needs len(ranked) ≥ 2
    return FillContext(
        status=verdict.status,
        root_service=None if root is None else root.service,
        root_fields={}
        if root is None
        else {
            "component": root.component or root.service,
            "fault_class": root.fault_class,
            "indicator": root.indicator,
            "mode": root.mode,
        },
        runner_up=None if runner is None else RunnerUp(runner.service, runner.fault_class, runner.indicator),
        conf_level=verdict.confidence.level,
        conf_set_size=verdict.confidence.set_size,
        conf_margin=verdict.confidence.margin,
        table=table,
        nodes=frozenset(nodes),
        onset_ns=None if onsets is None else onsets.t_onset_ns,
        sig_digits=sig_digits,
    )
