"""Canonical JSON: the one byte form that every hash, id and JSON artefact in Veyltrace is built on.

Two runs, two machines or two operating systems must produce the same bytes for the same value,
so the encoding fixes everything `json.dumps` leaves open (03 §1; 02 §9 determinism rule 4):

- keys sorted (code-point order, which equals UTF-8 byte order), separators `(",", ":")`,
  UTF-8 without escaping non-ASCII;
- floats rounded to 9 decimals, `-0.0` written as `0.0`, NaN and ±inf written as `null`;
- ints stay ints (`4` and `4.0` hash differently; FaultLoom atom vectors depend on it,
  06 §3.8), bools stay bools, tuples become lists, numpy scalars become Python scalars and
  Pydantic models are dumped with `model_dump(mode="json", by_alias=True)`;
- anything without one obvious JSON form (sets, bytes, datetimes, dataclasses, arrays, non-str
  keys) is a TypeError, so an ambiguous value never silently gets a hash.

The encoding is idempotent: parsing canonical bytes and encoding them again gives the same bytes.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

import numpy as np
from pydantic import BaseModel

__all__ = [
    "FLOAT_DECIMALS",
    "JSONLike",
    "JSONScalar",
    "JSONValue",
    "canonical_json",
    "canonical_json_str",
    "normalize",
]

#: Decimal places kept for floats in canonical JSON (03 §1, 02 §9 rule 3).
FLOAT_DECIMALS = 9

type JSONScalar = str | int | float | bool | None
#: A value after normalisation: plain JSON types only.
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
#: What canonical_json accepts. bytes and str type-check as sequences but bytes is rejected at run time.
type JSONLike = JSONScalar | np.generic | BaseModel | Mapping[str, JSONLike] | Sequence[JSONLike]

# Text-like sequences that are not JSON arrays.
_NOT_ARRAYS = (str, bytes, bytearray, memoryview)


def _norm_float(x: float) -> float | None:
    if not math.isfinite(x):
        return None
    r = round(x, FLOAT_DECIMALS)
    return 0.0 if r == 0.0 else r  # collapses -0.0 (and values that round to it) to 0.0


def normalize(obj: object) -> JSONValue:
    """Return `obj` as plain JSON types under the canonical rules (see module docstring).

    Raises TypeError for values without a canonical JSON form and for non-str mapping keys.
    """
    original: object = obj  # un-narrowed alias for error messages
    # Order matters: numpy scalars first (np.float64 is also a float, np.str_ also a str), bool
    # before int (bool is an int), str before Sequence (a str is a Sequence).
    if isinstance(obj, np.generic):
        if isinstance(obj, np.datetime64 | np.timedelta64):
            # .item() would silently turn nanosecond datetimes into ints; times are explicit *_ns ints.
            raise _no_form(original)
        item: object = cast("np.generic[Any]", obj).item()  # bytes/complex items fail below
        return normalize(item)
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return int(obj)  # plain int, also for int subclasses such as IntEnum
    if isinstance(obj, float):
        return _norm_float(obj)
    if isinstance(obj, str):
        return str.__str__(obj)  # plain str, also for str subclasses such as StrEnum
    if isinstance(obj, BaseModel):
        return normalize(obj.model_dump(mode="json", by_alias=True))
    if isinstance(obj, Mapping):
        out: dict[str, JSONValue] = {}
        for key, value in cast(Mapping[object, object], obj).items():
            if not isinstance(key, str):
                msg = f"canonical JSON keys must be str, got {type(key).__name__}: {key!r}"
                raise TypeError(msg)
            out[str.__str__(key)] = normalize(value)
        return out
    if isinstance(obj, Sequence) and not isinstance(obj, _NOT_ARRAYS):
        return [normalize(item) for item in cast(Sequence[object], obj)]
    raise _no_form(original)


def _no_form(obj: object) -> TypeError:
    return TypeError(f"no canonical JSON form for {type(obj).__name__}: {obj!r}")


def canonical_json_str(obj: JSONLike) -> str:
    """Return the canonical JSON text of `obj` (used for the str columns attrs_json, detail_json,
    args_json, 01 §3.6, 06 §3.4)."""
    return json.dumps(
        normalize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json(obj: JSONLike) -> bytes:
    """Return the canonical JSON bytes of `obj`: the input of every hash and id (03 §1)."""
    return canonical_json_str(obj).encode("utf-8")
