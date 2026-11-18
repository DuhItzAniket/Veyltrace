"""Number and time formatting for card text (10 §3.3): one function each, deterministic.

Why one formatter: every number a reader sees on the card (filled placeholders, the evidence table
in `card.md`, the timeline) goes through the same rule, so the same atom value always reads the
same, on every machine and in every locale. Decimal arithmetic with ROUND_HALF_EVEN avoids binary
float rounding surprises; times are converted with integer arithmetic, never with a time zone or
the clock.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Final

__all__ = [
    "MARGIN_DECIMALS",
    "NOT_AVAILABLE",
    "format_count",
    "format_margin",
    "format_number",
    "format_numbers_in",
    "format_time_utc",
]

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
#: Decimal precision for format_margin: the 309 integer digits of the largest float, plus the
#: decimals, rounded up (a priori; only keeps quantize total).
_MARGIN_PREC: Final = 320
#: A free-standing non-integer number in upstream text (an ask's `why`): not part of an identifier
#: such as `T1` or `synth-01`. `margin` captures a preceding "margin " (10 §3.1 step 7).
_TEXT_NUMBER: Final = re.compile(
    r"(?P<margin>\bmargin )?(?<![\w.\-])(?P<num>-?\d+(?:\.\d+(?:[eE][+-]?\d+)?|[eE][+-]?\d+))(?![\w\-]|\.\d)"
)


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
    """{CONF.margin}: the relative margin with two decimals, half-even.

    Total over floats, like format_number: NaN and ±inf print as "n/a", and a margin that rounds to
    zero prints "0.00", never "-0.00".
    """
    if not math.isfinite(margin):
        return NOT_AVAILABLE
    step = Decimal(1).scaleb(-MARGIN_DECIMALS)
    # Enough digits for any finite float (max ~1.8e308) plus the decimals, so quantize never raises.
    exact = Context(prec=_MARGIN_PREC).create_decimal(repr(float(margin)))
    rounded = exact.quantize(step, rounding=ROUND_HALF_EVEN, context=Context(prec=_MARGIN_PREC))
    return format(rounded.copy_abs() if rounded.is_zero() else rounded, "f")


def format_count(count: int, noun: str, plural: str | None = None) -> str:
    """`count` with its counted noun in agreement (10 §3.3): "1 service", "0 services", "2 services".

    The one rule for every counted noun on the card, so a count never reads "1 services". `plural`
    is for a noun whose plural is not `noun + "s"`.
    """
    if type(count) is not int:  # a bool is an int subclass, and not a count
        raise TypeError(f"a count must be an int, got {count!r}")
    return f"{count} {noun if count == 1 else (plural or noun + 's')}"


def format_numbers_in(text: str, sig_digits: int) -> str:
    """`text` from an upstream artifact with each free-standing non-integer reformatted (10 §3.1
    step 7): a number after "margin " as {CONF.margin} reads (`format_margin`), any other through
    `format_number`, so an ask states a number with the same precision as the rest of the card.

    Integers (counts) and digits inside identifiers (`T1`, `synth-01`) are left as they are.
    """

    def one(m: re.Match[str]) -> str:
        value = float(m["num"])
        if m["margin"]:
            return m["margin"] + format_margin(value)
        return format_number(value, sig_digits)

    return _TEXT_NUMBER.sub(one, text)


def format_time_utc(t_ns: int) -> str:
    """Nanoseconds since the epoch as `HH:MM:SS UTC` (10 §3.3 {ONSET}, §3.7 timeline)."""
    seconds = (t_ns // _NS_PER_S) % _S_PER_DAY
    hours, rest = divmod(seconds, _S_PER_HOUR)
    minutes, secs = divmod(rest, _S_PER_MIN)
    return f"{hours:02d}:{minutes:02d}:{secs:02d} UTC"
