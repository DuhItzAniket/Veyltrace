"""The per-case output schema of `brief` mode (08 §3.1 step 3, §3.4).

Why flat and enum-heavy: small models on constrained decoders do well on simple schemas and collapse
on complex ones, and closed enums make an invented service, predicate or fault class impossible to
express. One claim object with generic slots (`signal`, `other`, `x`) covers the whole predicate
library; code maps the slots to named arguments afterwards. Every list is sorted, so the schema, and
with it the cassette key, depends only on the case and the config.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, get_args

from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_json
from veyltrace_faultloom.predicates import LIBRARY
from veyltrace_relentra.settings import BriefSettings

__all__ = ["EMPTY", "CaseEnums", "build_enums", "build_schema", "schema_sha256"]

#: Log-template signals are not predicate arguments (08 §3.1 step 3).
TEMPLATE_PREFIX: Final = "tmpl:"
#: The empty slot value: this claim or hypothesis does not use the slot (08 §3.4).
EMPTY: Final = ""
# Limits of the proposals contract (03 §9.1), repeated so the model cannot exceed them.
MAX_CITES: Final = 3
MAX_TRIALS: Final = 4
MAX_ASKS: Final = 3
MAX_RATIONALE: Final = 280
MAX_ASK_TARGET: Final = 80
MAX_ASK_WHY: Final = 160
ASK_KINDS: Final[tuple[str, ...]] = get_args(models.AskKind)
_TRIALS: Final[tuple[str, ...]] = get_args(models.TrialId)  # T1 ... T10, numeric order
_INDICATORS: Final[tuple[str, ...]] = get_args(models.Indicator)
_FAULT_CLASSES: Final[tuple[str, ...]] = get_args(models.FaultClass)


@dataclass(frozen=True)
class CaseEnums:
    """The closed vocabularies of one case (08 §3.1 step 3), sorted by code point; trials stay in
    numeric order."""

    nodes: tuple[str, ...]
    fault_classes: tuple[str, ...]
    predicates: tuple[str, ...]
    signals: tuple[str, ...]
    atom_ids: tuple[str, ...]
    indicators: tuple[str, ...]
    trials: tuple[str, ...] = _TRIALS


def build_enums(
    nodes: Iterable[str], signals: Iterable[str], atom_ids: Iterable[str], settings: BriefSettings
) -> CaseEnums:
    """The enums from graph nodes, series signals and the atoms shown on the evidence cards."""
    usable = sorted({s for s in signals if not s.startswith(TEMPLATE_PREFIX)})
    return CaseEnums(
        nodes=tuple(sorted(set(nodes))),
        fault_classes=tuple(sorted(set(_FAULT_CLASSES) - set(settings.exclude_fault_classes))),
        predicates=tuple(sorted(LIBRARY)),
        signals=tuple(usable[: settings.max_signal_enum]),
        atom_ids=tuple(sorted(set(atom_ids))),
        indicators=tuple(sorted(_INDICATORS)),
    )


def _text(max_length: int) -> dict[str, Any]:
    return {"type": "string", "maxLength": max_length}


def _closed(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": properties}


def _cites(enums: CaseEnums) -> dict[str, Any]:
    if not enums.atom_ids:  # an empty enum is invalid JSON Schema; a claim may cite nothing (08 §2.2)
        return {"type": "array", "maxItems": 0, "items": {"type": "string"}}
    return {"type": "array", "maxItems": MAX_CITES, "items": {"enum": list(enums.atom_ids)}}


def build_schema(enums: CaseEnums, settings: BriefSettings) -> dict[str, Any]:
    """The JSON schema of 08 §3.4. A schema over `schema.max_bytes` is a ConfigError."""
    claim = _closed(
        ["predicate", "signal", "other", "x", "cites"],
        {
            "predicate": {"enum": list(enums.predicates)},
            "signal": {"enum": [*enums.signals, EMPTY]},
            "other": {"enum": [*enums.nodes, EMPTY]},
            "x": {"type": "number"},
            "cites": _cites(enums),
        },
    )
    proposal = _closed(
        ["service", "fault_class", "indicator", "claims", "requested_trials", "rationale"],
        {
            "service": {"enum": list(enums.nodes)},
            "fault_class": {"enum": list(enums.fault_classes)},
            "indicator": {"enum": [*enums.indicators, EMPTY]},
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": settings.max_claims_per_proposal,
                "items": claim,
            },
            "requested_trials": {
                "type": "array",
                "maxItems": MAX_TRIALS,
                "items": {"enum": list(enums.trials)},
            },
            "rationale": _text(MAX_RATIONALE),
        },
    )
    ask = _closed(
        ["kind", "target", "why"],
        {"kind": {"enum": list(ASK_KINDS)}, "target": _text(MAX_ASK_TARGET), "why": _text(MAX_ASK_WHY)},
    )
    schema = _closed(
        ["proposals", "asks"],
        {
            "proposals": {"type": "array", "maxItems": settings.max_proposals, "items": proposal},
            "asks": {"type": "array", "maxItems": MAX_ASKS, "items": ask},
        },
    )
    size = len(canonical_json(schema))
    if size > settings.schema_max_bytes:
        msg = f"the case schema is {size} bytes, over relentra.schema.max_bytes {settings.schema_max_bytes}"
        raise ConfigError(msg)
    return schema


def schema_sha256(schema: Mapping[str, Any]) -> str:
    """This schema's contribution to `run_manifest.ai.schema_sha256` (08 §3.4)."""
    return sha256_json(dict(schema))
