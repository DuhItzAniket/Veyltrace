"""scripts/explain/rq6_replay.py (X-08 #41): a FakeProvider recording on synth (08 §7, as bench's
RQ6 test), its recording result under another host name and its kept runs zipped as the release
asset; the script replays them through the real CLI in child processes, with no model call."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from veyltrace_bench import ai_arms, replay, runner
from veyltrace_core import cli, pipeline, textio
from veyltrace_core.config import CONFIG_DIR_ENV

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "explain" / "rq6_replay.py"
GGUF = "ab" * 32  # a test digest, as bench/tests/test_replay.py
EID = "synth-rq6-site"
EXPERIMENT = f"""\
experiment_id: {EID}
description: "RQ6 second-laptop replay on synth (never reported)"
dataset: {{parts: [synth], cases: all, exclude: null, normal_windows: none}}
split: {{family: null, scheme: none}}
protocol: {{alert: oracle, shift_s: 0, sources_drop: []}}
methods:
  - id: "veyltrace:brief"
    kind: veyltrace
    ai: {{mode: record, relentra_mode: brief, model: qwen3.5-9b-q4_k_m, seeds: [1]}}
calibration: {{fit: false}}
metrics: [ac_at_k]
resources: {{workers: 1, timeout_s: 600}}
"""
N_RUNS = 5  # synth-01..05, one seed


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("veyltrace_rq6_replay", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__["VEYLTRACE"] = [sys.executable, "-m", "veyltrace_core.cli"]  # not `uv run`
    return module


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    base = tmp_path_factory.mktemp("rq6-site")
    config = base / "repo" / "config"
    shutil.copytree(ROOT / "config", config)
    llm = config / "llm.yaml"
    text = textio.read_text(llm).replace("provider: ollama", "provider: fake")
    text = re.sub(r"(?m)^(\s*gguf_sha256:).*$", rf'\1 "{GGUF}"', text)
    textio.write_bytes(llm, text.encode())
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(CONFIG_DIR_ENV, str(config))
        mp.setattr(runner, "IN_PROCESS", True)
        assert cli.main(["data", "fetch", "synth"]) == 0
        root, path = base / "rec", base / f"{EID}.yaml"
        textio.write_bytes(path, EXPERIMENT.encode())
        runner.run_experiment(path, out_root=root / "results", runs_root=root / "runs")
        with pytest.MonkeyPatch.context() as host:
            host.setattr("platform.node", lambda: "the-recording-host")
            replay.replay(root / "results", root / "runs", replay.RECORDING)
        yield root


def _archive(runs: Path, to: Path) -> Path:  # bench-ai/ at the top, as the release asset
    return Path(shutil.make_archive(str(to / "bench-ai-r16"), "zip", root_dir=runs, base_dir=ai_arms.KEPT))


def _argv(rec: Path, archive: Path, site: Path, *extra: str) -> list[str]:
    return [
        "--commit", "HEAD", "--checkout", str(ROOT), "--skip-sync", "--no-table",
        "--archive", str(archive), "--runs-root", str(site), "--results", str(rec / "results"),
        *extra,
    ]  # fmt: skip


def test_constants_follow_core_and_bench() -> None:
    rq6 = _load()
    assert (rq6.DIRTY_PATHS, rq6.DIRTY_EXCLUDES) == (pipeline.DIRTY_PATHS, pipeline.DIRTY_EXCLUDES)
    assert (rq6.KEPT, rq6.ROLE) == (ai_arms.KEPT, replay.SECOND)
    assert (rq6.REPLAY_DIR, rq6.RECORDING, rq6.SUMMARY, rq6.CSV, rq6.MANIFEST) == (
        replay.REPLAY_DIR, replay.RECORDING, replay.SUMMARY, replay.CSV, replay.MANIFEST,
    )  # fmt: skip
    assert rq6.dry_run_count("x\nruns: 801, bytes: 12345\n") == (801, 12345)


def test_one_command_replays_every_recorded_run(
    recorded: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rq6 = _load()
    rec = Path(shutil.copytree(recorded, tmp_path / "rec"))
    archive = _archive(rec / "runs", tmp_path)
    site = tmp_path / "site-runs"
    size = replay.run_dirs_bytes(replay.recorded_runs(rec / "results").values(), rec / "runs" / ai_arms.KEPT)
    assert rq6.main(_argv(rec, archive, site, "--expect-bytes", str(size))) == rq6.OK
    out = capsys.readouterr().out
    assert f"Tier 1 on second-laptop: {N_RUNS}/{N_RUNS} replayed with exit 0 (rate 1.0" in out
    assert "not replayed" not in out
    got, mine = (
        rq6.read_json(rec / "results" / "replay" / r / "replay_summary.json")
        for r in (rq6.ROLE, rq6.RECORDING)
    )
    assert (got["tier1"]["n"], got["tier1"]["k"], got["tier1"]["k_verdict"]) == (N_RUNS, N_RUNS, N_RUNS)
    assert got["site"]["host_id"] != mine["site"]["host_id"]
    assert len(list((site / "bench-ai").rglob("receipt.json"))) == N_RUNS  # extracted from the zip


def test_a_changed_cassette_is_named_and_fails(
    recorded: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rq6 = _load()
    rec = Path(shutil.copytree(recorded, tmp_path / "rec"))
    changed = sorted((rec / "runs" / "bench-ai").rglob("receipt.json"))[0].parent
    entry = sorted(p for p in (changed / "cassette").rglob("*") if p.is_file())[0]
    textio.write_bytes(entry, textio.read_bytes(entry) + b" ")
    archive = _archive(rec / "runs", tmp_path)
    assert rq6.main(_argv(rec, archive, tmp_path / "site-runs")) == rq6.FAILED
    out = capsys.readouterr().out
    assert f"{N_RUNS - 1}/{N_RUNS} replayed with exit 0" in out
    where = f"{changed.parent.parent.name}/{changed.parent.name} {changed.name}"
    assert f"not replayed: {where} exit=3" in out  # 10 §3.9 R6: inputs changed


def test_refused_before_any_replay(recorded: Path, tmp_path: Path) -> None:
    rq6 = _load()
    rec = Path(shutil.copytree(recorded, tmp_path / "rec"))
    archive = _archive(rec / "runs", tmp_path)
    second = rec / "results" / "replay" / "second-laptop"
    # the extracted runs differ from the recording host's (its --dry-run bytes)
    assert rq6.main(_argv(rec, archive, tmp_path / "a", "--expect-bytes", "1")) == rq6.REFUSED
    assert not second.exists()
    # an archive member that would land outside the runs root
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../outside.txt", "x")
    assert rq6.main(_argv(rec, evil, tmp_path / "b")) == rq6.REFUSED
    assert not (tmp_path / "outside.txt").exists()
    # no committed recording result at the results commit
    shutil.rmtree(rec / "results" / "replay" / "recording")
    assert rq6.main(_argv(rec, archive, tmp_path / "d")) == rq6.REFUSED
    assert not second.exists()
