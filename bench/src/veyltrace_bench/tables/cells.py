"""Canonical cell text of the generated tables (R-17, 04 §10).

One formatting rule per kind of number, so a table is byte-identical across runs and platforms
(Python's fixed-point formatting is correctly rounded from the binary value, not locale- or
libc-dependent). A cell never stays blank: a value that is missing says why, through its note.
"""

from __future__ import annotations

from dataclasses import dataclass

NOT_RUN = "not run"
NOT_RUN_PREFIX = "not run: "  # the bench_summary 1.1 `statistics` string form (03 §13.3)
UNDEFINED = "n/a"
UNDEFINED_NOTE = "null in summary.json: undefined for this group, e.g. no fault case (03 §13.3)"
RATE_DIGITS = 3  # a priori: 1/270 ≈ 0.004 is one RE2 case, so a third decimal resolves one case
P_FLOOR = 0.001  # p-values below it print as "<0.001" (a priori presentation, as the paper's tables)


@dataclass(frozen=True)
class Cell:
    """The text of one table cell and an optional note the renderer numbers below the table."""

    text: str
    note: str | None = None


def text(value: str) -> Cell:
    """A label cell (system, method, protocol)."""
    return Cell(value)


def not_run(reason: str) -> Cell:
    """A cell that has no value, with the reason; a reason given as "not run: …" is not doubled."""
    reason = reason.removeprefix(NOT_RUN_PREFIX)
    return Cell(NOT_RUN, NOT_RUN_PREFIX + reason)


def fixed(value: float, digits: int = RATE_DIGITS) -> str:
    """`value` with `digits` decimals; a negative value that rounds to zero prints unsigned."""
    out = f"{value:.{digits}f}"
    return out[1:] if out.startswith("-") and float(out) == 0 else out


def rate(value: float | None, interval: tuple[float, float] | None = None, note: str | None = None) -> Cell:
    """A rate or mean, with its 95% interval as `[low, high]` when the summary has one."""
    if value is None:
        return Cell(UNDEFINED, UNDEFINED_NOTE)
    out = fixed(value)
    if interval is not None:
        out += f" [{fixed(interval[0])}, {fixed(interval[1])}]"
    return Cell(out, note)


def count(value: int | float | None) -> Cell:
    """An integer count, or a percentile of integer-valued columns (ms, MB, tokens), unrounded."""
    if value is None:
        return Cell(UNDEFINED, UNDEFINED_NOTE)
    return Cell(fixed(float(value), 0))


def p_value(value: float | None) -> Cell:
    """A p-value with three decimals, "<0.001" below P_FLOOR."""
    if value is None:
        return Cell(UNDEFINED, UNDEFINED_NOTE)
    return Cell(f"<{fixed(P_FLOOR)}" if value < P_FLOOR else fixed(value))
