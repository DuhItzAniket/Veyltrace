"""RQ6 replay results (`veyltrace bench replay`, CCR #440; ADR 20261122-ak-rq6-replay-results).

Synth runs, AI off plus a FakeProvider record arm (the config copy sets llm.provider fake, 08 §7,
and pins a test GGUF digest, #315), so the kept record runs have real receipts and cassettes.
One module fixture runs the experiments; a test that changes runs works on a copy.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pytest

from veyltrace_bench import cli as bench_cli
from veyltrace_bench import replay, runner
from veyltrace_contracts.models import BenchReplaySummary
from veyltrace_core import cli, io, textio
from veyltrace_core.config import CONFIG_DIR_ENV
from veyltrace_core.errors import ArtifactMissing, ConfigError, UsageError
from veyltrace_stats.exact import clopper_pearson

REPO = Path(__file__).resolve().parents[2]
GGUF = "ab" * 32
EXPERIMENT = """\
experiment_id: {eid}
description: "RQ6 replay on synth (never reported)"
dataset: {{parts: [synth], cases: all, exclude: null, normal_windows: none}}
split: {{family: null, scheme: none}}
protocol: {{alert: oracle, shift_s: 0, sources_drop: []}}
methods:
  - {{id: "veyltrace:off", kind: veyltrace, ai: {{mode: "off"}}, overrides: {{}}}}
  - id: "veyltrace:brief"
    kind: veyltrace
    ai: {{mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1]}}
calibration: {{fit: false}}
metrics: [ac_at_k]
resources: {{workers: 1, timeout_s: 600}}
"""
FIRST, SECOND = "synth-replay-a", "synth-replay-b"  # b replays a's kept runs (ai_mode replay rows)


@dataclass(frozen=True)
class Recorded:
    root: Path  # holds results/ and runs/

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    def copy(self, to: Path) -> Recorded:
        shutil.copytree(self.root, to)
        return Recorded(to)


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Recorded]:
    base = tmp_path_factory.mktemp("rq6")
    config = base / "repo" / "config"
    shutil.copytree(REPO / "config", config)
    llm = config / "llm.yaml"
    text = textio.read_text(llm).replace("provider: ollama", "provider: fake")
    lines = [
        f'  gguf_sha256: "{GGUF}"' if ln.strip().startswith("gguf_sha256:") else ln
        for ln in text.splitlines()
    ]
    textio.write_bytes(llm, ("\n".join(lines) + "\n").encode())
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(CONFIG_DIR_ENV, str(config))
        mp.setattr(runner, "IN_PROCESS", True)
        assert cli.main(["data", "fetch", "synth"]) == 0
        root = base / "rec"
        for eid in (FIRST, SECOND):
            path = base / f"{eid}.yaml"
            textio.write_bytes(path, EXPERIMENT.format(eid=eid).encode())
            runner.run_experiment(path, out_root=root / "results", runs_root=root / "runs")
        yield Recorded(root)


def _rows(out: Path) -> list[dict[str, Any]]:
    table = cast("pa.Table", io.read_path("bench_replay", out / replay.CSV, validate=True))
    return table.to_pylist()


def _summary(out: Path) -> BenchReplaySummary:
    return cast(
        "BenchReplaySummary", io.read_path("bench_replay_summary", out / replay.SUMMARY, validate=True)
    )


def _kept(rec: Recorded) -> list[Path]:
    return sorted(p.parent for p in (rec.runs / "bench-ai").rglob("receipt.json"))


def test_recording_replays_each_kept_run_once(recorded: Recorded, tmp_path: Path) -> None:
    rec = recorded.copy(tmp_path / "r")
    out = replay.replay(rec.results, rec.runs, replay.RECORDING)
    assert isinstance(out, Path) and out == rec.results / "replay" / "recording"
    rows = _rows(out)
    kept = _kept(rec)
    assert len(rows) == len(kept) == 5  # one per synth case: b's replay rows map to a's record runs
    assert {r["run_id"] for r in rows} == {p.name for p in kept}
    assert all(r["experiments"] == [FIRST, SECOND] for r in rows)  # AI-off rows are never replayed
    assert all(r["exit_code"] == 0 and r["verdict_hash_replayed"] == r["verdict_hash"] for r in rows)
    assert all(r["trace_match"] and r["card_match"] and r["env_drift"] == [] for r in rows)
    s = _summary(out)
    assert s.tier2 is None and s.tier1 is not None and (s.tier1.n, s.tier1.k, s.tier1.k_verdict) == (5, 5, 5)
    ci = clopper_pearson(5, 5)
    assert (s.tier1.rate, s.tier1.ci_low, s.tier1.ci_high) == pytest.approx((1.0, ci.low, ci.high), abs=1e-9)
    assert s.tier1.outcomes.f_0 == 5 and s.tier1.excluded.failed == 0
    assert [(e.experiment_id, e.n, e.k) for e in s.tier1.by_experiment] == [(FIRST, 5, 5), (SECOND, 5, 5)]
    assert [x.experiment_id for x in s.sources] == [FIRST, SECOND] and s.site.ci_run_url is None


def test_a_missing_receipt_and_a_changed_cassette_are_rows(recorded: Recorded, tmp_path: Path) -> None:
    rec = recorded.copy(tmp_path / "r")
    gone, changed = _kept(rec)[:2]
    (gone / "receipt.json").unlink()
    cassette = sorted(p for p in (changed / "cassette").rglob("*") if p.is_file())[0]
    textio.write_bytes(cassette, textio.read_bytes(cassette) + b" ")
    out = replay.replay(rec.results, rec.runs, replay.RECORDING)
    assert isinstance(out, Path)
    by_id = {r["run_id"]: r for r in _rows(out)}
    assert (by_id[gone.name]["exit_code"], by_id[gone.name]["reason"]) == (None, "no_receipt")
    assert by_id[changed.name]["exit_code"] == 3  # 10 §3.9 R6: inputs changed
    t1 = _summary(out).tier1
    assert t1 is not None and (t1.n, t1.k) == (5, 3) and (t1.outcomes.no_receipt, t1.outcomes.f_3) == (1, 1)


def test_dry_run_counts_runs_and_bytes_and_writes_nothing(recorded: Recorded) -> None:
    got = replay.replay(recorded.results, recorded.runs, replay.RECORDING, dry_run=True)
    assert isinstance(got, tuple) and got[0] == 5 and got[1] > 0
    assert not (recorded.results / "replay").exists()


def test_other_sites_replay_the_recording_runs(
    recorded: Recorded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = recorded.copy(tmp_path / "r")
    with pytest.raises(ArtifactMissing):
        replay.replay(rec.results, rec.runs, replay.SECOND)  # no recording result yet
    replay.replay(rec.results, rec.runs, replay.RECORDING)
    with pytest.raises(UsageError, match="recording host"):
        replay.replay(rec.results, rec.runs, replay.SECOND)
    monkeypatch.setattr("platform.node", lambda: "another-laptop")
    out = replay.replay(rec.results, rec.runs, replay.SECOND)
    assert isinstance(out, Path) and out.name == "second-laptop"
    assert [r["run_id"] for r in _rows(out)] == [
        r["run_id"] for r in _rows(rec.results / "replay" / "recording")
    ]
    with pytest.raises(UsageError, match="GitHub Actions"):
        replay.replay(rec.results, rec.runs, replay.CI)
    for k, v in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "7",
    }.items():
        monkeypatch.setenv(k, v)
    ci = replay.replay(rec.results, rec.runs, replay.CI)
    assert isinstance(ci, Path) and _summary(ci).site.ci_run_url == "https://github.com/o/r/actions/runs/7"


def test_results_from_another_commit_are_refused(recorded: Recorded, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"commit": "0" * 40, "dirty": False, "bench_dirty": False}
    monkeypatch.setattr(replay, "code_state", lambda _repo: state)
    with pytest.raises(ConfigError, match="not the code of these results"):
        replay.replay(recorded.results, recorded.runs, replay.RECORDING)


def test_cli_dry_run(recorded: Recorded, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["replay", "--role", "recording", "--dry-run", "--results", str(recorded.results)]
    assert bench_cli.main([*argv, "--runs-root", str(recorded.runs)]) == 0
    assert capsys.readouterr().out.startswith("runs: 5, bytes: ")
    assert json.loads(textio.read_text(recorded.results / FIRST / "manifest.json"))["experiment_id"] == FIRST
