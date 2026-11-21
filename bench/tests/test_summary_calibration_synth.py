"""The bench_summary 1.2 entries end to end on synth (#405): a copy of synth-smoke that lists every
new metric runs, its summary validates as 1.2, and each entry agrees with the per_case rows it was
computed from. Outputs go to tmp_path, never into bench/results (04 §3)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_bench import runner
from veyltrace_contracts.models import BenchManifest, BenchSummary
from veyltrace_core import cli, io, textio

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "synth-smoke.yaml"
LISTED = "metrics: [ac_at_k, avg_at_5, mrr, fine_ac_at_k, retrieval_at_k, chance, lift]"
NEW = (
    "coverage", "set_size", "no_fault_rates", "risk_coverage", "selective_accuracy",
    "decoy_top1_change", "permutation_invariance",
)  # fmt: skip


def test_the_synth_summary_holds_every_new_entry(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    text = textio.read_text(SMOKE)
    assert LISTED in text
    exp = tmp_path / "synth-entries.yaml"
    listed = text.replace(LISTED, f"metrics: [ac_at_k, {', '.join(NEW)}]")
    exp.write_text(listed, encoding="utf-8", newline="\n")
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "results", runs_root=tmp_path / "runs")
    summary = io.read_path("bench_summary", out / "summary.json", validate=True)
    manifest = io.read_path("bench_manifest", out / "manifest.json", validate=True)
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(summary, BenchSummary) and isinstance(table, pa.Table)
    assert isinstance(manifest, BenchManifest) and manifest.calibrations == []  # synth is uncalibrated (#412)
    rows: list[dict[str, object]] = table.to_pylist()
    fault = [r for r in rows if r["hit_at_1"] is not None]  # synth-01..04; synth-05 has no truth
    normal = [r for r in rows if r["hit_at_1"] is None]
    (group,) = summary.groups
    m = group.metrics
    assert m.mrr is None and m.ac_at_k is not None  # only the listed metrics
    assert m.coverage is not None and (m.coverage.n_fault, len(normal)) == (4, 1)
    assert m.coverage.coverage == sum(r["in_set"] is True for r in fault) / 4 and m.coverage.by_fold == []
    sizes = [int(str(r["set_size"])) for r in fault if r["set_size"] is not None]
    assert m.set_size is not None and m.set_size.n_set == len(sizes) == 4
    assert m.set_size.set_size_mean == pytest.approx(sum(sizes) / 4)
    assert m.no_fault_rates is not None and m.no_fault_rates.n_normal == 1
    assert m.no_fault_rates.false_alarm_rate == (0.0 if normal[0]["status"] == "NO_FAULT" else 1.0)
    confirmed = [r for r in fault if r["status"] == "CONFIRMED"]
    assert m.selective_accuracy is not None
    assert m.selective_accuracy.answer_rate_confirmed == len(confirmed) / 4
    risk = m.risk_coverage
    assert risk is not None and risk.n_fault == 4 and None not in (risk.aurc_verdict, risk.aurc_fused)
    assert m.decoy_top1_change is not None and m.permutation_invariance is not None
    assert (m.decoy_top1_change.n_pairs, m.permutation_invariance.n_cases) == (0, 0)  # no proposal variants
