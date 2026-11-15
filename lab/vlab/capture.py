"""Capture on/off, export and provenance for one case (05 §8.1, §9).

Capture boundaries are Collector restarts: the spool is emptied while the Collector is scaled to
zero, so a capture holds exactly the baseline, fault and recovery phases; scaling to zero again at
export flushes the file exporters before the spool is copied out of the kind node.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vlab.cluster import kubectl, node_exec, sha256_file
from vlab.shell import Runner

SPOOL = "/veyllab/spool"
COLLECTOR = "deploy/veyllab-collector"
COLLECTOR_POD = "app=veyllab-collector"
WAIT = "--timeout=180s"


def new_capture_id() -> str:
    """32 random hex chars with no meaning (05 §9; lab code may use unseeded randomness)."""
    return secrets.token_hex(16)


def _collector_replicas(runner: Runner, pins: Mapping[str, Any], n: int) -> None:
    obs = str(pins["obs_namespace"])
    runner.run(kubectl(pins, "-n", obs, "scale", COLLECTOR, f"--replicas={n}"))
    if n == 0:
        runner.run(kubectl(pins, "-n", obs, "wait", "--for=delete", "pod", "-l", COLLECTOR_POD, WAIT))
    else:
        runner.run(kubectl(pins, "-n", obs, "rollout", "status", COLLECTOR, WAIT))


def start(runner: Runner, pins: Mapping[str, Any]) -> None:
    """Capture on: empty the spool behind a stopped Collector, then start it."""
    _collector_replicas(runner, pins, 0)
    runner.run(node_exec(pins, f"mkdir -p {SPOOL} && rm -f {SPOOL}/*"))
    _collector_replicas(runner, pins, 1)


def stop_and_collect(runner: Runner, pins: Mapping[str, Any], capture_dir: Path) -> list[Path]:
    """Capture off: flush, copy the spool to ``capture_dir/otlp/``, restart the Collector."""
    _collector_replicas(runner, pins, 0)
    otlp = capture_dir / "otlp"
    if not runner.dry_run:
        otlp.mkdir(parents=True, exist_ok=True)
    runner.run(["docker", "cp", f"{pins['node_container']}:{SPOOL}/.", str(otlp)])
    _collector_replicas(runner, pins, 1)
    return sorted(otlp.glob("*.jsonl")) if otlp.is_dir() else []


def clock_sample(runner: Runner, pins: Mapping[str, Any]) -> dict[str, int | None]:
    """Host and kind-node clocks in ns, read back to back (05 §8.1, for skew)."""
    host_ns = runner.time_ns()
    out = runner.run(node_exec(pins, "date +%s%N")).strip()
    node_ns = int(out) if out.isdigit() else None
    return {"host_ns": host_ns, "node_ns": node_ns, "skew_ns": None if node_ns is None else node_ns - host_ns}


def versions(runner: Runner, pins: Mapping[str, Any]) -> dict[str, Any]:
    """Tool versions and the image + digest of every running container (05 §2.3)."""
    images = runner.run(
        kubectl(
            pins, "get", "pods", "-A", "-o",
            'jsonpath={range .items[*].status.containerStatuses[*]}{.image}{"\\t"}{.imageID}{"\\n"}{end}',
        )
    )  # fmt: skip
    return {
        "kind": runner.run(["kind", "version"]).strip(),
        "kubectl": runner.run(["kubectl", "version", "--client", "-o", "json"]).strip(),
        "helm": runner.run(["helm", "version", "--short"]).strip(),
        "docker_server": runner.run(["docker", "version", "--format", "{{.Server.Version}}"]).strip(),
        "chaos_mesh": pins["chaos_mesh"]["version"],
        "online_boutique": pins["online_boutique"]["version"],
        "images": sorted({line for line in images.splitlines() if line.strip()}),
    }


def host_spec() -> dict[str, Any]:
    """Host facts that matter for laptop threats (05 §12); no user or host names."""
    return {"os": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "cpus": os.cpu_count()}  # fmt: skip


def write_orchestrator(capture_dir: Path, record: Mapping[str, Any], files: list[Path]) -> Path:
    data = dict(record)
    data["files"] = {p.relative_to(capture_dir).as_posix(): sha256_file(p) for p in files}
    path = capture_dir / "orchestrator.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def log_attempt(captures_dir: Path, record: Mapping[str, Any]) -> None:
    """Append one attempt, kept or not, to ``attempts.jsonl`` (05 §8.2 rule 5)."""
    captures_dir.mkdir(parents=True, exist_ok=True)
    with (captures_dir / "attempts.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def kubectl_client_version(versions: Mapping[str, Any]) -> str:
    """`clientVersion.gitVersion` from the recorded `kubectl version -o json`, or "unknown"."""
    try:
        return str(json.loads(str(versions["kubectl"]))["clientVersion"]["gitVersion"])
    except (KeyError, TypeError, ValueError):
        return "unknown"
