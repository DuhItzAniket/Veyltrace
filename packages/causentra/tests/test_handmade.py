"""Golden tests of the v1 verdict on hand-made inputs (09 §7; the R-06 pattern of FaultLoom).

The synth evidence stays empty until Anomara's detectors land, so the decision is pinned here. Each
`fixtures/handmade/<case>/inputs.json` (contract name -> rows; "_" keys are comments) is written
through io.write; Causatrix then writes the slate from it, Causentra the verdict, compared with
`verdict.txt`. Refresh after review:
`VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/causentra/tests/test_handmade.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from veyltrace_causatrix import api as causatrix
from veyltrace_causentra import api
from veyltrace_contracts import models
from veyltrace_core import io, textio
from veyltrace_core.testing import content_lines, make_context

HANDMADE = Path(__file__).resolve().parents[1] / "fixtures" / "handmade"
CASES = tuple(sorted(p.name for p in HANDMADE.iterdir() if p.is_dir()))
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"


def _verdict(case: str, run_dir: Path) -> models.Verdict:
    inputs = json.loads((HANDMADE / case / "inputs.json").read_text(encoding="utf-8"))
    for name in sorted(n for n in inputs if not n.startswith("_")):
        io.write(name, inputs[name], run_dir)
    assert causatrix.run(make_context("causatrix", run_dir, dataset="handmade")).status == "ok"
    assert api.run(make_context("causentra", run_dir, dataset="handmade")).status == "ok"
    return io.read_model("verdict", run_dir, models.Verdict, validate=True)


@pytest.mark.parametrize("case", CASES)
def test_verdict_matches_the_handmade_golden(tmp_path: Path, case: str) -> None:
    _verdict(case, tmp_path)
    actual = content_lines("verdict", io.path_of("verdict", tmp_path))
    golden = HANDMADE / case / "verdict.txt"
    if os.environ.get(UPDATE_ENV) == "1":
        assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
        textio.write_bytes(golden, "".join(f"{line}\n" for line in actual).encode("utf-8"))
    assert golden.read_text(encoding="utf-8").splitlines() == actual


def test_cpu_hog_is_confirmed(tmp_path: Path) -> None:
    v = _verdict("cpu-hog", tmp_path)
    assert (v.status, v.confidence.level, v.confidence.set_size) == ("CONFIRMED", "high", 1)
    assert v.root is not None and (v.root.service, v.root.mode, v.root.fault_class, v.root.indicator) == (
        "checkout",
        "resource",
        "cpu",
        "cpu",
    )
    top = v.ranked[0]
    assert [(t.id, t.result) for t in top.trials if t.id in ("T1", "T2", "T3", "T4")] == [
        ("T1", "pass"),
        ("T2", "pass"),
        ("T3", "pass"),
        ("T4", "pass"),
    ]
    frontend = next(r for r in v.ranked if r.service == "frontend")
    assert next(t for t in frontend.trials if t.id == "T1").reason == "no_internal_anomaly"
    assert v.asks == [] and v.ranks_rcaeval[0] == "checkout_cpu"


def test_healthy_case_is_no_fault(tmp_path: Path) -> None:
    v = _verdict("healthy", tmp_path)
    assert (v.status, v.root, v.candidate_set, v.asks) == ("NO_FAULT", None, [], [])
    assert (v.confidence.level, v.confidence.set_size) == ("none", 0)
    assert len(v.ranks_rcaeval) == 3  # every service of U, under every status (03 §10)
