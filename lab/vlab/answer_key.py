"""Answer keys for lab captures (03 §13.1; 05 §11).

Written only to ``lab/captures/answer_keys/<capture_id>.json``, never into a capture folder, and
read only by lab and bench code (AGENTS §4.5).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: Columns of 03 §13.1 `answer_key`; a key with any other column is a contract change.
COLUMNS = frozenset({
    "case_id", "dataset", "system", "is_no_fault", "root_service", "root_component", "fault_class",
    "fault_label", "indicator", "mode", "t_inject_ns", "t_end_ns", "injection_json",
    "extra_roots_json", "decoy_changes_json", "validated", "sli_impact_json",
})  # fmt: skip
ANSWER_KEYS = "answer_keys"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def case_id(capture_id: str) -> str:
    """First 12 hex of SHA-256(capture_id), the rule Infralume applies at ingest (05 §9)."""
    return hashlib.sha256(capture_id.encode("utf-8")).hexdigest()[:12]


def build(
    *,
    capture_id: str,
    dataset: str,
    root_service: str,
    root_component: str,
    fault_id: str,
    fault_class: str,
    indicator: str,
    t_inject_ns: int,
    t_end_ns: int,
    injection: dict[str, Any],
) -> dict[str, Any]:
    """One single-root fault case. ``validated`` stays null until the 05 §8.2 rule runs (X-11)."""
    key: dict[str, Any] = {
        "case_id": case_id(capture_id),
        "dataset": dataset,
        "system": "ob",
        "is_no_fault": False,
        "root_service": root_service,
        "root_component": root_component,
        "fault_class": fault_class,
        "fault_label": fault_id,
        "indicator": indicator,
        "t_inject_ns": t_inject_ns,
        "t_end_ns": t_end_ns,
        "injection_json": canonical_json(injection),
        "extra_roots_json": None,
        "decoy_changes_json": canonical_json([]),
        "validated": None,
        "sli_impact_json": None,
    }
    assert set(key) <= COLUMNS, sorted(set(key) - COLUMNS)
    return key


def write(key: dict[str, Any], *, capture_id: str, captures_dir: Path) -> Path:
    """Write ``key`` to ``<captures_dir>/answer_keys/<capture_id>.json`` and return the path."""
    folder = captures_dir / ANSWER_KEYS
    path = folder / f"{capture_id}.json"
    if path.resolve().parent != folder.resolve():
        raise ValueError(f"answer key path {path} escapes {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(key) + "\n", encoding="utf-8")
    return path
