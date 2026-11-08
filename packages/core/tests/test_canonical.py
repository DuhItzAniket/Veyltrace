"""canonical_json: byte layout, normalisation rules, rejections and idempotence (03 §1)."""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict, Field

from veyltrace_core.canonical import canonical_json, canonical_json_str, normalize


def test_layout_sorted_keys_compact_separators() -> None:
    assert canonical_json({"b": 1, "a": [1, 2.5, None, True, "x"]}) == b'{"a":[1,2.5,null,true,"x"],"b":1}'


def test_non_ascii_is_utf8_not_escaped() -> None:
    text = "→ ≥ § é 😀"
    assert canonical_json({"k": text}) == ('{"k":"' + text + '"}').encode("utf-8")
    assert canonical_json_str({"k": text}) == '{"k":"' + text + '"}'


def test_keys_sort_in_utf8_byte_order() -> None:
    keys = ["é", "z", "A", "a", "😀", "ÿ", "￿"]
    out = json.loads(canonical_json(dict.fromkeys(keys, 0)))
    assert list(out) == sorted(keys, key=lambda k: k.encode("utf-8"))


def test_floats_round_to_nine_decimals() -> None:
    assert normalize(0.1234567891234) == 0.123456789
    assert canonical_json(1.0000000004) == b"1.0"
    assert canonical_json(0.1 + 0.2) == b"0.3"
    assert canonical_json(1e20) == b"1e+20"


def test_negative_zero_and_tiny_negatives_become_zero() -> None:
    assert canonical_json(-0.0) == b"0.0"
    assert canonical_json(-1e-12) == b"0.0"
    out = normalize(-1e-12)
    assert isinstance(out, float)
    assert math.copysign(1.0, out) == 1.0


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, np.float64("nan"), np.float32("inf")])
def test_non_finite_floats_are_null(value: float) -> None:
    assert canonical_json([value]) == b"[null]"


def test_int_and_float_stay_distinct() -> None:
    assert canonical_json(4) == b"4"
    assert canonical_json(4.0) == b"4.0"
    assert canonical_json(2**70) == str(2**70).encode()  # big ints are exact, never floats


def test_bool_stays_bool() -> None:
    assert canonical_json([True, False]) == b"[true,false]"
    assert normalize(True) is True


def test_tuple_and_sequences_become_lists() -> None:
    assert canonical_json((1, (2, 3))) == b"[1,[2,3]]"
    assert canonical_json(range(3)) == b"[0,1,2]"


def test_numpy_scalars_become_python_scalars() -> None:
    values = [np.int64(3), np.uint8(7), np.float32(0.1), np.float64(1.5), np.bool_(True), np.str_("x")]
    out = normalize(values)
    # float32(0.1) is 0.10000000149011612 as a double; 9 decimals keep its float32 error visible.
    assert out == [3, 7, 0.100000001, 1.5, True, "x"]
    assert isinstance(out, list)
    assert [type(v) for v in out] == [int, int, float, float, bool, str]


class _Color(StrEnum):
    RED = "red"


class _Level(IntEnum):
    HIGH = 2


def test_enum_subclasses_become_plain_values() -> None:
    assert canonical_json({_Color.RED: _Level.HIGH, "c": _Color.RED}) == b'{"c":"red","red":2}'
    assert type(normalize(_Color.RED)) is str
    assert type(normalize(_Level.HIGH)) is int


class _Inner(BaseModel):
    model_config = ConfigDict(frozen=True)
    k: float


class _Outer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type_: str = Field(alias="_type")
    inner: _Inner
    items: tuple[int, ...]


def test_pydantic_models_dump_json_mode_by_alias() -> None:
    model = _Outer(_type="x", inner=_Inner(k=4.0), items=(1, 2))
    assert canonical_json(model) == b'{"_type":"x","inner":{"k":4.0},"items":[1,2]}'
    assert canonical_json({"m": model}) == b'{"m":{"_type":"x","inner":{"k":4.0},"items":[1,2]}}'


def test_read_only_mappings_are_accepted() -> None:
    frozen = MappingProxyType({"b": (1, 2), "a": MappingProxyType({"x": None})})
    assert canonical_json(frozen) == b'{"a":{"x":null},"b":[1,2]}'


@dataclass(frozen=True)
class _DC:
    x: int


@pytest.mark.parametrize(
    "value",
    [
        {1, 2},
        frozenset({1}),
        b"bytes",
        bytearray(b"x"),
        memoryview(b"x"),
        dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        dt.date(2026, 1, 1),
        _DC(1),
        np.array([1, 2]),
        np.datetime64("2026-01-01T00:00:00.000000001"),
        np.timedelta64(5, "ns"),
        np.bytes_(b"x"),
        complex(1, 2),
        Decimal("1.5"),
        Path("a/b"),
        object(),
    ],
    ids=lambda v: type(v).__name__,
)
def test_values_without_a_canonical_form_raise_type_error(value: Any) -> None:
    with pytest.raises(TypeError):
        canonical_json(value)
    with pytest.raises(TypeError):
        canonical_json({"nested": [value]})


@pytest.mark.parametrize("key", [1, 1.5, True, None, ("a",), b"k"], ids=repr)
def test_non_str_keys_raise_type_error(key: Any) -> None:
    with pytest.raises(TypeError, match="keys must be str"):
        canonical_json({key: 1})


# ----------------------------------------------------------------------------------------------
# Properties

_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.floats(min_value=-1e-6, max_value=1e-6)  # values near the rounding cut-off
    | st.text()
)
_json_like = st.recursive(
    _scalars,
    lambda children: (
        st.lists(children, max_size=5)
        | st.tuples(children, children)
        | st.dictionaries(st.text(max_size=8), children, max_size=5)
    ),
    max_leaves=30,
)


@given(_json_like)
def test_idempotent_through_parse(value: Any) -> None:
    once = canonical_json(value)
    assert canonical_json(json.loads(once)) == once


@given(_json_like)
def test_normalize_is_a_projection(value: Any) -> None:
    norm = normalize(value)
    assert normalize(norm) == norm
    assert json.loads(canonical_json(value)) == norm  # floats survive the text round trip exactly


@given(st.dictionaries(st.text(max_size=8), _scalars, max_size=8))
def test_insertion_order_is_irrelevant(mapping: dict[str, Any]) -> None:
    reversed_mapping = dict(reversed(list(mapping.items())))
    assert canonical_json(reversed_mapping) == canonical_json(mapping)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_float_output_is_rounded_and_never_negative_zero(x: float) -> None:
    out = normalize(x)
    assert isinstance(out, float)
    assert out == round(x, 9)
    if out == 0.0:
        assert math.copysign(1.0, out) == 1.0
