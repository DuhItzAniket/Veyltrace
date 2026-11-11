"""Run a fault campaign from a plan file (05 §8).

    uv run python lab/campaign.py --plan lab/plans/x02-smoke.yaml [--dry-run]

Per entry: reset → warm-up → baseline check → baseline → fault → recovery → export. Each case
writes ``lab/captures/<capture_id>/`` (OTLP files + orchestrator.json), its answer key under
``lab/captures/answer_keys/`` and one line in ``lab/captures/attempts.jsonl``. A dry run prints
every command and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from vlab import CAPTURES_DIR, answer_key, capture
from vlab.cluster import OB_DIR, cpu_limits, kubectl, load_pins
from vlab.faults import CHAOS_KINDS, CONTAINER, Injection, get_fault, injection
from vlab.plan import Entry, Plan, load
from vlab.shell import CommandError, HostSuspended, Runner

ENTRY_URL = "http://127.0.0.1:8080/"
#: Baseline check retry (05 §8.1: wait 2 min and retry once).
BASELINE_RETRY_S = 120
RESET_TIMEOUT = "--timeout=300s"
#: Load-generator users of the overlay (05 §3.2 default); other profiles are set per case.
DEFAULT_USERS = 10


def reset(runner: Runner, pins: Mapping[str, Any], users: int = DEFAULT_USERS) -> None:
    """Remove leftover faults, restore config and images from the overlay, set the load profile and
    restart every app Deployment (05 §8.1 Reset)."""
    app = str(pins["app_namespace"])
    runner.run(kubectl(pins, "-n", app, "delete", CHAOS_KINDS, "--all", "--ignore-not-found"))
    runner.run(kubectl(pins, "apply", "-k", str(OB_DIR / "overlay")))
    if users != DEFAULT_USERS:
        runner.run(kubectl(pins, "-n", app, "set", "env", "deploy/loadgenerator", f"USERS={users}"))
    runner.run(kubectl(pins, "-n", app, "rollout", "restart", "deploy"))
    runner.run(
        kubectl(pins, "-n", app, "wait", "--for=condition=available", "deploy", "--all", RESET_TIMEOUT)
    )


def baseline_ok(runner: Runner) -> bool:
    """Entry service answers. The p95/error-rate check of 05 §8.1 needs span parsing (X-11)."""
    if runner.http_ok(ENTRY_URL):
        return True
    runner.sleep(BASELINE_RETRY_S, "baseline check retry")
    return runner.http_ok(ENTRY_URL)


def run_case(runner: Runner, pins: Mapping[str, Any], plan: Plan, entry: Entry, captures_dir: Path) -> str:
    """Run one plan entry, log the attempt and return its outcome."""
    capture_id = capture.new_capture_id()
    attempt: dict[str, Any] = {"capture_id": capture_id, "fault": entry.fault, "target": entry.target,
                               "severity": entry.severity, "users": entry.users}  # fmt: skip
    print(f"campaign: {entry.fault} {entry.severity} -> {entry.target} as {capture_id}")
    try:
        outcome = _phases(runner, pins, plan, entry, capture_id, captures_dir, attempt)
    except HostSuspended as exc:  # timings and telemetry have holes: no answer key, no capture
        attempt["error"] = str(exc)
        outcome = "host_suspended"
        app = str(pins["app_namespace"])
        runner.run(kubectl(pins, "-n", app, "delete", CHAOS_KINDS, "--all", "--ignore-not-found"))
    attempt["outcome"] = outcome
    attempt["validated"] = None  # 05 §8.2 validation rule arrives with X-11
    if not runner.dry_run:
        capture.log_attempt(captures_dir, attempt)
    print(f"campaign: {capture_id} {outcome}")
    return outcome


def _phases(
    runner: Runner,
    pins: Mapping[str, Any],
    plan: Plan,
    entry: Entry,
    capture_id: str,
    captures_dir: Path,
    attempt: dict[str, Any],
) -> str:
    """Reset → … → export for one entry (05 §8.1); returns the outcome."""
    fault = get_fault(entry.fault, entry.target, entry.severity)
    d = plan.durations_s
    capture_dir = captures_dir / capture_id
    app = str(pins["app_namespace"])
    inj = injection(
        fault, target=entry.target, severity=entry.severity, name=f"vl-{capture_id[:8]}", namespace=app,
        duration_s=d["fault"], cpu_limit=cpu_limits(pins).get(entry.target),
        cpu_request=cpu_limits(pins, "requests").get(entry.target),
    )  # fmt: skip
    reset(runner, pins, entry.users)
    runner.sleep(d["warmup"], "warm-up")
    if not baseline_ok(runner):
        outcome = "baseline_unrecovered"
    else:
        capture.start(runner, pins)
        t_capture_ns = runner.time_ns()
        runner.sleep(d["baseline"], "baseline")
        clock = capture.clock_sample(runner, pins)
        t_inject_ns: int | None = None
        try:
            inject(runner, pins, inj)
            t_inject_ns = runner.time_ns()
            runner.sleep(d["fault"], "fault window")
        except CommandError as exc:
            attempt["error"] = str(exc)
        finally:  # the fault never outlives the case, whatever failed above
            for args in inj.revert_args:
                runner.run(kubectl(pins, *args))
        t_end_ns = runner.time_ns()
        runner.sleep(d["recovery"], "recovery")
        files = capture.stop_and_collect(runner, pins, capture_dir)
        outcome = "inject_failed" if t_inject_ns is None else "captured"
        if runner.dry_run:
            outcome = "dry_run"
        elif t_inject_ns is not None:
            versions = capture.versions(runner, pins)
            tool_version = (
                capture.kubectl_client_version(versions)
                if fault.tool.startswith("kubectl/")
                else str(pins["chaos_mesh"]["version"])
            )
            injected = {"fault_id": fault.fault_id, "tool": fault.tool, "tool_version": tool_version,
                        "params": dict(fault.levels[entry.severity]), "severity": entry.severity,
                        "seed": plan.seed}  # fmt: skip
            key = answer_key.build(
                capture_id=capture_id, dataset=plan.dataset, root_service=entry.target,
                root_component=CONTAINER[entry.target], fault_id=fault.fault_id,
                fault_class=fault.fault_class, indicator=fault.indicator, mode=fault.mode,
                t_inject_ns=t_inject_ns, t_end_ns=t_end_ns, injection=injected,
            )  # fmt: skip
            answer_key.write(key, capture_id=capture_id, captures_dir=captures_dir)
            capture.write_orchestrator(capture_dir, {
                "capture_id": capture_id, "profile": plan.profile, "durations_s": d, "users": entry.users,
                "t_capture_start_ns": t_capture_ns, "t_inject_ns": t_inject_ns, "t_end_ns": t_end_ns,
                "clock": clock, "versions": versions, "host": capture.host_spec(),
                "injection": {"manifests": inj.manifests, "apply": inj.apply_args, "revert": inj.revert_args},
            }, files)  # fmt: skip
    return outcome


def inject(runner: Runner, pins: Mapping[str, Any], inj: Injection) -> None:
    """Apply the fault: its Chaos Mesh object, or its kubectl commands (F11)."""
    for manifest in inj.manifests:
        runner.run(kubectl(pins, "apply", "-f", "-"), stdin=yaml.safe_dump(manifest, sort_keys=True))
    for args in inj.apply_args:
        runner.run(kubectl(pins, *args))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab/campaign.py", description=__doc__.splitlines()[0])
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true", help="print every command; touch nothing")
    ap.add_argument("--captures", type=Path, default=CAPTURES_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        plan = load(args.plan)
    except (OSError, ValueError) as exc:
        print(f"campaign: bad plan {args.plan}: {exc}", file=sys.stderr)
        return 2
    runner = Runner(dry_run=args.dry_run)
    pins = load_pins()
    outcomes = [run_case(runner, pins, plan, entry, args.captures) for entry in plan.entries]
    return 0 if all(o in {"captured", "dry_run"} for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
