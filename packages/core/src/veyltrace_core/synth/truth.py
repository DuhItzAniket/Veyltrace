"""Ground truth of the synth cases: answer-key rows (03 §13.1) and the NO_FAULT normal window.

Evaluation only. Engines never import `veyltrace_core.synth` (AST ban in the isolation test) and
never read `${VEYLTRACE_DATA}/answer_keys/` (02 §2 P7). The fetcher writes the rows there; bench
and tests read them. Every value comes from `layout`, the same specification the generator uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pyarrow as pa

from veyltrace_core import io
from veyltrace_core.canonical import canonical_json_str
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.synth import layout as lay

__all__ = [
    "ANSWER_KEY_CONTRACT",
    "ANSWER_KEY_RELPATH",
    "NormalWindow",
    "answer_key_path",
    "answer_key_rows",
    "answer_key_table",
    "normal_windows",
    "write_answer_keys",
]

ANSWER_KEY_CONTRACT: Final = "answer_key"
#: Relative to the data root (03 §13.1: ${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet).
ANSWER_KEY_RELPATH: Final = f"answer_keys/{lay.DATASET}.parquet"
#: injection_json.tool and .severity for every synth injection (single fixed level).
_TOOL: Final = "synth"
_SEVERITY: Final = "fixed"


def _injection(key: str, fault: lay.Fault) -> str:
    return canonical_json_str(
        {
            "fault_id": fault.fault_id,
            "tool": _TOOL,
            "tool_version": lay.ADAPTER_VERSION,
            "params": dict(fault.params),
            "severity": _SEVERITY,
            # The generator's draws are keyed by the base case id (veyltrace_core.rng).
            "seed": make_case_id(lay.case_spec(key)[0].name),
        }
    )


def _decoys(spec: lay.CaseSpec) -> str | None:
    planted = [
        {"t_ns": lay.T0_NS + c.offset_s * lay.NS, "entity": c.entity, "kind": c.kind, "is_true": c.is_true}
        for c in spec.changes
        if c.is_true is not None
    ]
    return canonical_json_str(planted) if planted else None


def _row(key: str) -> dict[str, Any]:
    spec, variant = lay.case_spec(key)
    fault = variant.fault if variant is not None else spec.fault
    no_fault = fault.root_service is None
    return {
        "case_id": make_case_id(key),
        "dataset": lay.DATASET,
        "system": lay.SYSTEM,
        "is_no_fault": no_fault,
        "root_service": fault.root_service,
        "root_component": fault.root_component,
        "fault_class": fault.fault_class,
        "fault_label": None if no_fault else fault.fault_id,
        "indicator": fault.indicator,
        "mode": fault.mode,
        "t_inject_ns": None if no_fault else lay.T_INJECT_NS,
        "t_end_ns": None if no_fault else lay.DATA_END_NS,
        "injection_json": None if no_fault else _injection(key, fault),
        "extra_roots_json": None,
        "decoy_changes_json": _decoys(spec) if variant is None else None,
        "validated": None,
        "sli_impact_json": None,
    }


def answer_key_rows(*, include_variants: bool = True) -> list[dict[str, Any]]:
    """One answer_key row per synth case (and, by default, per generator variant), by case_id."""
    keys = [*lay.CASE_NAMES, *(sorted(lay.GENERATOR_VARIANTS) if include_variants else [])]
    return sorted((_row(k) for k in keys), key=lambda r: str(r["case_id"]))


def answer_key_table(*, include_variants: bool = True) -> pa.Table:
    """The rows as an answer_key-typed Arrow table (validated when written)."""
    rows = answer_key_rows(include_variants=include_variants)
    return pa.Table.from_pylist(rows, schema=io.arrow_schema(ANSWER_KEY_CONTRACT))


def answer_key_path(data_root: Path) -> Path:
    return data_root / ANSWER_KEY_RELPATH


def write_answer_keys(data_root: Path) -> tuple[Path, str]:
    """Write `${data_root}/answer_keys/synth.parquet` with core's io writer; (path, sha256)."""
    path = answer_key_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, io.write_path(ANSWER_KEY_CONTRACT, answer_key_table(), path)


@dataclass(frozen=True)
class NormalWindow:
    """A no-fault window for NO_FAULT calibration (04 §5.4; 02 §6.9).

    synth-05 is one normal window as it is: oracle protocol, no shift, all sources. It is used for
    calibration only and never reported (04 §2, §5.4).
    """

    case: str
    case_id: str
    dataset: str = lay.DATASET
    #: bench_result.variant of the window ("" = the unperturbed run, 03 §13.2).
    variant: str = ""
    protocol: str = "oracle"
    shift_s: int = 0
    overrides: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    reportable: bool = False


def normal_windows() -> tuple[NormalWindow, ...]:
    """The synth normal windows: every no-fault case (synth-05)."""
    return tuple(
        NormalWindow(case=name, case_id=make_case_id(name))
        for name in lay.CASE_NAMES
        if lay.CASES[name].fault.root_service is None
    )
