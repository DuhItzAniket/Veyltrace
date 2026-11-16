"""Golden tests of the v1 slate on hand-made inputs (07 §3.7, §7; the R-06 pattern of FaultLoom).

The synth evidence stays empty until Anomara's detectors land, so the ranking is pinned here. Each
`fixtures/handmade/<case>/` holds `inputs.json` (contract name -> rows; "_" keys are comments),
written through io.write so the inputs are contract-valid on every run, and `slate.txt`, the
expected slate's canonical content. Refresh after review:
`VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/causatrix/tests/test_handmade.py`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from veyltrace_causatrix.api import NO_VOTE_NOTE, run
from veyltrace_contracts import models
from veyltrace_core import io, textio
from veyltrace_core.context import RunContext
from veyltrace_core.testing import content_lines, make_context

HANDMADE = Path(__file__).resolve().parents[1] / "fixtures" / "handmade"
CASES = tuple(sorted(p.name for p in HANDMADE.iterdir() if p.is_dir()))
GOLDEN = "slate.txt"
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"


def _run_dir(case: str, tmp_path: Path) -> Path:
    inputs = json.loads((HANDMADE / case / "inputs.json").read_text(encoding="utf-8"))
    for name in sorted(n for n in inputs if not n.startswith("_")):
        io.write(name, inputs[name], tmp_path)
    return tmp_path


def _ctx(run_dir: Path, overrides: Mapping[str, Any] | None = None) -> RunContext:
    return make_context("causatrix", run_dir, dataset="handmade", overrides=overrides or {})


def _slate(case: str, tmp_path: Path, overrides: Mapping[str, Any] | None = None) -> models.Slate:
    run_dir = _run_dir(case, tmp_path)
    assert run(_ctx(run_dir, overrides)).status == "ok"
    return io.read_model("slate", run_dir, models.Slate, validate=True)


@pytest.mark.parametrize("case", CASES)
def test_slate_matches_the_handmade_golden(tmp_path: Path, case: str) -> None:
    run_dir = _run_dir(case, tmp_path)
    assert run(_ctx(run_dir)).status == "ok"
    actual = content_lines("slate", io.path_of("slate", run_dir))
    golden = HANDMADE / case / GOLDEN
    if os.environ.get(UPDATE_ENV) == "1":
        assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
        textio.write_bytes(golden, "".join(f"{line}\n" for line in actual).encode("utf-8"))
    assert golden.read_text(encoding="utf-8").splitlines() == actual


def test_worked_example_reproduces_07_3_7(tmp_path: Path) -> None:
    slate = _slate("worked-example", tmp_path, {"causatrix.slate.k": 2})
    assert slate.k == 2  # the slate.k override (the synth slate is empty, so it is checked here)
    assert slate.rankers_active == ["baro_rs", "cp_sbfl", "graph_walk", "nsigma", "prism_m"]
    first, second = slate.candidates
    assert (first.service, first.mode, first.fault_class, first.indicator) == (
        "checkout",
        "resource",
        "cpu",
        "cpu",
    )
    assert (second.service, second.mode, second.indicator) == ("frontend", "network", "latency")
    assert round(first.fused_score, 9) == 0.081438392 and round(second.fused_score, 9) == 0.081173982
    assert first.ranker_ranks == {
        "baro_rs": 2,
        "change_prox": None,
        "cp_sbfl": 1,
        "graph_walk": 1,
        "nsigma": 2,
        "prism_m": 1,
    }
    assert [s.service for s in slate.all_scores] == ["checkout", "frontend", "currency", "payment"]


def test_no_vote_gives_an_empty_slate_over_u(tmp_path: Path) -> None:
    run_dir = _run_dir("no-vote", tmp_path)
    result = run(_ctx(run_dir))
    slate = io.read_model("slate", run_dir, models.Slate, validate=True)
    assert (slate.candidates, slate.rankers_active, result.notes) == ([], [], (NO_VOTE_NOTE,))
    assert [(s.service, s.fused_score) for s in slate.all_scores] == [
        ("cart", 0.0),
        ("frontend", 0.0),
        ("payment", 0.0),
    ]
    assert set(slate.fusion.weights) == {
        "baro_rs",
        "change_prox",
        "cp_sbfl",
        "graph_walk",
        "nsigma",
        "prism_m",
    }


@pytest.mark.parametrize("ranker", ["baro_rs", "change_prox", "graph_walk", "nsigma", "prism_m"])
def test_each_ranker_alone_through_the_engine(tmp_path: Path, ranker: str) -> None:
    # Bench's causatrix:<ranker> method (07 §9): only that ranker votes and the slate follows its ranks.
    slate = _slate("change-silence-code", tmp_path, {"causatrix.rankers.enabled": [ranker]})
    assert slate.rankers_active == [ranker]
    assert list(slate.fusion.weights) == [ranker]
    ranks = [c.ranker_ranks[ranker] for c in slate.candidates]
    assert ranks == sorted(r for r in ranks if r is not None)
