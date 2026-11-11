"""05 §13: `--dry-run` prints every command and touches no cluster, process or file."""

import subprocess
from pathlib import Path
from typing import Any

import campaign
import pytest
import up
from vlab import LAB_DIR
from vlab.cluster import load_pins


@pytest.fixture(autouse=True)
def no_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"dry run started a process: {args}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


def _commands(out: str) -> list[str]:
    return [line[2:] for line in out.splitlines() if line.startswith("+ ")]


def test_campaign_dry_run_prints_all_phases_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = campaign.main(["--plan", str(LAB_DIR / "plans" / "x02-smoke.yaml"), "--dry-run",
                          "--captures", str(tmp_path)])  # fmt: skip
    cmds = _commands(capsys.readouterr().out)
    assert code == 0
    assert list(tmp_path.iterdir()) == []
    context = f"kind-{load_pins()['cluster_name']}"
    kubectl = [c for c in cmds if c.startswith("kubectl")]
    assert kubectl and all(c.startswith(f"kubectl --context {context} ") for c in kubectl)
    assert sum("apply -f - <<stdin" in c for c in cmds) == 2
    assert sum(c.startswith("sleep 600") for c in cmds) == 4  # baseline + fault, two entries
    # Every injected fault is deleted again, before the spool is copied out.
    for kind in ("stresschaos", "networkchaos"):
        delete = next(i for i, c in enumerate(cmds) if f"delete {kind} vl-" in c)
        assert any("docker cp" in c for c in cmds[delete:])


def test_up_dry_run_orders_cluster_chaos_collector_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(up, "manifest_problem", lambda pins: None)
    assert up.main(["--profile", "ob", "--dry-run"]) == 0
    cmds = _commands(capsys.readouterr().out)
    markers = ("kind create cluster", "upgrade --install chaos-mesh", "collector.yaml", "apply -k")
    order = [next(i for i, c in enumerate(cmds) if marker in c) for marker in markers]
    assert order == sorted(order)
    assert any("--version 2.8.7" in c for c in cmds)


def test_up_refuses_without_vendored_manifest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(up, "manifest_problem", lambda pins: "not vendored")
    assert up.main(["--profile", "ob", "--dry-run"]) == 1
    assert "not vendored" in capsys.readouterr().err


def test_up_otel_is_not_available_yet(capsys: pytest.CaptureFixture[str]) -> None:
    assert up.main(["--profile", "otel", "--dry-run"]) == 2


def test_down_needs_only_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up.shutil, "which", lambda tool: None if tool == "helm" else f"/bin/{tool}")
    assert up.missing_tools(down=True) == []
    assert up.missing_tools() == ["helm"]
