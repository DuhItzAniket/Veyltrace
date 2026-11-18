"""RCAEval-C in the runner (04 §5.2; #326): one events overlay per case, and its answer-key row.

The generator (`veyltrace_decoys`, Observe's O-13) draws decoys from `case_manifest.services`
(04-causync §3.7); every method's run names the overlay in `infralume.events.overlay_path` (01
§3.10). Which change is true goes only into the answer-key row (`decoy_changes_json`, 03 §13.1),
scored as `decoy_present` and `decoy_ranked_first` (04 §7); the engines see identical rows.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from veyltrace_bench.metrics import coarse_ranking, coarse_service
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.errors import ConfigError
from veyltrace_decoys.rcaevalc import DecoySpec, decoy_changes_json, generate, write_overlay

__all__ = ["DecoySpec", "Prepared", "decoy_columns", "decoy_spec", "prepare_case"]


@dataclass(frozen=True)
class Prepared:
    """A case ready for its RCAEval-C runs: the answer-key row with `decoy_changes_json`, and the
    overlay as the value of `infralume.events.overlay_path` (POSIX, relative to the data root)."""

    key: AnswerKeyRow
    overlay: str


def decoy_spec(decoys: Mapping[str, object] | None) -> DecoySpec | None:
    """`protocol.decoys` as the generator's spec (None without it); a bad block is a ConfigError,
    raised before any case runs."""
    if decoys is None:
        return None
    try:
        return DecoySpec.from_protocol(decoys)
    except ValueError as exc:
        raise ConfigError(f"protocol.decoys: {exc}") from None


def prepare_case(
    experiment_id: str, key: AnswerKeyRow, spec: DecoySpec, services: Sequence[str], data_root: Path
) -> Prepared:
    """Generate and write the overlay of one fault case; RCAEval-C plants changes around the
    injection on the root, so a case without a root service or an injection time is refused."""
    if key.root_service is None or key.t_inject_ns is None:
        raise ConfigError(f"protocol.decoys: case {key.case_id} has no root_service or t_inject_ns")
    changes = generate(key.case_id, key.root_service, key.t_inject_ns, services, spec)
    path, _ = write_overlay(experiment_id, key.case_id, changes, data_root)
    row = key.model_copy(update={"decoy_changes_json": decoy_changes_json(changes)})
    return Prepared(row, path.relative_to(data_root).as_posix())


def decoy_columns(key: AnswerKeyRow, ranks: Sequence[str]) -> dict[str, bool | None]:
    """per_case.csv `decoy_present` and `decoy_ranked_first` (03 §13.2; 04 §7): a decoy is a
    `decoy_changes_json` row with `is_true = false`, counted for its entity's service; `ranks` are
    the scored ones (empty for a miss, so a present decoy is then not ranked first). Both are null
    for a case without planted changes, and `decoy_ranked_first` is null without a decoy."""
    if key.decoy_changes_json is None:
        return {"decoy_present": None, "decoy_ranked_first": None}
    rows = cast("list[dict[str, object]]", json.loads(key.decoy_changes_json))
    decoys = {coarse_service(str(r["entity"])) for r in rows if r["is_true"] is False}
    if not decoys:
        return {"decoy_present": False, "decoy_ranked_first": None}
    top = coarse_ranking(ranks)[:1]
    return {"decoy_present": True, "decoy_ranked_first": bool(top) and top[0] in decoys}
