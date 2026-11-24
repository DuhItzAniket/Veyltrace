"""#489: the Collector's otlphttp exporter to the gateway is off by default (06 §3.3, OQ-7)."""

import copy
import shlex
import subprocess
from typing import Any

import pytest
import up
import yaml
from vlab.cluster import (
    COLLECTOR_FILE,
    LIVE_ANNOTATION,
    LIVE_EXPORTER,
    collector_manifest_live,
    live_endpoint_problem,
    load_pins,
)

ENDPOINT = "http://host.docker.internal:4319"


def _split(docs: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    cm = next(d for d in docs if d["kind"] == "ConfigMap")
    dep = next(d for d in docs if d["kind"] == "Deployment")
    return yaml.safe_load(cm["data"]["config.yaml"]), dep


def _committed() -> list[dict[str, Any]]:
    with COLLECTOR_FILE.open(encoding="utf-8") as fh:
        return [d for d in yaml.safe_load_all(fh) if d]


@pytest.fixture
def dry_run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Any:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"dry run started a process: {args}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(up, "manifest_problem", lambda pins: None)

    def run(*flags: str) -> tuple[int, list[str], str]:
        code = up.main(["--profile", "ob", "--dry-run", *flags])
        out = capsys.readouterr()
        return code, [line[2:] for line in out.out.splitlines() if line.startswith("+ ")], out.err

    return run


def test_switch_off_applies_the_committed_manifest(dry_run: Any) -> None:
    code, cmds, _ = dry_run()
    assert code == 0
    collector = [c for c in cmds if "apply -f" in c and "kubectl" in c]
    assert collector == [
        shlex.join(["kubectl", "--context", "kind-veyllab", "apply", "-f", str(COLLECTOR_FILE)])
    ]
    pipelines = _split(_committed())[0]["service"]["pipelines"]
    assert {s: p["exporters"] for s, p in pipelines.items()} == {
        "traces": ["file/traces"], "metrics": ["file/metrics"], "logs": ["file/logs"],
    }  # fmt: skip


def test_switch_on_pipes_the_live_manifest(dry_run: Any) -> None:
    code, cmds, _ = dry_run("--live-export")
    assert code == 0
    assert "kubectl --context kind-veyllab apply -f - <<stdin" in cmds
    assert not any(str(COLLECTOR_FILE) in c for c in cmds)


def test_switch_on_adds_only_the_exporter() -> None:
    committed = _committed()
    live_docs = list(yaml.safe_load_all(collector_manifest_live(ENDPOINT)))
    live, dep = _split(live_docs)
    assert live["exporters"][LIVE_EXPORTER] == {
        "endpoint": ENDPOINT,
        "encoding": "json",
        "compression": "gzip",
    }
    for signal, pipe in live["service"]["pipelines"].items():
        assert pipe["exporters"] == [f"file/{signal}", LIVE_EXPORTER]
    assert dep["spec"]["template"]["metadata"]["annotations"] == {LIVE_ANNOTATION: ENDPOINT}
    # Removing the exporter and the annotation gives back exactly the committed objects.
    undone = copy.deepcopy(live)
    del undone["exporters"][LIVE_EXPORTER]
    for pipe in undone["service"]["pipelines"].values():
        pipe["exporters"].remove(LIVE_EXPORTER)
    original, original_dep = _split(committed)
    assert undone == original
    del dep["spec"]["template"]["metadata"]["annotations"]
    assert dep == original_dep
    others = [d for d in live_docs if d["kind"] not in ("ConfigMap", "Deployment")]
    assert others == [d for d in committed if d["kind"] not in ("ConfigMap", "Deployment")]


def test_default_endpoint_is_pinned() -> None:
    assert live_endpoint_problem(str(load_pins()["gateway_otlp_endpoint"])) is None


@pytest.mark.parametrize(
    "bad", ["host.docker.internal:4319", "http://h:4319/v1/traces", "ftp://h:1", "http://"]
)
def test_bad_endpoint_is_refused(dry_run: Any, bad: str) -> None:
    code, cmds, err = dry_run("--live-export", bad)
    assert code == 1
    assert cmds == []
    assert "live export endpoint" in err
