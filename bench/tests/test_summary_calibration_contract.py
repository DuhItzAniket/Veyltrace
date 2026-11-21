"""bench_summary 1.2 and bench_manifest 1.1 (CCR #404): the calibration and proposal entries, the
manifest's calibration files, and older files still reading as an older minor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_core import io, textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ContractValidationError

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "contracts" / "examples"
NEW_ENTRIES = (
    "coverage", "set_size", "no_fault_rates", "risk_coverage", "selective_accuracy",
    "decoy_top1_change", "permutation_invariance",
)  # fmt: skip
SHA = "ab" * 32
FAMILY = "rcaeval-re2.off.oracle.foldA"


def _example(name: str) -> dict[str, Any]:
    return json.loads(textio.read_text(EXAMPLES / f"{name}.example.json"))


def _read(name: str, doc: dict[str, Any], tmp_path: Path) -> Any:
    path = tmp_path / f"{name}.json"
    textio.write_bytes(path, canonical_json(doc) + b"\n")
    return io.read_path(name, path, validate=True)


def _filled() -> dict[str, Any]:
    doc = _example("bench_summary")
    metrics = doc["groups"][0]["metrics"]
    metrics["coverage"]["by_fold"] = [
        {"fold": "foldA", "coverage": 0.5, "n_fault": 2},
        {"fold": "foldB", "coverage": None, "n_fault": 0},
    ]
    metrics["no_fault_rates"]["by_fold"] = [{"fold": "foldA", "false_alarm_rate": 0.0, "n_normal": 1}]
    metrics["decoy_top1_change"] = {"decoy_top1_change": 0.25, "n_pairs": 4}
    metrics["permutation_invariance"] = {"permutation_invariance": 1.0, "n_cases": 3}
    return doc


def test_a_1_1_summary_reads_under_1_2_with_the_new_entries_null(tmp_path: Path) -> None:
    doc = _example("bench_summary")
    doc["schema_version"] = "1.1.0"
    for group in doc["groups"]:
        for name in NEW_ENTRIES:
            del group["metrics"][name]
    summary = _read("bench_summary", doc, tmp_path)
    assert all(getattr(g.metrics, name) is None for g in summary.groups for name in NEW_ENTRIES)
    assert summary.groups[0].metrics.ac_at_k is not None  # the 1.1 entries are kept


def test_filled_entries_validate(tmp_path: Path) -> None:
    metrics = _read("bench_summary", _filled(), tmp_path).groups[0].metrics
    assert [f.fold for f in metrics.coverage.by_fold] == ["foldA", "foldB"]
    assert metrics.coverage.coverage_gap == -0.9 and metrics.set_size.n_set == 0
    assert (metrics.decoy_top1_change.n_pairs, metrics.permutation_invariance.n_cases) == (4, 3)


@pytest.mark.parametrize(
    ("entry", "key", "value"),
    [
        ("coverage", "coverage", 1.5),  # a share lies in [0, 1]
        ("risk_coverage", "aurc_verdict", -0.1),
        ("selective_accuracy", "n_fault", -1),  # a count is never negative
        ("no_fault_rates", "by_fold", [{"fold": "", "false_alarm_rate": 0.0, "n_normal": 1}]),
        ("set_size", "set_size_p50", 1.0),  # no key outside the entry's own
    ],
)
def test_a_bad_entry_is_refused(tmp_path: Path, entry: str, key: str, value: object) -> None:
    doc = _filled()
    doc["groups"][0]["metrics"][entry][key] = value
    with pytest.raises(ContractValidationError):
        _read("bench_summary", doc, tmp_path)


def test_folds_must_be_sorted(tmp_path: Path) -> None:
    doc = _filled()
    doc["groups"][0]["metrics"]["coverage"]["by_fold"].reverse()
    with pytest.raises(ContractValidationError):
        _read("bench_summary", doc, tmp_path)


def test_a_1_0_manifest_reads_under_1_1_with_calibrations_null(tmp_path: Path) -> None:
    doc = _example("bench_manifest")
    doc["schema_version"] = "1.0.0"
    del doc["calibrations"]
    assert _read("bench_manifest", doc, tmp_path).calibrations is None


def test_calibration_files_validate_sorted_by_family_then_hash(tmp_path: Path) -> None:
    doc = _example("bench_manifest")
    files = [
        {"family_id": FAMILY, "sha256": SHA, "fitted": True},
        {"family_id": FAMILY.replace("foldA", "foldB"), "sha256": "0" * 64, "fitted": False},
    ]
    doc["calibrations"] = files
    got = _read("bench_manifest", doc, tmp_path).calibrations
    assert [(c.family_id, c.fitted) for c in got] == [(FAMILY, True), (files[1]["family_id"], False)]
    for bad in (files[::-1], [files[0] | {"family_id": "uncalibrated"}]):  # unsorted; not a family id
        doc["calibrations"] = bad
        with pytest.raises(ContractValidationError):
            _read("bench_manifest", doc, tmp_path)
