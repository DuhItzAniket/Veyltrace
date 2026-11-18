"""Number and time formatting for card text (10 §3.3): one function each, deterministic.

Why one formatter: every number a reader sees on the card (filled placeholders, the evidence table
in `card.md`, the timeline) goes through the same rule, so the same atom value always reads the
same, on every machine and in every locale. Decimal arithmetic with ROUND_HALF_EVEN avoids binary
float rounding surprises; times are converted with integer arithmetic, never with a time zone or
the clock.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Final

__all__ = [
    "COUNT_UNITS",
    "MARGIN_DECIMALS",
    "NOT_AVAILABLE",
    "format_margin",
    "format_number",
    "format_time_utc",
    "format_value",
]

#: How a missing or non-finite value reads (10 §3.3: null/NaN → n/a).
NOT_AVAILABLE: Final = "n/a"
#: Plain notation range of 10 §3.3: 0.001 ≤ |x| < 10^6, tested on the rounded value.
_PLAIN_MIN: Final = Decimal("0.001")
_PLAIN_MAX: Final = Decimal(10) ** 6
#: Units whose values are counts (03 §7 canonical units): an atom value in one prints as an
#: integer, decided by its unit, never by testing the float (10 §3.3).
COUNT_UNITS: Final = frozenset({"count"})
#: `%g` writes exponents down to -4 in plain notation (0.000123); kept so the rule reads like `%g`.
_G_PLAIN_EXP: Final = 4
_NS_PER_S: Final = 1_000_000_000
_S_PER_DAY: Final = 86_400
_S_PER_HOUR: Final = 3_600
_S_PER_MIN: Final = 60
#: Decimal places of {CONF.margin} (10 §3.3 table: "margin, 2 decimals").
MARGIN_DECIMALS: Final = 2
#: Decimal precision for format_margin: the 309 integer digits of the largest float, plus the
#: decimals, rounded up (a priori; only keeps quantize total).
_MARGIN_PREC: Final = 320


def format_number(value: float | int | None, sig_digits: int) -> str:
    """`value` with `sig_digits` significant figures, trailing zeros stripped like `%g` (10 §3.3).

    Rounding comes first (half-even on the decimal value); the notation is then chosen from the
    rounded value: plain for 0.001 ≤ |rounded| < 10^6, else the `%g` form (`1.2e+06`; `%g` keeps
    exponent -4 plain, 0.000123). So 999500 → "1e+06"
    (it rounds to 10^6), 1.0 → "1", 1.20 → "1.2", 1.2e+06 → "1.2e+06". Integers below 10^6 print
    unchanged; null, NaN and ±inf print as "n/a".
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
    step = Decimal(1).scaleb(exact.adjusted() - sig_digits + 1)
    rounded = exact.quantize(step, rounding=ROUND_HALF_EVEN, context=Context(prec=sig_digits + 1))
    digits = rounded.normalize()  # trailing zeros stripped: 1.00 → 1, 1.20 → 1.2
    exponent = digits.adjusted()
    if _PLAIN_MIN <= abs(rounded) < _PLAIN_MAX or -_G_PLAIN_EXP <= exponent < sig_digits:
        return format(digits, "f")  # the second test is `%g`'s own plain range (0.000123)
    return f"{format(digits.scaleb(-exponent), 'f')}e{exponent:+03d}"  # `%g` form: 1.2e+06


def format_value(value: float | int | None, unit: str | None, sig_digits: int) -> str:
    """An atom value as the card shows it: a count (`unit` in COUNT_UNITS) as an integer, rounded
    half-even, else `format_number`. Count atoms are float64 in evidence (03 §7), so 12.0 would
    otherwise read as a measurement."""
    if unit in COUNT_UNITS and isinstance(value, float) and math.isfinite(value):
        return format_number(
            int(Decimal(repr(value)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)), sig_digits
        )
    return format_number(value, sig_digits)


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


def format_time_utc(t_ns: int) -> str:
    """Nanoseconds since the epoch as `HH:MM:SS UTC` (10 §3.3 {ONSET}, §3.7 timeline)."""
    seconds = (t_ns // _NS_PER_S) % _S_PER_DAY
    hours, rest = divmod(seconds, _S_PER_HOUR)
    minutes, secs = divmod(rest, _S_PER_MIN)
    return f"{hours:02d}:{minutes:02d}:{secs:02d} UTC"
