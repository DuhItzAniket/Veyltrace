"""`veyltrace replay <receipt.json>`: re-check a verdict from its receipt (10 §3.9; 02 §6.10).

Why: a verdict is only trustworthy if anyone holding the run directory can reproduce it. Replay
checks the receipt, manifest, locked config and stored step 0–4 inputs, re-runs steps 5–10a into a
temp dir under the locked config (and the recorded cassette when AI was on), and compares the
verdict hash, agent-trace head and card hash. It never reads the repository's `config/` files.
Exit precedence is 1 → 4 → 3 → 5 → 2 → 6 → 0 (R9); environment drift decides only at the end, so
`--allow-env-drift` replays a receipt from another machine. `--full` is not built yet (#432).

Alone in Causivra, this module calls core's pipeline: it is the CLI command behind
`veyltrace.commands:replay`, never imported by an engine step.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from veyltrace_causivra.receipt import PREDICATE_TYPE, STATEMENT_TYPE
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import ResolvedConfig
from veyltrace_core.errors import ChainBroken, ReplayExit, VeyltraceError, exit_code_for
from veyltrace_core.hashing import manifest_hash, sha256_file, verify_chain
from veyltrace_core.pipeline import UNCALIBRATED_SHA256, env_info, run_case, uv_lock_sha256
from veyltrace_core.steps import STEPS, index_of

__all__ = ["REPLAY_FROM", "Report", "main", "replay"]

#: The first sub-step replay re-runs (02 numbering: step 5, FaultLoom); everything before is input.
REPLAY_FROM: Final = "faultloom"
#: The last sub-step replay re-runs: the card (10a). The manifest and receipt are not rewritten.
REPLAY_TO: Final = "causivra.card"
CASSETTE_DIR: Final = "cassette"
MINISIG: Final = ".minisig"
#: Artefacts compared after the three hashes, to name the first that diverged (R8).
_DIAGNOSE: Final = ("evidence.parquet", "slate.json", "proposals.json")


@dataclass
class Report:
    """The replay report (10 §3.9 "Report"), written as canonical JSON."""

    checks: list[dict[str, Any]] = field(default_factory=lambda: [])
    env_drift: list[str] = field(default_factory=lambda: [])
    first_divergence: str | None = None
    hashes: dict[str, dict[str, str | None]] = field(default_factory=lambda: {})
    exit_code: int = int(ReplayExit.OK)

    def check(self, check_id: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"id": check_id, "ok": ok, "detail": detail})
        return ok

    def as_json(self) -> dict[str, Any]:
        empty: dict[str, str | None] = {"expected": None, "actual": None}
        hashes = {k: self.hashes.get(k, empty) for k in ("verdict_hash", "card_hash", "agent_trace_head")}
        out: dict[str, Any] = {
            "exit_code": self.exit_code,
            "checks": self.checks,
            "env_drift": self.env_drift,
        }
        return out | {"first_divergence": self.first_divergence} | hashes


class _Stop(Exception):
    """A check failed with exit code `args[0]`; later checks do not run."""


def _require(report: Report, check_id: str, ok: bool, detail: str, code: ReplayExit) -> None:
    if not report.check(check_id, ok, detail):
        raise _Stop(code)


def _receipt(path: Path, report: Report) -> models.Receipt:
    """R1: the Statement fields of 03 §11.2."""
    try:
        receipt = cast(models.Receipt, io.read_path("receipt", path, validate=True))
    except (VeyltraceError, OSError, ValueError) as exc:
        report.check("R1", False, f"unreadable receipt: {exc}")
        raise _Stop(ReplayExit.ERROR) from exc
    ok = (
        receipt.type_ == STATEMENT_TYPE
        and receipt.predicate_type == PREDICATE_TYPE
        and len(receipt.subject) == 1
        and receipt.subject[0].name == CONTRACTS["verdict"].path
    )
    _require(report, "R1", ok, "Statement type, predicate type and subject", ReplayExit.ERROR)
    return receipt


def _manifest(receipt: models.Receipt, run_dir: Path, report: Report) -> models.RunManifest:
    """R3: the embedded manifest is the one on disk, and the subject digest is verdict.json's."""
    embedded = receipt.predicate.run_manifest
    on_disk = io.path_of("run_manifest", run_dir)
    same = on_disk.is_file() and on_disk.read_bytes() == canonical_json(embedded) + b"\n"
    _require(report, "R3", same, "embedded run_manifest equals run_manifest.json", ReplayExit.INPUTS_CHANGED)
    verdict = io.path_of("verdict", run_dir)
    ok = verdict.is_file() and sha256_file(verdict) == receipt.subject[0].digest.sha256
    _require(report, "R3", ok, "verdict.json bytes match the subject digest", ReplayExit.INPUTS_CHANGED)
    return embedded


def _config(manifest: models.RunManifest, run_dir: Path, report: Report) -> ResolvedConfig:
    """R4: the locked config is valid and is the one the manifest names."""
    lock = io.path_of("config_lock", run_dir)
    try:
        resolved = ResolvedConfig.from_lock(lock)
    except (VeyltraceError, OSError, ValueError) as exc:
        report.check("R4", False, f"config.lock.json: {exc}")
        raise _Stop(ReplayExit.CONFIG) from exc
    same = sha256_file(lock) == manifest.config_sha256
    _require(report, "R4", same, "config.lock.json hash equals config_sha256", ReplayExit.CONFIG)
    return resolved


def _environment(manifest: models.RunManifest, report: Report) -> None:
    """R5: drift is recorded; the OS and the code commit are reported, never compared."""
    now = env_info()
    major_minor = ".".join(str(now["python"]).split(".")[:2])
    if ".".join(manifest.env.python.split(".")[:2]) != major_minor:
        report.env_drift.append(f"python {manifest.env.python} -> {now['python']}")
    for lib in sorted(set(manifest.env.libs) | set(now["libs"])):
        before, after = manifest.env.libs.get(lib), now["libs"].get(lib)
        if before != after:
            report.env_drift.append(f"{lib} {before} -> {after}")
    if uv_lock_sha256() != manifest.uv_lock_sha256:
        report.env_drift.append("uv.lock differs")
    detail = f"os {manifest.env.os}, commit {manifest.code.commit}; drift: {report.env_drift or 'none'}"
    report.check("R5", True, detail)


def _inputs(manifest: models.RunManifest, resolved: ResolvedConfig, run_dir: Path, report: Report) -> None:
    """R6: step 0–4 outputs, the calibration and the cassette are byte-identical to the record."""
    earlier = {s.name for s in STEPS[: index_of(REPLAY_FROM)]}
    want = {f.name: f.sha256 for s in manifest.steps if s.name in earlier for f in s.outputs}
    changed = sorted(
        name for name, digest in want.items()
        if not (run_dir / name).is_file() or sha256_file(run_dir / name) != digest
    )  # fmt: skip
    changed_input = ReplayExit.INPUTS_CHANGED
    _require(report, "R6", not changed, f"step 0-4 outputs changed: {changed or 'none'}", changed_input)
    calibration = UNCALIBRATED_SHA256 if resolved.calibration is None else resolved.calibration.sha256
    ok = calibration == manifest.calibration_sha256
    _require(report, "R6", ok, "the locked calibration is the manifest's", changed_input)
    if manifest.ai.mode != "off":
        cassette = run_dir / CASSETTE_DIR
        files = sorted(p for p in cassette.rglob("*") if p.is_file()) if cassette.is_dir() else []
        entries = [(p.relative_to(cassette).as_posix(), sha256_file(p)) for p in files]
        ok = (manifest_hash(entries) if entries else None) == manifest.ai.cassette_sha256
        _require(report, "R6", ok, "the cassette is the recorded one", changed_input)


def _rerun(
    manifest: models.RunManifest, resolved: ResolvedConfig, run_dir: Path, out_dir: Path, report: Report
) -> None:
    """R7: steps 5–10a into `out_dir`, AI replayed from the recorded cassette."""
    ai_mode = "off" if manifest.ai.mode == "off" else "replay"
    try:
        summary = run_case(
            manifest.dataset, manifest.case_id, ai_mode, {},
            config=resolved, run_id=manifest.run_id, out_dir=out_dir, reuse_dir=run_dir,
            from_step=REPLAY_FROM, to_step=REPLAY_TO, write_manifest=False, write_receipt=False,
            cassette_dir=run_dir / CASSETTE_DIR if ai_mode == "replay" else None,
            code_commit=manifest.code.commit,
        )  # fmt: skip
    except (VeyltraceError, OSError, ValueError) as exc:
        report.check("R7", False, f"{type(exc).__name__}: {exc}")
        raise _Stop(ReplayExit(exit_code_for(exc, "replay"))) from exc
    # A step error comes back wrapped; a cassette miss means the agent asked something new (2).
    code = ReplayExit(exit_code_for(summary.error, "replay")) if summary.error else ReplayExit.ERROR
    detail = f"re-run {summary.outcome} at {summary.failed_step}: {summary.reason}"
    _require(report, "R7", summary.outcome == "ok", detail, code)


def _compare(
    receipt: models.Receipt, manifest: models.RunManifest, out_dir: Path, report: Report
) -> ReplayExit:
    """R8: the verdict and trace decide; the card alone is a narrative mismatch."""
    verdict = io.read_model("verdict", out_dir, models.Verdict)
    card = io.read_model("card", out_dir, models.Card)
    try:
        traced = io.exists("agent_trace", out_dir)
        head = verify_chain(io.read_lines("agent_trace", out_dir, models.AgentTraceLine)) if traced else None
    except ChainBroken as exc:
        head = f"broken: {exc}"
    pred = receipt.predicate
    pairs = {
        "verdict_hash": (pred.verdict_hash, verdict.verdict_hash),
        "agent_trace_head": (pred.agent_trace_head, head),
        "card_hash": (pred.card_hash, card.card_hash),
    }
    report.hashes = {k: {"expected": e, "actual": a} for k, (e, a) in pairs.items()}
    recorded = {o.name: o.sha256 for o in manifest.outputs}
    for name in _DIAGNOSE:
        path = out_dir / name
        if name in recorded and (not path.is_file() or sha256_file(path) != recorded[name]):
            report.first_divergence = name
            break
    decision = pairs["verdict_hash"][0] == pairs["verdict_hash"][1] and pairs["agent_trace_head"][0] == head
    report.check("R8", decision, "verdict_hash and agent_trace_head reproduced")
    if not decision:
        return ReplayExit.HASH_MISMATCH
    card_ok = report.check("R8", pairs["card_hash"][0] == pairs["card_hash"][1], "card_hash reproduced")
    return ReplayExit.OK if card_ok else ReplayExit.NARRATIVE_MISMATCH


def replay(
    receipt_path: Path,
    *,
    run_dir: Path | None = None,
    allow_env_drift: bool = False,
    keep: Path | None = None,
) -> Report:
    """Replay one receipt; `keep` keeps the re-run directory there instead of deleting it."""
    report = Report()
    work = Path(tempfile.mkdtemp(prefix="veyltrace-replay-"))
    out_dir = keep if keep is not None else work / "run"
    try:
        receipt = _receipt(receipt_path, report)
        signed = receipt_path.with_name(receipt_path.name + MINISIG).is_file()  # R2: no key in v1 (X-09)
        report.check("R2", True, "signature present, no public key configured" if signed else "unsigned")
        directory = run_dir if run_dir is not None else receipt_path.parent
        manifest = _manifest(receipt, directory, report)
        resolved = _config(manifest, directory, report)
        _environment(manifest, report)
        _inputs(manifest, resolved, directory, report)
        _rerun(manifest, resolved, directory, out_dir, report)
        outcome = _compare(receipt, manifest, out_dir, report)
    except _Stop as stop:
        outcome = ReplayExit(stop.args[0])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # R9: unallowed drift (5) outranks 2, 6 and 0, however the re-run ended; 1, 4 and 3 outrank it.
    drift = bool(report.env_drift) and not allow_env_drift
    late = outcome in (ReplayExit.HASH_MISMATCH, ReplayExit.NARRATIVE_MISMATCH, ReplayExit.OK)
    report.exit_code = int(ReplayExit.ENV_DRIFT if drift and late else outcome)
    return report


def main(argv: Sequence[str]) -> int:
    """`veyltrace.commands:replay`: core's CLI forwards its arguments verbatim."""
    ap = argparse.ArgumentParser(prog="veyltrace replay", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("receipt", type=Path)
    ap.add_argument("--run-dir", type=Path)
    ap.add_argument("--full", action="store_true", help="not built yet (#432)")
    ap.add_argument("--allow-env-drift", action="store_true")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--keep", type=Path, help="keep the re-run directory here")
    args = ap.parse_args(list(argv))
    if args.full:
        print("veyltrace replay: --full is not built yet (#432)", file=sys.stderr)
        return int(ReplayExit.ERROR)
    report = replay(args.receipt, run_dir=args.run_dir, allow_env_drift=args.allow_env_drift, keep=args.keep)
    text = canonical_json(report.as_json()) + b"\n"
    sys.stdout.write(text.decode("utf-8"))
    if args.report is not None:
        args.report.write_bytes(text)
    return report.exit_code
