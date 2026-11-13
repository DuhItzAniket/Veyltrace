"""The span error-status rule (01 §3.5): `status` from a case's raw status codes.

Why a case-level rule: RCAEval's `statusCode` mixes conventions. When every code of the case is an
OTel status (0 unset, 1 ok, 2 error) the codes are read that way; otherwise each code is an HTTP
status (`>= 100`, error from `http_error_min`) or a gRPC code (`1..99`, every non-zero code is an
error). Null and 0 are never errors; under the OTel reading 0 is `unset`, otherwise a present
non-error code (0 included) is `ok`. Known limit: under the OTel reading gRPC CANCELLED (1) is ok.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

import numpy as np
import pyarrow as pa

__all__ = ["ERROR", "OK", "UNSET", "StatusRules", "span_status"]

ERROR: Final = "error"
OK: Final = "ok"
UNSET: Final = "unset"
#: The OTel status code that means error (01 §3.5 rule 1), and the one that means ok.
_OTEL_ERROR: Final = 2
_OTEL_OK: Final = 1
#: HTTP status codes start at 100; below that a non-zero code is a gRPC code (01 §3.5 rule 2).
_HTTP_MIN: Final = 100


@dataclass(frozen=True)
class StatusRules:
    """`status.otel_code_set` and `status.http_error_min` (01 §4)."""

    otel_code_set: frozenset[int]
    http_error_min: int

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> StatusRules:
        section = cast("Mapping[str, Any]", cfg["status"])
        return cls(frozenset(int(c) for c in section["otel_code_set"]), int(section["http_error_min"]))


def span_status(codes: pa.Array[Any], rules: StatusRules) -> pa.Array[Any]:
    """`status` (`ok | error | unset`) for each code of one case, by 01 §3.5.

    `codes` are the case's raw codes as integers (null where the source has none); the rule set
    is chosen from all non-null codes of the case together, so pass every span of the case.
    """
    present = np.asarray(codes.is_valid().to_numpy(zero_copy_only=False), dtype=bool)
    values = np.asarray(codes.fill_null(0).to_numpy(zero_copy_only=False), dtype=np.int64)
    seen = set(np.unique(values[present]).tolist())
    if seen <= rules.otel_code_set:
        error = present & (values == _OTEL_ERROR)
        ok = present & (values == _OTEL_OK)
    else:
        http = values >= _HTTP_MIN
        error = present & ((http & (values >= rules.http_error_min)) | (~http & (values >= 1)))
        ok = present & ~error  # a present non-error code, 0 included (gRPC OK)
    out = np.where(error, ERROR, np.where(ok, OK, UNSET))
    return pa.array(out, type=pa.string())
