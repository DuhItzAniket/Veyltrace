"""Number and time formatting for card text (10 §3.3): one function each, deterministic.

Why one formatter: every number a reader sees on the card (filled placeholders, the evidence table
in `card.md`, the timeline) goes through the same rule, so the same atom value always reads the
same, on every machine and in every locale. Decimal arithmetic with ROUND_HALF_EVEN avoids binary
float rounding surprises; times are converted with integer arithmetic, never with a time zone or
the clock.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

__all__ = ["MARGIN_DECIMALS", "NOT_AVAILABLE", "format_margin", "format_number", "format_time_utc"]

#: How a missing or non-finite value reads (10 §3.3: null/NaN → n/a).
NOT_AVAILABLE: Final = "n/a"
#: Plain notation range of 10 §3.3: 0.001 ≤ |x| < 10^6.
_PLAIN_MIN: Final = Decimal("0.001")
_PLAIN_MAX: Final = Decimal(10) ** 6
_NS_PER_S: Final = 1_000_000_000
_S_PER_DAY: Final = 86_400
_S_PER_HOUR: Final = 3_600
_S_PER_MIN: Final = 60
#: Decimal places of {CONF.margin} (10 §3.3 table: "margin, 2 decimals").
MARGIN_DECIMALS: Final = 2


def format_number(value: float | int | None, sig_digits: int) -> str:
    """`value` with `sig_digits` significant figures (10 §3.3).

    Integers below 10^6 print unchanged; other values in [0.001, 10^6) print in plain notation
    (trailing zeros kept: 1.0 → "1.00"); everything else uses `.<sig_digits>g`; null, NaN and
    ±inf print as "n/a".
    """
    if value is None:
        return NOT_AVAILABLE
    if isinstance(value, bool):
        raise TypeError("a bool is not a number to format")
    if isinstance(value, int) and abs(value) < _PLAIN_MAX:
        return str(value)
    if not math.isfinite(value):
        return NOT_AVAILABLE
    if value == 0:
        return "0"
    exact = Decimal(repr(float(value)))
    if not _PLAIN_MIN <= abs(exact) < _PLAIN_MAX:
        return format(float(value), f".{sig_digits}g")
    step = Decimal(1).scaleb(exact.adjusted() - sig_digits + 1)
    return format(exact.quantize(step, rounding=ROUND_HALF_EVEN), "f")


def format_margin(margin: float) -> str:
    """{CONF.margin}: the relative margin with two decimals, half-even."""
    step = Decimal(1).scaleb(-MARGIN_DECIMALS)
    return format(Decimal(repr(float(margin))).quantize(step, rounding=ROUND_HALF_EVEN), "f")


def format_time_utc(t_ns: int) -> str:
    """Nanoseconds since the epoch as `HH:MM:SS UTC` (10 §3.3 {ONSET}, §3.7 timeline)."""
    seconds = (t_ns // _NS_PER_S) % _S_PER_DAY
    hours, rest = divmod(seconds, _S_PER_HOUR)
    minutes, secs = divmod(rest, _S_PER_MIN)
    return f"{hours:02d}:{minutes:02d}:{secs:02d} UTC"
