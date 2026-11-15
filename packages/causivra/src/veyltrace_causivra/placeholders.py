"""The placeholder grammar and filler (10 §3.3) and its validity rules C1–C3 (10 §3.4).

Why: card prose never carries a number or an entity name typed by a writer, human or model. A
sentence names facts by placeholder (`{E3f9a0c41d2.value}`, `{ROOT}`, `{SVC:cart}`, `{CONF.margin}`)
and code fills them from the verdict and the evidence table, through one number formatter. Template
sentences (X-03) and LLM sentences (X-09) go through this same filler.

Rules applied here: C1 syntax (balanced braces, a known placeholder), C2 resolvable (the placeholder
is valid for this card, e.g. `{ROOT}` needs a root), C3 citation (every cite is in the evidence
table, and every atom placeholder's atom is cited). C4–C8 inspect the text outside placeholders and
belong to the claim checker (X-09).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

from veyltrace_causivra.fmt import format_margin, format_number, format_time_utc

__all__ = ["FillContext", "PlaceholderError", "RunnerUp", "TableAtom", "check_cites", "fill", "placeholders"]

Rule = Literal["C1", "C2", "C3"]

_ATOM: Final = re.compile(r"(?P<atom>E[0-9a-f]{10})\.(?P<field>value|unit|label|candidate|window)")
_ROLE: Final = re.compile(
    r"ROOT(?:\.(?P<root>component|fault_class|indicator|mode))?"
    r"|RUNNER_UP(?:\.(?P<ru>fault_class|indicator))?"
    r"|CONF\.(?P<conf>level|set_size|margin)"
    r"|(?P<status>STATUS)|(?P<onset>ONSET)"
)
_SVC: Final = re.compile(r"SVC:(?P<node>[^{}]+)")
_BRACED: Final = re.compile(r"\{([^{}]*)\}")


class PlaceholderError(ValueError):
    """A sentence breaks C1, C2 or C3; `token` is the offending placeholder or cite."""

    def __init__(self, rule: Rule, token: str, detail: str) -> None:
        super().__init__(f"{rule} {token!r}: {detail}")
        self.rule: Rule = rule
        self.token = token
        self.detail = detail


@dataclass(frozen=True)
class TableAtom:
    """One evidence-table row as the filler sees it."""

    atom_id: str
    label: str
    value: float | None
    unit: str | None
    candidate: str
    window: str


@dataclass(frozen=True)
class RunnerUp:
    service: str
    fault_class: str
    indicator: str


@dataclass(frozen=True)
class FillContext:
    """Everything a placeholder may resolve to, taken from the card's own inputs."""

    status: str
    root_service: str | None
    root_fields: Mapping[str, str]  # component (falls back to the service), fault_class, indicator, mode
    runner_up: RunnerUp | None
    conf_level: str
    conf_set_size: int
    conf_margin: float
    table: Mapping[str, TableAtom]
    nodes: frozenset[str]
    onset_ns: int | None
    sig_digits: int


def placeholders(text: str) -> list[str]:
    """The placeholder bodies of `text` in order; C1 if a brace is unbalanced or nested."""
    stripped = _BRACED.sub("", text)
    if "{" in stripped or "}" in stripped:
        raise PlaceholderError("C1", text, "unbalanced or nested braces")
    return _BRACED.findall(text)


@dataclass(frozen=True)
class _Ref:
    """One placeholder that passed C1: the grammar alternative it matched."""

    body: str
    kind: Literal["atom", "role", "svc"]
    match: re.Match[str]


def _parse(body: str) -> _Ref:
    """C1 for one placeholder body."""
    if (m := _ATOM.fullmatch(body)) is not None:
        return _Ref(body, "atom", m)
    if (m := _ROLE.fullmatch(body)) is not None:
        return _Ref(body, "role", m)
    if (m := _SVC.fullmatch(body)) is not None:
        return _Ref(body, "svc", m)
    raise PlaceholderError("C1", body, "not a placeholder of the grammar")


def _check_resolvable(ref: _Ref, ctx: FillContext) -> None:
    """C2: the placeholder's "valid when" condition holds for this card (10 §3.3)."""
    m, body = ref.match, ref.body
    if ref.kind == "atom" and m["atom"] not in ctx.table:
        raise PlaceholderError("C2", body, "atom is not in the evidence table")
    if ref.kind == "svc" and m["node"] not in ctx.nodes:
        raise PlaceholderError("C2", body, "not a graph node")
    if ref.kind != "role":
        return
    if body.startswith("ROOT") and ctx.root_service is None:
        raise PlaceholderError("C2", body, f"no root under {ctx.status}")
    if body.startswith("RUNNER_UP") and ctx.runner_up is None:
        raise PlaceholderError("C2", body, "no runner-up")
    if m["onset"] and ctx.onset_ns is None:
        raise PlaceholderError("C2", body, "onsets.json is absent")


def _value(ref: _Ref, ctx: FillContext) -> str:
    """The text of a placeholder that passed C1–C3."""
    m, body = ref.match, ref.body
    if ref.kind == "atom":
        atom = ctx.table[m["atom"]]
        field = m["field"]
        if field == "value":
            return format_number(atom.value, ctx.sig_digits)
        if field == "unit":
            return atom.unit or ""
        return {"label": atom.label, "candidate": atom.candidate, "window": atom.window}[field]
    if ref.kind == "svc":
        return m["node"]
    if body.startswith("ROOT"):
        return ctx.root_fields[m["root"]] if m["root"] else cast(str, ctx.root_service)
    if body.startswith("RUNNER_UP"):
        runner_up = cast(RunnerUp, ctx.runner_up)
        by_field = {"fault_class": runner_up.fault_class, "indicator": runner_up.indicator}
        return by_field.get(m["ru"] or "", runner_up.service)
    if m["conf"] == "level":
        return ctx.conf_level
    if m["conf"] == "set_size":
        return str(ctx.conf_set_size)
    if m["conf"] == "margin":
        return format_margin(ctx.conf_margin)
    if m["status"]:
        return ctx.status
    return format_time_utc(cast(int, ctx.onset_ns))


def check_cites(cites: Sequence[str], ctx: FillContext) -> None:
    """C3 for the cite list itself: every cite is an atom of the evidence table."""
    for cite in cites:
        if cite not in ctx.table:
            raise PlaceholderError("C3", cite, "cited atom is not in the evidence table")


def fill(text: str, cites: Sequence[str], ctx: FillContext) -> str:
    """`text` with every placeholder replaced.

    Rules run in 10 §3.4 order, each over the whole sentence before the next: C1 on every
    placeholder, then C2 on every placeholder, then C3 (the cite list, then each atom placeholder's
    cite). PlaceholderError reports the first failing rule, at its first offending token, so a
    sentence breaking two rules always reports the earlier rule (X-09 repairs by rule id).
    """
    refs = [_parse(body) for body in placeholders(text)]
    for ref in refs:
        _check_resolvable(ref, ctx)
    check_cites(cites, ctx)
    cited = frozenset(cites)
    for ref in refs:
        if ref.kind == "atom" and ref.match["atom"] not in cited:
            raise PlaceholderError("C3", ref.body, "atom placeholder without a citation of that atom")
    values = iter([_value(ref, ctx) for ref in refs])
    return _BRACED.sub(lambda _m: next(values), text)
