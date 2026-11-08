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
from typing import Final, Literal

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


def _resolve(body: str, cites: frozenset[str], ctx: FillContext) -> str:
    if (m := _ATOM.fullmatch(body)) is not None:
        atom = ctx.table.get(m["atom"])
        if atom is None:
            raise PlaceholderError("C2", body, "atom is not in the evidence table")
        if atom.atom_id not in cites:
            raise PlaceholderError("C3", body, "atom placeholder without a citation of that atom")
        field = m["field"]
        if field == "value":
            return format_number(atom.value, ctx.sig_digits)
        if field == "unit":
            return atom.unit or ""
        return {"label": atom.label, "candidate": atom.candidate, "window": atom.window}[field]
    if (m := _ROLE.fullmatch(body)) is not None:
        if body.startswith("ROOT"):
            if ctx.root_service is None:
                raise PlaceholderError("C2", body, f"no root under {ctx.status}")
            return ctx.root_fields[m["root"]] if m["root"] else ctx.root_service
        if body.startswith("RUNNER_UP"):
            if ctx.runner_up is None:
                raise PlaceholderError("C2", body, "no runner-up")
            return {"fault_class": ctx.runner_up.fault_class, "indicator": ctx.runner_up.indicator}.get(
                m["ru"] or "", ctx.runner_up.service
            )
        if m["conf"] == "level":
            return ctx.conf_level
        if m["conf"] == "set_size":
            return str(ctx.conf_set_size)
        if m["conf"] == "margin":
            return format_margin(ctx.conf_margin)
        if m["status"]:
            return ctx.status
        if ctx.onset_ns is None:
            raise PlaceholderError("C2", body, "onsets.json is absent")
        return format_time_utc(ctx.onset_ns)
    if (m := _SVC.fullmatch(body)) is not None:
        if m["node"] not in ctx.nodes:
            raise PlaceholderError("C2", body, "not a graph node")
        return m["node"]
    raise PlaceholderError("C1", body, "not a placeholder of the grammar")


def check_cites(cites: Sequence[str], ctx: FillContext) -> None:
    """C3 for the cite list itself: every cite is an atom of the evidence table."""
    for cite in cites:
        if cite not in ctx.table:
            raise PlaceholderError("C3", cite, "cited atom is not in the evidence table")


def fill(text: str, cites: Sequence[str], ctx: FillContext) -> str:
    """`text` with every placeholder replaced; PlaceholderError on the first C1–C3 violation."""
    check_cites(cites, ctx)
    placeholders(text)  # C1 first, for the whole sentence
    cited = frozenset(cites)
    return _BRACED.sub(lambda m: _resolve(m.group(1), cited, ctx), text)
