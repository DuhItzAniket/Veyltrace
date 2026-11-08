"""pipeline: run-dir layout, sub-step order, outcomes, manifest, caching, partial runs and reuse.

Engines are in-test fakes registered by patching `plugins.discover`, so these tests never depend
on the engine stubs or the real engines. The fakes write placeholder bytes at their contract
paths (the pipeline only checks that reported hashes match the files), except Infralume, which
writes a valid case_manifest and empty telemetry because core reads them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts.models import CaseManifest, RunManifest
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import plugins, textio
from veyltrace_core.adapters import AlertDetection, TelemetryTables
from veyltrace_core.canonical import canonical_json
from veyltrace_core.context import AIManifest, EngineResult, RunContext, RunPlan
from veyltrace_core.errors import ConfigError, InputChanged, StepFailed, UsageError
from veyltrace_core.hashing import sha256_bytes, sha256_file
from veyltrace_core.ids import case_id, is_code_commit
from veyltrace_core.pipeline import (
    PARTIAL_SEPARATOR,
    StepEvent,
    code_commit,
    env_info,
    execute,
    find_run,
    is_finished,
    run_case,
    summary_dict,
    write_summary,
)
from veyltrace_core.plugins import Plugin
from veyltrace_core.steps import STEP_NAMES, step

REPO = Path(__file__).resolve().parents[3]
CASE = case_id("synth-01")
NS = 1_000_000_000
T0 = 1_700_000_000_000_000_000
HINT = T0 + 1320 * NS
ENV = {"python": "3.12.0", "os": "linux", "libs": {"numpy": "2.0.0"}, "uv_lock_sha256": "c" * 64}
ENGINES = (
    "infralume",
    "signalyth",
    "anomara",
    "causync",
    "causalith",
    "faultloom",
    "causatrix",
    "relentra",
    "causentra",
    "causivra",
)
Hook = Callable[[RunContext], EngineResult | None]


def _write(ctx: RunContext, rel: str, payload: dict[str, Any]) -> tuple[str, str]:
    data = canonical_json(payload) + b"\n"
    textio.write_bytes(ctx.run_dir / rel, data)
    return rel, sha256_bytes(data)


def _infralume(ctx: RunContext, hint: int | None) -> EngineResult:
    manifest = {
        "schema_version": CONTRACTS["case_manifest"].version,
        "case_id": ctx.case_id,
        "dataset": ctx.dataset,
        "system": "ob",
        "t_alert_hint_ns": hint,
        "hint_source": "oracle" if hint is not None else "none",
        "data_start_ns": T0,
        "data_end_ns": T0 + 1920 * NS,
        "sources": {"metrics": False, "logs": False, "traces": False, "events": False},
        "services": [],
        "inputs": [{"name": "metrics/m.csv", "sha256": "d" * 64, "bytes": 3}],
        "adapter": {"name": "fake", "version": "1"},
        "scrub": {"rules_version": "1", "dropped_attributes": 0, "dropped_rows": 0},
    }
    outputs = [("case_manifest", ctx.write("case_manifest", manifest))]
    for name in step("infralume").outputs[1:]:
        schema = CONTRACTS[name].arrow_schema
        assert schema is not None
        outputs.append((name, ctx.write(name, schema.empty_table())))
    return EngineResult("infralume", "ok", outputs=tuple(outputs))


@dataclass
class Fakes:
    """Fake engines: records every call and lets a test hook any sub-step."""

    hint: int | None = HINT
    hooks: dict[str, Hook] = field(default_factory=lambda: {})
    calls: list[tuple[str, str, str]] = field(default_factory=lambda: [])
    detector: Callable[..., AlertDetection | None] | None = None
    missing: tuple[str, ...] = ()

    def engine(self, name: str) -> Callable[[RunContext], EngineResult]:
        def run(ctx: RunContext) -> EngineResult:
            assert ctx.engine == name
            self.calls.append((ctx.step, ctx.engine, ctx.phase))
            hook = self.hooks.get(ctx.step)
            if hook is not None:
                result = hook(ctx)
                if result is not None:
                    return result
            if ctx.step == "infralume":
                return _infralume(ctx, self.hint)
            return self.placeholders(ctx)

        return run

    def placeholders(self, ctx: RunContext) -> EngineResult:
        s = step(ctx.step)
        outputs = [
            (name, _write(ctx, CONTRACTS[name].path, {"fake": ctx.step, "name": name})[1])
            for name in s.outputs
        ]
        if "card.md" in s.files:
            outputs.append(_write(ctx, "card.md", {"md": True}))
        ai = None
        if ctx.ai_mode == "record" and "cassette/" in s.files:
            _write(ctx, f"cassette/{ctx.step}.json", {"call": ctx.step})
            ai = AIManifest("fake", "fake-model", None, prompts=((f"{ctx.step}.md", "e" * 64),))
        return EngineResult(ctx.engine, "ok", outputs=tuple(outputs), ai_manifest=ai)

    def discover(self, group: str) -> tuple[Plugin, ...]:
        if group == plugins.ENGINES:
            return tuple(
                Plugin(group, n, f"fake:{n}", "fake", (lambda n=n: self.engine(n)))
                for n in ENGINES
                if n not in self.missing
            )
        if group == plugins.ALERT_DETECTORS and self.detector is not None:
            det = self.detector
            return (Plugin(group, "default", "fake:det", "fake", lambda: det),)
        return ()


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    f = Fakes()
    monkeypatch.setattr(plugins, "discover", f.discover)
    return f


def plan(tmp_path: Path, **kw: Any) -> RunPlan:
    base: dict[str, Any] = {
        "dataset": "synth",
        "case": CASE,
        "runs_root": tmp_path / "runs",
        "config_dir": REPO / "config",
        "code_commit": "fixture",
        "env": ENV,
    }
    return RunPlan(**{**base, **kw})


def _manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / "run_manifest.json").read_bytes())


def test_full_run_layout_order_and_manifest(tmp_path: Path, fakes: Fakes) -> None:
    events: list[StepEvent] = []
    summary = execute(plan(tmp_path), progress=events.append)
    assert summary.outcome == "ok" and summary.exit_code == 0 and not summary.cached
    assert summary.run_dir == (tmp_path / "runs" / "synth" / CASE / summary.run_id).resolve()
    assert is_finished(summary.run_dir)
    assert tuple(r.name for r in summary.steps) == STEP_NAMES
    assert [r.engine for r in summary.results][:2] == ["infralume", "core"]
    assert summary.results[STEP_NAMES.index("relentra")].status == "skipped"
    assert set(summary.wall_ms) == set(STEP_NAMES)
    # FaultLoom and Causivra run twice, branching on ctx.phase (D-5).
    assert [c for c in fakes.calls if c[1] in ("faultloom", "causivra")] == [
        ("faultloom", "faultloom", "main"),
        ("faultloom.claim_pass", "faultloom", "claim_pass"),
        ("causivra.card", "causivra", "card"),
        ("causivra.receipt", "causivra", "receipt"),
    ]
    assert ("relentra", "relentra", "main") not in fakes.calls
    started = [e.name for e in events if e.event == "started"]
    assert started == list(STEP_NAMES)

    m = _manifest(summary.run_dir)
    names = [o.name for o in m.outputs]
    assert names == sorted(names)
    assert "config.lock.json" in names and "card.md" in names and "alert.json" in names
    assert not {"run_manifest.json", "receipt.json"} & set(names)
    assert m.config_sha256 == sha256_file(summary.run_dir / "config.lock.json")
    assert (m.code.commit, m.code.dirty) == ("fixture", False)
    assert m.env.python == "3.12.0" and m.uv_lock_sha256 == "c" * 64
    assert [i.name for i in m.inputs] == ["metrics/m.csv"]
    assert [s.name for s in m.steps] == list(STEP_NAMES[:-1])  # ends with manifest
    assert [o.name for o in m.steps[-1].outputs] == ["config.lock.json"]
    assert m.steps[STEP_NAMES.index("relentra")].status == "skipped"
    assert m.ai.mode == "off" and m.ai.prompt_sha256 is None
    evidence = {s.name: [o.sha256 for o in s.outputs if o.name == "evidence.parquet"] for s in m.steps}
    assert evidence["faultloom"] != evidence["faultloom.claim_pass"]
    assert summary.outputs == tuple((o.name, o.sha256) for o in m.outputs)


def test_alert_sees_hint_but_signalyth_does_not(tmp_path: Path, fakes: Fakes) -> None:
    seen: dict[str, int | None] = {}

    def look(ctx: RunContext) -> None:
        value = ctx.read("case_manifest")
        assert isinstance(value, CaseManifest)
        seen[ctx.step] = value.t_alert_hint_ns

    fakes.hooks = {"signalyth": look, "causentra": look}
    summary = execute(plan(tmp_path))
    alert = json.loads((summary.run_dir / "alert.json").read_bytes())
    assert alert["t_alert_ns"] == T0 + 1320 * NS
    assert seen == {"signalyth": None, "causentra": None}


def test_runs_are_byte_identical(tmp_path: Path, fakes: Fakes) -> None:
    a = execute(plan(tmp_path / "a"))
    b = execute(plan(tmp_path / "b"))
    assert a.run_id == b.run_id
    assert (a.run_dir / "run_manifest.json").read_bytes() == (b.run_dir / "run_manifest.json").read_bytes()
    assert a.outputs == b.outputs


def test_finished_run_is_cached_unless_dirty(tmp_path: Path, fakes: Fakes) -> None:
    first = execute(plan(tmp_path))
    n = len(fakes.calls)
    again = execute(plan(tmp_path))
    assert again.cached and again.outputs == first.outputs and len(fakes.calls) == n
    assert find_run(first.run_id, tmp_path / "runs") == first.run_dir
    dirty = "fixture+dirty.0123456789ab"
    d1 = execute(plan(tmp_path, code_commit=dirty))
    assert d1.run_id != first.run_id
    d2 = execute(plan(tmp_path, code_commit=dirty))
    assert not d2.cached and len(fakes.calls) > n
    assert _manifest(d2.run_dir).code.dirty is True


def test_record_refuses_overwrite_without_force(tmp_path: Path, fakes: Fakes) -> None:
    first = execute(plan(tmp_path, ai_mode="record"))
    assert first.outcome == "ok"
    m = _manifest(first.run_dir)
    assert m.ai.mode == "record" and m.ai.provider == "fake" and m.ai.cassette_sha256 is not None
    assert m.ai.prompt_sha256 is not None
    assert (first.run_dir / "cassette" / "relentra.json").is_file()
    assert "cassette/relentra.json" in [o.name for o in m.outputs]
    with pytest.raises(UsageError, match="force_record"):
        execute(plan(tmp_path, ai_mode="record"))
    again = execute(plan(tmp_path, ai_mode="record", force_record=True))
    assert not again.cached and again.run_id == first.run_id


def test_partial_run_dir_and_rerun(tmp_path: Path, fakes: Fakes) -> None:
    summary = execute(plan(tmp_path, to_step="alert"))
    assert summary.run_dir.name == f"{summary.run_id}{PARTIAL_SEPARATOR}alert"
    assert [r.name for r in summary.steps] == ["infralume", "alert"]
    assert not (summary.run_dir / "run_manifest.json").exists()
    assert "alert.json" in [n for n, _ in summary.outputs]
    again = execute(plan(tmp_path, to_step="alert"))
    assert not again.cached  # partial runs are never finished, so they re-run
    full = execute(plan(tmp_path))
    assert full.run_dir.name == full.run_id and summary.run_dir.is_dir()


def test_no_alert_and_rejected_outcomes(tmp_path: Path, fakes: Fakes) -> None:
    fakes.hint = None
    rejected = execute(plan(tmp_path))
    assert (rejected.outcome, rejected.reason, rejected.failed_step) == ("rejected", "no_hint", "alert")
    assert rejected.exit_code == 3
    assert all(r.status == "skipped" for r in rejected.results[2:])
    assert not (rejected.run_dir / "run_manifest.json").exists()

    fakes.detector = lambda *_: None
    no_alert = execute(plan(tmp_path, overrides={"core.alert.protocol": "detected"}))
    assert (no_alert.outcome, no_alert.exit_code, no_alert.failed_step) == ("no_alert", 7, "alert")


def test_detected_protocol_passes_run_config(tmp_path: Path, fakes: Fakes) -> None:
    got: list[Any] = []

    def detector(telemetry: TelemetryTables, manifest: CaseManifest, config: Any) -> AlertDetection:
        got.append((manifest.t_alert_hint_ns, config.engine))
        return AlertDetection(T0 + 1000 * NS, ("frontend",), "latency_p99", 1.0)

    fakes.detector = detector
    fakes.hint = None
    summary = execute(plan(tmp_path, overrides={"core.alert.protocol": "detected"}))
    assert summary.outcome == "ok"
    assert got == [(None, "anomara")]


def test_missing_plugins_fail_before_any_dir(tmp_path: Path, fakes: Fakes) -> None:
    fakes.missing = ("causync",)
    with pytest.raises(ConfigError, match=r"veyltrace\.engines:causync"):
        execute(plan(tmp_path))
    fakes.missing = ()
    with pytest.raises(ConfigError, match="alert_detectors:default"):
        execute(plan(tmp_path, overrides={"core.alert.protocol": "detected"}))
    assert not (tmp_path / "runs").exists()


def test_engine_errors_become_failed_outcomes(tmp_path: Path, fakes: Fakes) -> None:
    def boom(ctx: RunContext) -> EngineResult:
        raise RuntimeError("kaput")

    fakes.hooks = {"causatrix": boom}
    s = execute(plan(tmp_path))
    assert (s.outcome, s.failed_step, s.exit_code) == ("failed", "causatrix", 1)
    assert isinstance(s.error, StepFailed) and "kaput" in (s.reason or "")
    assert s.results[STEP_NAMES.index("causentra")].status == "skipped"
    assert not is_finished(s.run_dir)

    def config_boom(ctx: RunContext) -> EngineResult:
        raise ConfigError("bad key")

    fakes.hooks = {"anomara": config_boom}
    assert execute(plan(tmp_path)).exit_code == 4

    fakes.hooks = {"causync": lambda ctx: EngineResult("causync", "failed", notes=("no events",))}
    s = execute(plan(tmp_path))
    assert (s.outcome, s.failed_step, s.reason) == ("failed", "causync", "no events")

    def misreport(ctx: RunContext) -> EngineResult:
        fakes.placeholders(ctx)
        return EngineResult("causync", "ok", outputs=(("changes", "0" * 64),))

    fakes.hooks = {"causync": misreport}
    s = execute(plan(tmp_path))
    assert s.failed_step == "causync" and "file is" in (s.reason or "")

    fakes.hooks = {"causync": lambda ctx: EngineResult("causync", "ok", outputs=(("changes", "0" * 64),))}
    assert "is missing" in (execute(plan(tmp_path)).reason or "")

    fakes.hooks = {"causync": lambda ctx: EngineResult("causync", "ok", outputs=(("slate", "0" * 64),))}
    assert "does not write" in (execute(plan(tmp_path)).reason or "")


def test_stray_file_fails_manifest_step(tmp_path: Path, fakes: Fakes) -> None:
    def litter(ctx: RunContext) -> None:
        textio.write_bytes(ctx.run_dir / "notes.txt", b"hi")
        (ctx.run_dir / ".duck-tmp").mkdir(exist_ok=True)
        textio.write_bytes(ctx.run_dir / ".duck-tmp" / "spill.bin", b"x")  # ignored scratch

    fakes.hooks = {"causentra": litter}
    s = execute(plan(tmp_path))
    assert s.failed_step == "manifest" and "notes.txt" in (s.reason or "")
    assert ".duck-tmp" not in (s.reason or "")
    fakes.hooks = {}
    with pytest.raises(UsageError, match="refusing to clear"):  # never deletes unknown files
        execute(plan(tmp_path))


def test_reuse_dir_copies_and_checks_hashes(tmp_path: Path, fakes: Fakes) -> None:
    parent = execute(plan(tmp_path))
    out = tmp_path / "derived"
    fakes.calls.clear()
    s = execute(plan(tmp_path, from_step="causentra", reuse_dir=parent.run_dir, out_dir=out))
    assert s.outcome == "ok"
    assert [c[0] for c in fakes.calls] == ["causentra", "causivra.card", "causivra.receipt"]
    m = _manifest(s.run_dir)
    assert [st.name for st in m.steps] == list(STEP_NAMES[:-1])
    assert m.steps[0] == _manifest(parent.run_dir).steps[0]

    tampered = tmp_path / "tampered"
    execute(plan(tmp_path / "t", out_dir=tampered))
    textio.write_bytes(tampered / "slate.json", b"{}\n")
    with pytest.raises(InputChanged, match=r"slate\.json"):
        execute(plan(tmp_path, from_step="causentra", reuse_dir=tampered, out_dir=tmp_path / "d2"))


@pytest.mark.parametrize("from_step", ["causatrix", "relentra", "faultloom.claim_pass"])
def test_reuse_refuses_the_claim_pass_evidence_as_main(tmp_path: Path, fakes: Fakes, from_step: str) -> None:
    """A finished run holds the claim-pass evidence; restarting before claim_pass would feed it to
    steps that need FaultLoom's main version, so it is refused (per-step hashes, critic gap)."""
    parent = execute(plan(tmp_path))
    steps = _manifest(parent.run_dir).steps
    records = {st.name: {f.name: f.sha256 for f in st.outputs} for st in steps}
    assert records["faultloom"]["evidence.parquet"] != records["faultloom.claim_pass"]["evidence.parquet"]
    with pytest.raises(InputChanged, match=r"evidence\.parquet"):
        execute(plan(tmp_path, from_step=from_step, reuse_dir=parent.run_dir, out_dir=tmp_path / "x"))
    with pytest.raises(InputChanged, match=r"evidence\.parquet"):
        execute(plan(tmp_path, from_step=from_step, out_dir=parent.run_dir))


def test_from_step_in_place_keeps_earlier_outputs(tmp_path: Path, fakes: Fakes) -> None:
    first = execute(plan(tmp_path, out_dir=tmp_path / "rd"))
    signal = sha256_file(first.run_dir / "signal_cube" / "series.parquet")
    fakes.calls.clear()
    s = execute(plan(tmp_path, out_dir=tmp_path / "rd", from_step="causentra"))
    assert s.outcome == "ok" and fakes.calls[0][0] == "causentra"
    assert sha256_file(s.run_dir / "signal_cube" / "series.parquet") == signal


def test_run_case_and_summary_json(tmp_path: Path, fakes: Fakes) -> None:
    s = run_case(
        "synth", CASE, runs_root=tmp_path / "runs", config_dir=REPO / "config", code_commit="fixture", env=ENV
    )
    d = summary_dict(s)
    assert d["outcome"] == "ok" and d["exit_code"] == 0 and len(d["steps"]) == 14
    assert d["steps"][1]["name"] == "alert" and d["steps"][1]["engine"] == "core"
    path = tmp_path / "summary.json"
    write_summary(s, path)
    assert json.loads(path.read_bytes())["run_id"] == s.run_id
    assert path.read_bytes() == canonical_json(d) + b"\n"


def test_code_commit_and_env_info() -> None:
    commit, dirty = code_commit()
    assert is_code_commit(commit)
    assert dirty == ("+dirty." in commit or commit == "unknown")
    env = env_info()
    assert set(env) == {"python", "os", "libs"} and "numpy" in env["libs"]
    assert list(env["libs"]) == sorted(env["libs"])


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_dirty_digest_rules(tmp_path: Path) -> None:
    """Lead decision §2.9: which edits make a tree dirty, and that different edits differ."""
    repo = tmp_path / "repo"
    files = {
        "packages/x/a.py": b"a = 1\n",
        "config/core.yaml": b"k: 1\n",
        "config/calibration/c.json": b"{}\n",
        "scripts/s.py": b"s = 1\n",
        "uv.lock": b"lock\n",
        "pyproject.toml": b"[project]\n",
    }
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    head, dirty = code_commit(repo)
    assert not dirty and "+dirty." not in head
    for rel in ("config/calibration/c.json", "scripts/s.py"):  # excluded or outside: clean
        (repo / rel).write_bytes(b"changed\n")
    assert code_commit(repo) == (head, False)
    (repo / "packages/x/a.py").write_bytes(b"a = 2\n")
    first, dirty = code_commit(repo)
    assert dirty and first.startswith(head + "+dirty.")
    assert code_commit(repo / "packages" / "x") == (first, True)  # same from a subdirectory
    (repo / "packages/x/a.py").write_bytes(b"a = 3\n")
    second, _ = code_commit(repo)
    assert second != first  # different edits, different run ids
    (repo / "packages/x/new.py").write_bytes(b"n = 1\n")
    assert code_commit(repo)[0] != second  # untracked files count
    _git(repo, "checkout", "-q", "--", "packages")
    (repo / "packages/x/new.py").unlink()
    assert code_commit(repo) == (head, False)
    (repo / "uv.lock").write_bytes(b"upgraded\n")
    assert code_commit(repo)[1] is True  # a dependency change is dirty too
    outside = tmp_path / "plain"
    outside.mkdir()
    if not any((d / ".git").exists() for d in (outside, *outside.parents)):
        assert code_commit(outside) == ("unknown", True)
