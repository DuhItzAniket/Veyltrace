"""Check a parsed model reply and keep what is valid (08 §3.2 steps 4 and 6, §3.4).

A provider may ignore the schema (FakeProvider, an OpenAI-compatible server), so every enum and limit
is checked again. Each failure becomes a `Problem` a repair turn can quote. The same pass is the
salvage: an invalid claim is dropped, then a proposal with an invalid hypothesis or no valid claim.
A threshold is only a request; FaultLoom's `validate()` decides whether a claim can be evaluated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from veyltrace_faultloom.predicates import LIBRARY, ArgValue
from veyltrace_faultloom.validation import CaseDomain, Rejection, validate
from veyltrace_relentra.schema import (
    ASK_KINDS,
    EMPTY,
    MAX_ASK_TARGET,
    MAX_ASK_WHY,
    MAX_ASKS,
    MAX_CITES,
    MAX_RATIONALE,
    MAX_TRIALS,
    CaseEnums,
)
from veyltrace_relentra.settings import BriefSettings

__all__ = ["CheckedAsk", "CheckedClaim", "CheckedProposal", "CheckedReply", "Drop", "Problem", "check_reply"]

_CLAIM_KEYS: Final = frozenset({"predicate", "signal", "other", "x", "cites"})
_PROPOSAL_KEYS: Final = frozenset(
    {"service", "fault_class", "indicator", "claims", "requested_trials", "rationale"}
)
_ASK_KEYS: Final = frozenset({"kind", "target", "why"})
_REPLY_KEYS: Final = frozenset({"proposals", "asks"})


@dataclass(frozen=True)
class Problem:
    """One error, located in the reply: what the repair turn lists (08 §3.2 step 5)."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class Drop:
    """A part salvage removed; the engine writes it as a `drop_claim` or `drop_proposal` trace line."""

    kind: Literal["drop_claim", "drop_proposal"]
    detail: str


@dataclass(frozen=True)
class CheckedClaim:
    predicate: str
    args: Mapping[str, ArgValue]
    cites: tuple[str, ...]


@dataclass(frozen=True)
class CheckedProposal:
    service: str
    fault_class: str
    indicator: str | None
    claims: tuple[CheckedClaim, ...]
    requested_trials: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class CheckedAsk:
    kind: str
    target: str
    why: str


@dataclass(frozen=True)
class CheckedReply:
    """The valid parts of a reply. `problems` empty means the reply was fully valid."""

    proposals: tuple[CheckedProposal, ...]
    asks: tuple[CheckedAsk, ...]
    problems: tuple[Problem, ...]
    drops: tuple[Drop, ...]


def _keys_problem(item: Mapping[str, Any], keys: frozenset[str], path: str) -> Problem | None:
    if not set(item) ^ keys:
        return None
    missing, extra = sorted(keys - set(item)), sorted(map(str, set(item) - keys))
    return Problem(path, f"missing keys {missing}, unknown keys {extra}")


def _members(values: list[Any], allowed: Sequence[str]) -> bool:
    """Every item of the list is an allowed string; unhashable items are simply not members."""
    return all(isinstance(v, str) and v in allowed for v in values)


def _finite(x: object) -> bool:
    """A number a float can hold: JSON integers are unbounded, so a huge one is not."""
    if isinstance(x, bool) or not isinstance(x, int | float):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


def _object(
    value: object, keys: frozenset[str], path: str, problems: list[Problem]
) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        problems.append(Problem(path, "must be an object"))
        return None
    item = cast("Mapping[str, Any]", value)
    problem = _keys_problem(item, keys, path)
    if problem is not None:
        problems.append(problem)
        return None
    return item


def _items(value: object, limit: int, path: str, problems: list[Problem]) -> Sequence[Any]:
    """A list, cut to `limit` in model order; going over is a problem, the rest is still usable."""
    if not isinstance(value, list):
        problems.append(Problem(path, "must be a list"))
        return ()
    items = cast("list[Any]", value)
    if len(items) > limit:
        problems.append(Problem(path, f"has {len(items)} items, at most {limit} are allowed"))
    return items[:limit]


def _arguments(predicate: str, item: Mapping[str, Any], path: str) -> dict[str, ArgValue] | Problem:
    """The slot mapping of 08 §3.4: signal params from `signal`, service params from `other`,
    numbers from `x` (integers rounded)."""
    args: dict[str, ArgValue] = {}
    for param in LIBRARY[predicate].params:
        if param.type in ("signal", "service"):
            slot = "signal" if param.type == "signal" else "other"
            if item[slot] == EMPTY:
                return Problem(path, f"predicate {predicate} needs '{slot}'")
            args[param.name] = item[slot]
        else:
            args[param.name] = round(item["x"]) if param.type == "int" else item["x"]
    return args


def _claim(
    value: object, path: str, enums: CaseEnums, domain: CaseDomain, problems: list[Problem]
) -> CheckedClaim | None:
    item = _object(value, _CLAIM_KEYS, path, problems)
    if item is None:
        return None
    x, cites = item["x"], item["cites"]
    found: Problem | None = None
    if item["predicate"] not in enums.predicates:
        found = Problem(path, f"unknown predicate {item['predicate']!r}")
    elif item["signal"] not in (*enums.signals, EMPTY):
        found = Problem(path, f"unknown signal {item['signal']!r}")
    elif item["other"] not in (*enums.nodes, EMPTY):
        found = Problem(path, f"unknown service {item['other']!r}")
    elif not _finite(x):
        found = Problem(path, f"x must be a finite number, got {x!r}")
    elif not isinstance(cites, list) or len(cast("list[Any]", cites)) > MAX_CITES:
        found = Problem(path, f"cites must be a list of at most {MAX_CITES} atom ids")
    elif not _members(cast("list[Any]", cites), enums.atom_ids):
        found = Problem(path, "cites names an atom that is not on the evidence cards")
    if found is not None:
        problems.append(found)
        return None
    args = _arguments(item["predicate"], item, path)
    if isinstance(args, Problem):
        problems.append(args)
        return None
    checked = validate(item["predicate"], args, domain)
    if isinstance(checked, Rejection):
        problems.append(Problem(path, f"{checked.reason}: {checked.detail}"))
        return None
    return CheckedClaim(item["predicate"], dict(checked.args), tuple(cast("list[str]", cites)))


def _hypothesis_problem(item: Mapping[str, Any], path: str, enums: CaseEnums) -> Problem | None:
    trials, rationale = item["requested_trials"], item["rationale"]
    if item["service"] not in enums.nodes:
        return Problem(path, f"unknown service {item['service']!r}")
    if item["fault_class"] not in enums.fault_classes:
        return Problem(path, f"unknown fault_class {item['fault_class']!r}")
    if item["indicator"] not in (*enums.indicators, EMPTY):
        return Problem(path, f"unknown indicator {item['indicator']!r}")
    if not isinstance(trials, list) or len(cast("list[Any]", trials)) > MAX_TRIALS:
        return Problem(path, f"requested_trials must be a list of at most {MAX_TRIALS} trials")
    if not _members(cast("list[Any]", trials), enums.trials):
        return Problem(path, "requested_trials names an unknown trial")
    if not isinstance(rationale, str) or len(rationale) > MAX_RATIONALE:
        return Problem(path, f"rationale must be text of at most {MAX_RATIONALE} characters")
    return None


def _proposal(
    value: object,
    path: str,
    enums: CaseEnums,
    domain: CaseDomain,
    settings: BriefSettings,
    problems: list[Problem],
    drops: list[Drop],
) -> CheckedProposal | None:
    start = len(problems)
    item = _object(value, _PROPOSAL_KEYS, path, problems)
    found = None if item is None else _hypothesis_problem(item, path, enums)
    if found is not None:
        problems.append(found)
    if item is None or found is not None:
        drops.append(Drop("drop_proposal", str(problems[start])))
        return None
    claims: list[CheckedClaim] = []
    limit = settings.max_claims_per_proposal
    for i, raw in enumerate(_items(item["claims"], limit, f"{path}.claims", problems)):
        before = len(problems)
        claim = _claim(raw, f"{path}.claims[{i}]", enums, domain, problems)
        if claim is None:
            drops.append(Drop("drop_claim", str(problems[before])))
        else:
            claims.append(claim)
    if not claims:
        problems.append(Problem(path, "has no valid claim"))
        drops.append(Drop("drop_proposal", str(problems[-1])))
        return None
    indicator = None if item["indicator"] == EMPTY else str(item["indicator"])
    trials = tuple(cast("list[str]", item["requested_trials"]))
    return CheckedProposal(
        item["service"], item["fault_class"], indicator, tuple(claims), trials, item["rationale"]
    )


def _ask(value: object, path: str, problems: list[Problem]) -> CheckedAsk | None:
    item = _object(value, _ASK_KEYS, path, problems)
    if item is None:
        return None
    target, why = item["target"], item["why"]
    if item["kind"] not in ASK_KINDS:
        problems.append(Problem(path, f"unknown kind {item['kind']!r}"))
    elif not isinstance(target, str) or len(target) > MAX_ASK_TARGET:
        problems.append(Problem(path, f"target must be text of at most {MAX_ASK_TARGET} characters"))
    elif not isinstance(why, str) or len(why) > MAX_ASK_WHY:
        problems.append(Problem(path, f"why must be text of at most {MAX_ASK_WHY} characters"))
    else:
        return CheckedAsk(item["kind"], target, why)
    return None


def check_reply(value: object, enums: CaseEnums, domain: CaseDomain, settings: BriefSettings) -> CheckedReply:
    """Check parsed JSON `value`. A value that is not an object salvages nothing; an object with a
    missing or unknown top-level key is a problem, and the parts it does have are still used."""
    problems: list[Problem] = []
    drops: list[Drop] = []
    if not isinstance(value, Mapping):
        return CheckedReply((), (), (Problem("reply", "must be an object"),), ())
    reply = cast("Mapping[str, Any]", value)
    top = _keys_problem(reply, _REPLY_KEYS, "reply")
    if top is not None:
        problems.append(top)
    proposals: list[CheckedProposal] = []
    for i, item in enumerate(
        _items(reply.get("proposals", []), settings.max_proposals, "proposals", problems)
    ):
        checked = _proposal(item, f"proposals[{i}]", enums, domain, settings, problems, drops)
        if checked is not None:
            proposals.append(checked)
    asks: list[CheckedAsk] = []
    for i, item in enumerate(_items(reply.get("asks", []), MAX_ASKS, "asks", problems)):
        ask = _ask(item, f"asks[{i}]", problems)
        if ask is not None:
            asks.append(ask)
    return CheckedReply(tuple(proposals), tuple(asks), tuple(problems), tuple(drops))
