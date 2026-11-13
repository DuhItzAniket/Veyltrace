"""Infralume's engine step (01 §3.1, §7): synth goldens, FR-4 source drops, hint blanking, cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.adapters import TELEMETRY_CONTRACTS
from veyltrace_core.config import data_root
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.testing import SYNTH_CASES, VARIANTS, assert_golden, golden_path, make_context
from veyltrace_infralume.api import run
from veyltrace_infralume.cache import CACHE_DIR

CASES = (*SYNTH_CASES, *sorted(VARIANTS))
CONTRACTS = ("case_manifest", *TELEMETRY_CONTRACTS.values())
KEY = "re2ob_cartservice_cpu_1"  # the Hugging Face tree of conftest.py


def _synth(case: str, run_dir: Path, **overrides: Any) -> tuple[models.CaseManifest, dict[str, Any]]:
    variant = VARIANTS.get(case)
    key = case if variant is None or variant.generator else variant.base_case  # update_golden's rule
    ctx = make_context(
        "infralume", run_dir, case_id=make_case_id(key),
        overrides={**(variant.overrides if variant else {}), **overrides},
    )  # fmt: skip
    result = run(ctx)
    assert result.status == "ok"
    manifest = io.read_unredacted("case_manifest", run_dir)
    assert isinstance(manifest, models.CaseManifest)
    return manifest, dict(result.metrics)


@pytest.mark.parametrize("case", CASES)
def test_matches_golden(tmp_path: Path, case: str) -> None:
    _synth(case, tmp_path)
    # golden() redacts the hint (D-15); the manifest is compared as bytes, hint included.
    written = io.path_of("case_manifest", tmp_path).read_bytes()
    assert written == golden_path("case_manifest", case).read_bytes(), case
    for contract in TELEMETRY_CONTRACTS.values():
        assert_golden(io.path_of(contract, tmp_path), contract, case)


@pytest.mark.parametrize(
    ("variant", "kept"),
    [("synth-01@metrics", "metrics"), ("synth-01@logs", "logs"), ("synth-01@traces", "traces"),
     ("synth-01@events", "events")],
)  # fmt: skip
def test_single_source_variants(tmp_path: Path, variant: str, kept: str) -> None:
    manifest, metrics = _synth(variant, tmp_path)
    assert {s for s, on in manifest.sources.model_dump().items() if on} == {kept}
    rows = {s: io.read_table(c, tmp_path).num_rows for s, c in TELEMETRY_CONTRACTS.items()}
    assert {("traces" if s == "spans" else s) for s, n in rows.items() if n} == {kept}
    assert metrics == {f"rows_{s}": n for s, n in rows.items()}  # dropped sources report 0 rows
    if kept == "events":
        assert manifest.services == []  # event entities are not telemetry services (01 §3.8)


def test_detected_protocol_blanks_the_hint(tmp_path: Path) -> None:
    manifest, _ = _synth("synth-01", tmp_path, **{"core.alert.protocol": "detected"})
    assert (manifest.t_alert_hint_ns, manifest.hint_source) == (None, "none")


def test_unknown_source_drop_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="spans"):
        _synth("synth-01", tmp_path, **{"infralume.sources.drop": ["spans"]})


def _rcaeval(run_dir: Path) -> dict[str, bytes]:
    ctx = make_context("infralume", run_dir, case_id=make_case_id(KEY), dataset="re2-ob")
    assert run(ctx).status == "ok"
    return {c: io.path_of(c, run_dir).read_bytes() for c in CONTRACTS}


def test_rcaeval_runs_through_the_cache(tmp_path: Path, hf_case: Path) -> None:
    first = _rcaeval(tmp_path / "a")
    entries = sorted((data_root() / CACHE_DIR / "re2-ob" / make_case_id(KEY)).iterdir())
    assert len(entries) == 1 and (entries[0] / "case.json").is_file()
    (hf_case / "metrics.parquet").unlink()  # the second run must not need the raw files
    assert _rcaeval(tmp_path / "b") == first
    manifest = io.read_unredacted("case_manifest", tmp_path / "b")
    assert isinstance(manifest, models.CaseManifest) and manifest.dataset == "re2-ob"
    assert [i.name for i in manifest.inputs] == [
        "logs/logs.parquet",
        "metrics/metrics.parquet",
        "traces/traces.parquet",
    ]
