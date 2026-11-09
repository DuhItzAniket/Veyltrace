"""Golden tests of the engine atoms on hand-made inputs (06 §3.4, §7).

The synth anomalies stay empty until Anomara's detectors land, so the atom logic is pinned here.
Each `fixtures/handmade/<case>/` holds `inputs.json` (contract name -> rows; "_" keys are comments),
written through io.write so the inputs are contract-valid on every run, and `evidence.main.txt`,
the expected evidence's canonical content (what assert_golden compares, D-16). Refresh after review:
`VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/faultloom/tests/test_handmade.py`.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from veyltrace_core import io, textio
from veyltrace_core.context import RunContext
from veyltrace_core.testing import content_lines, make_context
from veyltrace_faultloom.api import run

HANDMADE = Path(__file__).resolve().parents[1] / "fixtures" / "handmade"
CASES = tuple(sorted(p.name for p in HANDMADE.iterdir() if p.is_dir()))
GOLDEN = "evidence.main.txt"
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"


def _run_dir(case: str, tmp_path: Path) -> Path:
    inputs = json.loads((HANDMADE / case / "inputs.json").read_text(encoding="utf-8"))
    for name in sorted(n for n in inputs if not n.startswith("_")):
        io.write(name, inputs[name], tmp_path)
    return tmp_path


def _ctx(run_dir: Path, overrides: Mapping[str, Any] | None = None) -> RunContext:
    # ctx.dataset comes from the manifest, as in the pipeline: downstream Causentra checks it.
    manifest = json.loads(io.path_of("case_manifest", run_dir).read_text(encoding="utf-8"))
    return make_context("faultloom", run_dir, dataset=str(manifest["dataset"]), overrides=overrides or {})


@pytest.mark.parametrize("case", CASES)
def test_evidence_matches_the_handmade_golden(tmp_path: Path, case: str) -> None:
    run_dir = _run_dir(case, tmp_path)
    assert run(_ctx(run_dir)).status == "ok"
    actual = content_lines("evidence", io.path_of("evidence", run_dir))
    golden = HANDMADE / case / GOLDEN
    if os.environ.get(UPDATE_ENV) == "1":
        assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
        textio.write_bytes(golden, "".join(f"{line}\n" for line in actual).encode("utf-8"))
    assert golden.read_text(encoding="utf-8").splitlines() == actual


@pytest.fixture
def anomaly_dir(tmp_path: Path) -> Path:
    return _run_dir("cpu-hog", tmp_path)


def _evidence(run_dir: Path) -> list[dict[str, object]]:
    return io.read_table("evidence", run_dir, validate=True).to_pylist()


def test_robust_z_atoms_recover_the_max_score_norm(anomaly_dir: Path) -> None:
    # 06 §7: log1p(value) = max score_norm of the refs (09 §3.8), to 1 ulp: libm log1p differs by OS.
    metrics = run(_ctx(anomaly_dir)).metrics
    assert (metrics["atoms.internal_anomaly"], metrics["atoms.external_anomaly"]) == (6, 2)
    anomalies = io.read_table("anomalies", anomaly_dir).to_pylist()
    norm = {(r["series_id"], r["detector"]): r["score_norm"] for r in anomalies}
    robust = [a for a in _evidence(anomaly_dir) if '"detector":"robust_z"' in str(a["args_json"])]
    assert len(robust) == 6
    for atom in robust:
        refs = atom["refs"]
        assert isinstance(refs, list) and isinstance(atom["value"], float)
        assert math.isclose(math.log1p(atom["value"]), max(norm[r, "robust_z"] for r in refs), rel_tol=1e-12)


def test_external_graph_nodes_get_atoms_only_inside_the_universe(anomaly_dir: Path) -> None:
    run(_ctx(anomaly_dir))
    assert "card-gateway.example" not in {a["candidate"] for a in _evidence(anomaly_dir)}
    run(_ctx(anomaly_dir, {"core.universe.include_external": True}))
    assert "card-gateway.example" in {a["candidate"] for a in _evidence(anomaly_dir)}
