"""Start or stop a lab profile (05 §3, §4).

    uv run python lab/up.py --profile ob [--dry-run]
    uv run python lab/up.py --profile ob --down
    uv run python lab/up.py --vendor          # download and hash the pinned OB manifest

The `ob` and `otel` profiles never run together (02 §10): each refuses while the other is up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from vlab import LAB_DIR
from vlab.cluster import OB_DIR, helm, kubectl, load_pins, manifest_path, manifest_problem, sums_path
from vlab.shell import Runner

TOOLS = ("docker", "kind", "kubectl", "helm")
#: Compose project of the OpenTelemetry Demo (`otel` profile); its name is confirmed at X-06.
OTEL_PROJECT = "opentelemetry-demo"
#: Readiness waits. First start pulls every image; Chaos Mesh alone took > 5 min from ghcr.io on
#: 2026-11-09, so its wait is 15 min (measured once, generous).
CHAOS_TIMEOUT = "900s"
COLLECTOR_TIMEOUT = "300s"
APP_TIMEOUT = "900s"


def kind_cluster_exists(runner: Runner, pins: Mapping[str, Any]) -> bool:
    if runner.dry_run:
        runner.run(["kind", "get", "clusters"])
        return False
    return str(pins["cluster_name"]) in runner.run(["kind", "get", "clusters"]).split()


def otel_project_up(runner: Runner) -> bool:
    out = runner.run(["docker", "compose", "ls", "--format", "json"])
    if runner.dry_run or not out.strip():
        return False
    return any(p.get("Name") == OTEL_PROJECT for p in json.loads(out))


def missing_tools(*, down: bool = False) -> list[str]:
    """Tools the action needs that are not on PATH; deleting the cluster needs only kind."""
    return [t for t in (("kind",) if down else TOOLS) if shutil.which(t) is None]


def up_ob(runner: Runner, pins: Mapping[str, Any]) -> int:
    problem = manifest_problem(pins)
    if problem:
        print(f"up: {problem}", file=sys.stderr)
        return 1
    if otel_project_up(runner):
        print(f"up: refusing: Compose project {OTEL_PROJECT!r} (profile otel) is running", file=sys.stderr)
        return 1
    if not kind_cluster_exists(runner, pins):
        runner.run(["kind", "create", "cluster", "--config", str(OB_DIR / "kind.yaml"), "--wait", "120s"])
    chaos = pins["chaos_mesh"]
    runner.run(["helm", "repo", "add", "chaos-mesh", str(chaos["repo"]), "--force-update"])
    runner.run(
        helm(
            pins,
            "upgrade", "--install", "chaos-mesh", str(chaos["chart"]),
            "--namespace", str(pins["chaos_namespace"]), "--create-namespace",
            "--version", str(chaos["version"]),
            "--values", str(OB_DIR / "chaos-mesh-values.yaml"),
            "--wait", "--timeout", CHAOS_TIMEOUT,
        )
    )  # fmt: skip
    obs = str(pins["obs_namespace"])
    runner.run(kubectl(pins, "apply", "-f", str(OB_DIR / "collector.yaml")))
    runner.run(
        kubectl(
            pins, "-n", obs, "rollout", "status", "deploy/veyllab-collector", f"--timeout={COLLECTOR_TIMEOUT}"
        )
    )
    app = str(pins["app_namespace"])
    runner.run(kubectl(pins, "apply", "-k", str(OB_DIR / "overlay")))
    runner.run(
        kubectl(
            pins,
            "-n",
            app,
            "wait",
            "--for=condition=available",
            "deploy",
            "--all",
            f"--timeout={APP_TIMEOUT}",
        )
    )
    print("up: profile ob ready; frontend at http://127.0.0.1:8080/")
    return 0


def down_ob(runner: Runner, pins: Mapping[str, Any]) -> int:
    runner.run(["kind", "delete", "cluster", "--name", str(pins["cluster_name"])])
    return 0


def vendor(pins: Mapping[str, Any]) -> int:
    """Download the pinned OB release manifest and record its SHA-256 (05 §3.2)."""
    url = str(pins["online_boutique"]["manifest_url"])
    with urllib.request.urlopen(url, timeout=60) as resp:
        body: bytes = resp.read()
    digest = hashlib.sha256(body).hexdigest()
    target = manifest_path(pins)
    target.write_bytes(body)
    sums_path(pins).write_text(f"{digest}  {target.name}\n", encoding="utf-8", newline="\n")
    print(f"vendored {target.relative_to(LAB_DIR)} sha256={digest}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab/up.py", description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=("ob", "otel"))
    ap.add_argument("--down", action="store_true", help="delete the profile's cluster")
    ap.add_argument("--dry-run", action="store_true", help="print every command; touch nothing")
    ap.add_argument("--vendor", action="store_true", help="download the pinned OB manifest")
    args = ap.parse_args(argv)
    pins = load_pins()
    if args.vendor:
        return vendor(pins)
    if args.profile is None:
        ap.error("--profile is required unless --vendor is given")
    if not args.dry_run and (missing := missing_tools(down=args.down)):
        print(f"up: missing tools on PATH: {', '.join(missing)} (05 §2)", file=sys.stderr)
        return 1
    runner = Runner(dry_run=args.dry_run)
    if args.profile == "otel":
        if kind_cluster_exists(runner, pins):
            print(f"up: refusing: kind cluster {pins['cluster_name']!r} (profile ob) exists", file=sys.stderr)
            return 1
        print("up: profile otel is not implemented yet (X-06)", file=sys.stderr)
        return 2
    return down_ob(runner, pins) if args.down else up_ob(runner, pins)


if __name__ == "__main__":
    sys.exit(main())
