"""Slate-scored methods (04 §3 `causatrix:<ranker>` and `causatrix:rrf`; 07 §9; #172).

A `kind: causatrix` method runs the pipeline and is scored on Causatrix's slate, not on Causentra's
verdict: ranks are the top-K candidates as `{service}_{indicator}`, then the rest of U in
`all_scores` order. It shares a run with `veyltrace:off` when their configs are equal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_bench import runner
from veyltrace_contracts.models import Slate
from veyltrace_core import cli, io, textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import case_id

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "bench" / "experiments" / "synth-smoke.yaml"
EXAMPLE = ROOT / "contracts" / "examples" / "slate.example.json"
OFF = '  - {id: "veyltrace:off", kind: veyltrace, ai: {mode: "off"}, overrides: {}}\n'
RRF = '  - {id: "causatrix:rrf", kind: causatrix, ai: {mode: "off"}, overrides: {}}\n'
BARO = '  - {id: "causatrix:baro_rs", kind: causatrix, overrides: {causatrix.rankers.enabled: [baro_rs]}}\n'


def _slate(**changes: object) -> Slate:
    return Slate.model_validate(json.loads(textio.read_text(EXAMPLE)) | changes)


def test_slate_ranks_are_the_top_k_then_the_rest_of_u() -> None:
    slate = _slate()
    ranks = runner.slate_ranks(slate)
    top = [f"{c.service}_{c.indicator}" for c in slate.candidates]
    rest = [s.service for s in slate.all_scores if s.service not in {c.service for c in slate.candidates}]
    assert list(ranks) == [*top, *rest] and top and rest
    assert len({r.split("_")[0] for r in ranks}) == len(ranks)  # every service once, coarse or fine


def test_slate_scored_output_has_no_verifier_channels() -> None:
    out = runner.method_output("ok", None, _slate(), slate_scored=True)
    assert out.ranks == runner.slate_ranks(_slate()) and not out.has_verdict
    assert (out.pool, out.candidate_set, out.root_fault_class) == (None, None, None)
    empty = runner.method_output("ok", None, _slate(rankers_active=[], candidates=[]), slate_scored=True)
    assert empty.rankers_active == () and empty.slate == ()  # no ranker voted: unranked (04 §7)
    assert runner.method_output("failed", None, None, slate_scored=True).ranks == ()


def _experiment(tmp_path: Path, methods: str) -> Path:
    cases = tmp_path / "cases.yaml"
    cases.write_text(f"[{case_id('synth-01')}]\n", encoding="utf-8")
    text = textio.read_text(SMOKE).replace("cases: all", f"cases: {json.dumps(cases.as_posix())}")
    exp = tmp_path / "exp.yaml"
    exp.write_text(text.replace(OFF, methods), encoding="utf-8")
    return exp


def test_rankers_alone_and_rrf_run_on_synth(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = _experiment(tmp_path, OFF + RRF + BARO)
    out, summary = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows = {str(r["method"]): r for r in table.to_pylist()}
    assert sorted(rows) == ["causatrix:baro_rs", "causatrix:rrf", "veyltrace:off"]
    assert all(rows[m]["run_outcome"] == "ok" for m in rows)
    assert rows["veyltrace:off"]["status"] is not None
    for method in ("causatrix:rrf", "causatrix:baro_rs"):  # scored on the slate: no verdict columns
        assert rows[method]["status"] is None and rows[method]["verdict_hash"] is None
        assert rows[method]["pool_hit"] is None and rows[method]["in_set"] is None
    assert rows["causatrix:rrf"]["wall_ms"] == rows["veyltrace:off"]["wall_ms"]  # one run, scored twice
    groups = summary["groups"]
    assert isinstance(groups, list) and sorted(g["method"] for g in groups) == sorted(rows)


def test_a_duplicated_method_is_still_refused(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    dup = OFF.replace('"veyltrace:off"', '"veyltrace:again"')
    with pytest.raises(ConfigError, match="reuses run"):
        runner.run_experiment(
            _experiment(tmp_path, OFF + dup), out_root=tmp_path / "r", runs_root=tmp_path / "runs"
        )
