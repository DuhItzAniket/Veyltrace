"""Canonical cell text of the generated tables (R-17, 04 §10).

One formatting rule per kind of number, so a table is byte-identical across runs and platforms.
Rounding is decimal ROUND_HALF_UP of the value as summary.json writes it (`repr`, the shortest
decimal that round-trips the float): 0.1235 in the file prints as 0.124, as a reader rounding the
file by hand would get, and never depends on the binary float below it, the locale or libc. A cell
never stays blank: a value that is missing says why, through its note.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from veyltrace_core.errors import ConfigError
from veyltrace_stats.exact import clopper_pearson

NOT_RUN = "not run"
NOT_RUN_PREFIX = "not run: "  # the bench_summary 1.1 `statistics` string form (03 §13.3)
UNDEFINED = "n/a"
UNDEFINED_NOTE = (
    "null in summary.json: undefined for this group, as no row has the value "
    "(no fault case, no slate, no LLM tokens; 03 §13.3)"
)
RATE_DIGITS = 3  # a priori: 1/270 ≈ 0.004 is one RE2 case, so a third decimal resolves one case
P_DIGITS = 4  # review decision (R-17, 21 Nov): p-values carry one decimal more than rates
P_FLOOR = 0.001  # p-values below it print as "<0.001" (a priori presentation, as the paper's tables)
DASH = "—"  # a share over no pairs: no estimate and no interval (R-17 #46, lead brief)
NO_PAIRS_NOTE = "no (case, seed) pairs (n = 0): the share and its exact interval are undefined"
#: A share in summary.json is k / n as a float; k is recovered when share · n lies this close to an
#: integer (a float k / n is within n · 2**-53 of it, far inside this tolerance; a priori).
SHARE_TOLERANCE = 1e-6


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


def fixed(value: float, digits: int = RATE_DIGITS, *, signed: bool = False) -> str:
    """`value` with `digits` decimals, ROUND_HALF_UP. A negative value that rounds to zero prints
    unsigned, except when `signed` (an interval bound: "-0.000" says the bound lies below 0)."""
    out = str(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
    return out[1:] if out.startswith("-") and Decimal(out) == 0 and not signed else out


def rate(value: float | None, interval: tuple[float, float] | None = None, note: str | None = None) -> Cell:
    """A rate or mean, with its 95% interval as `[low, high]` when the summary has one."""
    if value is None:
        return Cell(UNDEFINED, UNDEFINED_NOTE)
    out = fixed(value)
    if interval is not None:
        out += f" [{fixed(interval[0], signed=True)}, {fixed(interval[1], signed=True)}]"
    return Cell(out, note)


def count(value: int | float | None) -> Cell:
    """An integer count, or a percentile of integer-valued columns (ms, MiB, tokens), unrounded."""
    if value is None:
        return Cell(UNDEFINED, UNDEFINED_NOTE)
    return Cell(fixed(float(value), 0))


def p_value(value: float | None) -> Cell:
    """A p-value with P_DIGITS decimals, "<0.001" below P_FLOOR."""
    if value is None:
        return Cell(UNDEFINED, UNDEFINED_NOTE)
    return Cell(f"<{fixed(P_FLOOR)}" if value < P_FLOOR else fixed(value, P_DIGITS))


def exact_share(share: float | None, n: int | None) -> Cell:
    """A share of `n` independent pairs with its 95% exact (Clopper–Pearson) interval, as 04 §8
    gives proportions without clusters (H2b decoy flips, H2c permutation invariance); a dash for
    n = 0. A share that is not k / n for an integer k breaks 03 §13.3 and is an error."""
    if n == 0 and share is None:
        return Cell(DASH, NO_PAIRS_NOTE)
    if share is None or n is None or n < 1 or not 0.0 <= share <= 1.0:
        raise ConfigError(f"summary.json share {share!r} of n = {n!r} is not k / n (03 §13.3)")
    k = round(share * n)
    if abs(share * n - k) > SHARE_TOLERANCE:
        raise ConfigError(f"summary.json share {share!r} of n = {n} is not k / n for an integer k")
    ci = clopper_pearson(k, n)
    return rate(share, (ci.low, ci.high))
