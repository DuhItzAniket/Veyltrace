"""bench_summary 1.1 (CCR #357): the statistics object, the decoy_ranked_first entry, and 1.0 files
still reading as an older minor."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_core import io, textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ContractValidationError

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "contracts" / "examples" / "bench_summary.example.json"
COMPARISON: dict[str, Any] = {
    "dataset": "re2-ob", "system": "ob", "metric": "ac_at_1",
    "method_a": "veyltrace:off", "method_b": "rcaeval:baro", "kind": "noninferiority",
    "family": None, "margin": 0.0, "n_pairs": 89, "n_clusters": 30, "difference": 0.05,
    "low": -0.02, "high": 0.12, "sign_flip_p": 0.21, "mcnemar_only_a": 9, "mcnemar_only_b": 5,
    "mcnemar_p": 0.42, "holm_p": None,
}  # fmt: skip


def _example() -> dict[str, Any]:
    return json.loads(textio.read_text(EXAMPLE))


def _read(doc: dict[str, Any], tmp_path: Path) -> Any:
    path = tmp_path / "summary.json"
    textio.write_bytes(path, canonical_json(doc) + b"\n")
    return io.read_path("bench_summary", path, validate=True)


def test_a_1_0_summary_reads_under_1_1_with_decoy_null_and_the_string_kept(tmp_path: Path) -> None:
    """A 1.0 file (no decoy_ranked_first, statistics a string) reads as an older minor (#357)."""
    doc = _example()
    doc["schema_version"] = "1.0.0"
    doc["statistics"] = "not run: cluster bootstrap CIs and tests come from bench/stats (O-14)"
    for group in doc["groups"]:
        del group["metrics"]["decoy_ranked_first"]
    summary = _read(doc, tmp_path)
    assert summary.statistics == doc["statistics"]
    assert all(g.metrics.decoy_ranked_first is None for g in summary.groups)


def test_a_statistics_object_with_a_comparison_and_a_decoy_entry_validates(tmp_path: Path) -> None:
    doc = _example()
    doc["statistics"]["comparisons"] = [COMPARISON]
    doc["groups"][0]["metrics"]["decoy_ranked_first"] = {"decoy_ranked_first": 0.25, "n_decoy": 4}
    summary = _read(doc, tmp_path)
    assert summary.statistics.comparisons[0].margin == 0.0
    assert summary.groups[0].metrics.decoy_ranked_first.n_decoy == 4


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("kind", "equivalence"),  # not one of the three kinds
        ("metric", "lift_at_1"),  # a ratio has no cluster-bootstrap interval
        ("sign_flip_p", 1.5),  # a p-value lies in [0, 1]
    ],
)
def test_a_bad_comparison_is_refused(tmp_path: Path, where: str, value: object) -> None:
    doc = _example()
    doc["statistics"]["comparisons"] = [copy.deepcopy(COMPARISON) | {where: value}]
    with pytest.raises(ContractValidationError):
        _read(doc, tmp_path)


def test_statistics_as_a_string_must_say_not_run(tmp_path: Path) -> None:
    doc = _example()
    doc["statistics"] = "computed elsewhere"
    with pytest.raises(ContractValidationError):
        _read(doc, tmp_path)
