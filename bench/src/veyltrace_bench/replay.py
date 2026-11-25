"""RQ6 replay results: `veyltrace bench replay` (04 §2 RQ6, §7 "Replay", §8; CCR #440).

The recorded runs are the kept AI-arm record runs under `<runs root>/bench-ai/` (`ai_arms`) that an
`ok` AI-arm row of a source experiment scored. A row bench replayed from a kept run carries the
replay's run id, which shares the kept run's config hash (core: "record and replay share one
lock"), so the kept run is found by that alias. The `recording` role enumerates the runs; a
`second-laptop` or `ci` role replays exactly the runs of the committed `recording` result, so
every site has the same denominator (a run missing there is `no_receipt`).

- **Tier 1** (H6a / SC-6) runs `veyltrace replay <receipt> --report` in a child interpreter, strict
  (no `--allow-env-drift`), so bench never imports `veyltrace_llm` or Causivra. The report decides:
  core's CLI also exits 2 on a usage error, so a child without a report is `no_report`.
- **Tier 2** (H6b) regenerates a fixed sample in `record` mode through bench's child, from the
  kept run's `config.lock.json` (same config hash and run id) into a scratch root, reusing its
  steps 0-4, and compares the `proposals.json` bytes.

Writes `<results>/replay/<role>/replay.csv` (bench_replay), then `replay_summary.json`
(bench_replay_summary). The other tier's committed result is kept when its sources and code
commit are the current ones. Decisions: ADR 20261122-ak-rq6-replay-results.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pyarrow as pa

from veyltrace_bench import agent_only, ai_arms
from veyltrace_bench.experiment import code_state
from veyltrace_bench.runner import PRODUCER, child_command
from veyltrace_contracts.models import BenchManifest, BenchReplaySummary, RunManifest, Verdict
from veyltrace_core import io, textio
from veyltrace_core.config import find_config_dir
from veyltrace_core.errors import ArtifactMissing, ConfigError, UsageError, VeyltraceError
from veyltrace_core.hashing import sha256_file, sha256_json
from veyltrace_core.ids import run_id as make_run_id
from veyltrace_core.pipeline import DIRTY_EXCLUDES, DIRTY_PATHS, env_info, run_dir_for, uv_lock_sha256
from veyltrace_stats.exact import clopper_pearson

RECORDING, SECOND, CI = "recording", "second-laptop", "ci"
ROLES = (RECORDING, SECOND, CI)
REPLAY_DIR = "replay"  # <results>/replay/<role>/ (03 §13.5)
CSV, SUMMARY, MANIFEST, PER_CASE = "replay.csv", "replay_summary.json", "manifest.json", "per_case.csv"
RECEIPT, LOCK, PROPOSALS = "receipt.json", "config.lock.json", "proposals.json"
LEVEL = 0.95  # 04 §8
TIER2_FROM = "re2-oracle-rq2-v1", "veyltrace:brief", 1  # ADR: the RQ2 brief arm, first seed
TIER2_N = 50  # 04 §6 "Tier 2 regeneration on 50 recorded cases"
TIER2_RNG_SEED = 20261108  # ADR, a priori: re2-oracle-rq2-v1's split seed
REGEN_FROM_STEP = "faultloom"  # as replay R7 (10 §3.9): steps 0-4 are reused, FaultLoom onwards re-run
OUTCOMES = (*(str(c) for c in range(7)), "no_receipt", "no_report", "timeout")  # 0-6: ReplayExit
EXCLUDED = ("failed", "no_alert", "rejected", "timeout")
GITHUB = ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")


@dataclass
class Run:
    """One recorded run to replay: its bench_replay identity columns (its kept directory is
    `run_dir_for(<runs root>/bench-ai, dataset, case_id, run_id)`)."""

    run_id: str
    case_id: str
    dataset: str
    system: str
    method: str
    seed: int
    verdict_hash: str
    experiments: set[str] = field(default_factory=set[str])

    def identity(self, tier: int) -> dict[str, object]:
        keys = ("run_id", "case_id", "dataset", "system", "method", "seed", "verdict_hash")
        return {"tier": tier, **{k: getattr(self, k) for k in keys}, "experiments": sorted(self.experiments)}


@dataclass(frozen=True)
class Source:
    """One source experiment's committed results: manifest (and its file hash) and per_case rows."""

    experiment_id: str
    manifest: BenchManifest
    manifest_sha256: str
    rows: list[dict[str, Any]]
    timeout_s: int

    @property
    def arms(self) -> set[str]:
        """The methods with recorded runs of their own: AI on, and not agent-only, which scores its
        source arm's run and has no run or verdict of its own (agent_only.source_of; #529)."""
        methods = cast("list[dict[str, Any]]", self.manifest.experiment["methods"])
        return {
            m["id"]
            for m in methods
            if m.get("ai", {}).get("mode", "off") != "off" and m.get("kind") != agent_only.KIND
        }


def load_sources(results: Path, ids: Sequence[str]) -> list[Source]:
    """The source experiments: `ids`, or every result under `results` with an AI arm."""
    chosen = ids or sorted(
        p.parent.name for p in results.glob(f"*/{MANIFEST}") if p.parent.name != REPLAY_DIR
    )
    out: list[Source] = []
    for eid in sorted(set(chosen)):
        path = results / eid / MANIFEST
        manifest = cast("BenchManifest", io.read_path("bench_manifest", path, validate=True))
        table = cast("pa.Table", io.read_path("bench_result", results / eid / PER_CASE, validate=True))
        timeout = int(cast("dict[str, Any]", manifest.experiment["resources"])["timeout_s"])
        src = Source(eid, manifest, sha256_file(path), table.to_pylist(), timeout)
        if src.arms or ids:
            out.append(src)
    if not out:
        raise ArtifactMissing(MANIFEST, results / "<experiment_id>" / MANIFEST)
    return out


def _kept(run_dir: Path) -> tuple[str, str, int, str] | None:
    """(record run id, replay alias, seed, verdict_hash) of a finished kept record run."""
    try:
        manifest = io.read_model("run_manifest", run_dir, RunManifest)
        verdict = io.read_model("verdict", run_dir, Verdict)
    except (ArtifactMissing, VeyltraceError):
        return None
    lock = cast("dict[str, Any]", json.loads(textio.read_text(run_dir / LOCK)))
    seed = int(lock["sections"]["relentra"]["sampler"][ai_arms.SEED_KEY.rsplit(".", 1)[1]])
    alias = make_run_id(manifest.case_id, manifest.config_sha256, manifest.code.commit, ai_arms.REPLAY)
    return manifest.run_id, alias, seed, verdict.verdict_hash


def excluded_rows(sources: Iterable[Source]) -> Counter[str]:
    """The sources' AI-arm rows with no verdict to replay, per run_outcome."""
    return Counter(
        r["run_outcome"]
        for s in sources
        for r in s.rows
        if r["method"] in s.arms and r["run_outcome"] != "ok"
    )


def enumerate_runs(sources: Iterable[Source], kept: Path) -> dict[str, Run]:
    """The recorded runs the sources' `ok` AI-arm rows scored (recording role)."""
    runs: dict[str, Run] = {}
    index: dict[tuple[str, str], dict[str, tuple[str, int, str]]] = {}  # (dataset, case) -> alias -> kept
    for src in sources:
        entries: dict[tuple[str, str, str], set[str]] = {}
        for r in src.manifest.runs:
            if r.run_id is not None:
                entries.setdefault((r.dataset, r.case_id, r.method), set()).add(r.run_id)
        for row in src.rows:
            if row["method"] not in src.arms or row["run_outcome"] != "ok":
                continue
            d, c = row["dataset"], row["case_id"]
            if (d, c) not in index:
                found = (_kept(p) for p in sorted((kept / d / c).glob("*")) if p.is_dir())
                index[(d, c)] = {a: (k[0], k[2], k[3]) for k in found if k for a in (k[0], k[1])}
            hits = {
                k[0]
                for rid in sorted(entries.get((d, c, row["method"]), ()))
                if (k := index[(d, c)].get(rid)) and (k[1], k[2]) == (row["seed"], row["verdict_hash"])
            }
            if not hits:
                raise VeyltraceError(
                    f"{src.experiment_id}: {c} {row['method']} seed {row['seed']}: no kept run"
                )
            for rid in hits:
                run = runs.setdefault(
                    rid, Run(rid, c, d, row["system"], row["method"], row["seed"], row["verdict_hash"])
                )
                run.experiments.add(src.experiment_id)
    return runs


def recorded_runs(results: Path) -> dict[str, Run]:
    """The Tier 1 runs of the committed recording result (the other roles replay exactly these)."""
    table = cast(
        "pa.Table", io.read_path("bench_replay", results / REPLAY_DIR / RECORDING / CSV, validate=True)
    )
    runs: dict[str, Run] = {}
    for r in table.to_pylist():
        if r["tier"] == 1:
            keys = ("run_id", "case_id", "dataset", "system", "method", "seed", "verdict_hash")
            runs[r["run_id"]] = Run(*(r[k] for k in keys), experiments=set(r["experiments"]))
    return runs


def _report_row(run: Run, report: Mapping[str, Any]) -> dict[str, object]:
    """A Tier 1 row from a 10 §3.9 report; the hashes are compared only when R8 ran."""
    hashes = {
        k: cast("dict[str, str | None]", report.get(k) or {})
        for k in ("verdict_hash", "agent_trace_head", "card_hash")
    }
    replayed = hashes["verdict_hash"].get("actual")

    def match(name: str) -> bool | None:
        return hashes[name].get("expected") == hashes[name].get("actual") if replayed is not None else None

    return run.identity(1) | {
        "exit_code": int(report["exit_code"]),
        "verdict_hash_replayed": replayed,
        "trace_match": match("agent_trace_head"),
        "card_match": match("card_hash"),
        "first_divergence": report.get("first_divergence"),
        "env_drift": list(report.get("env_drift") or []),
    }


EMPTY = {
    "exit_code": None,
    "reason": None,
    "verdict_hash_replayed": None,
    "trace_match": None,
    "card_match": None,
    "proposals_match": None,
    "first_divergence": None,
    "env_drift": [],
}


def replay_one(run: Run, kept: Path, timeout_s: int) -> dict[str, object]:
    """Tier 1 row of one run: `veyltrace replay` in a child, read from its report."""
    receipt = run_dir_for(kept, run.dataset, run.case_id, run.run_id) / RECEIPT
    if not receipt.is_file():
        return EMPTY | run.identity(1) | {"reason": "no_receipt"}
    with tempfile.TemporaryDirectory(prefix="veyltrace-replay-") as tmp:
        report = Path(tmp, "report.json")
        cmd = [sys.executable, "-m", "veyltrace_core.cli", "replay", str(receipt), "--report", str(report)]
        try:
            subprocess.run(
                cmd, cwd=find_config_dir().parent, capture_output=True, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired:
            return EMPTY | run.identity(1) | {"reason": "timeout"}
        if not report.is_file():
            return EMPTY | run.identity(1) | {"reason": "no_report"}
        return EMPTY | _report_row(run, json.loads(textio.read_text(report)))


def sample(runs: Mapping[str, Run]) -> list[Run]:
    """The Tier 2 sample: the TIER2_FROM runs ordered by sha256_json([TIER2_RNG_SEED, case_id,
    run_id]), first TIER2_N (fixed by the ADR before any regeneration)."""
    eid, method, seed = TIER2_FROM
    pool = [r for r in runs.values() if eid in r.experiments and (r.method, r.seed) == (method, seed)]
    return sorted(pool, key=lambda r: sha256_json([TIER2_RNG_SEED, r.case_id, r.run_id]))[:TIER2_N]


def same_run_config(kept_dir: Path, regen_dir: Path) -> bool:
    """Whether a regenerated run is the kept run again: the same case and resolved config (so the
    same prompts and sampler). The run id is not compared: it hashes the code commit (02 §4.1),
    and a site regenerates at its own checkout, whose run code `_check` has already required to
    equal the recording's (#534)."""
    try:
        a = io.read_model("run_manifest", kept_dir, RunManifest)
        b = io.read_model("run_manifest", regen_dir, RunManifest)
    except (ArtifactMissing, VeyltraceError):
        return False
    return (a.case_id, a.config_sha256) == (b.case_id, b.config_sha256)


def regenerate_one(run: Run, kept: Path, scratch: Path, timeout_s: int) -> dict[str, object]:
    """Tier 2 row of one run: record again from its lock into `scratch`, compare proposals.json."""
    src = run_dir_for(kept, run.dataset, run.case_id, run.run_id)
    base = EMPTY | run.identity(2)
    if not (src / LOCK).is_file():
        return base | {"reason": "regen_failed"}
    request = {
        "dataset": run.dataset,
        "case_id": run.case_id,
        "ai_mode": ai_arms.RECORD,
        "overrides": {},
        "lock": str(src / LOCK),
        "runs_root": str(scratch),
        "from_step": REGEN_FROM_STEP,
        "reuse_dir": str(src),
    }
    with tempfile.TemporaryDirectory(prefix="veyltrace-regen-") as tmp:
        req, res = Path(tmp, "request.json"), Path(tmp, "result.json")
        textio.write_bytes(req, json.dumps(request).encode())
        try:
            cmd = child_command(req, res)
            subprocess.run(
                cmd, cwd=find_config_dir().parent, capture_output=True, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired:
            return base | {"reason": "timeout"}
        got = cast("dict[str, Any]", json.loads(textio.read_text(res))) if res.is_file() else {}
    summary = cast("dict[str, Any]", got.get("summary") or {})
    if summary.get("outcome") != "ok" or not same_run_config(src, Path(summary["run_dir"])):
        return base | {"reason": "regen_failed"}
    out = Path(summary["run_dir"])
    verdict = io.read_model("verdict", out, Verdict).verdict_hash
    return base | {
        "verdict_hash_replayed": verdict,
        "proposals_match": (out / PROPOSALS).is_file()
        and sha256_file(out / PROPOSALS) == sha256_file(src / PROPOSALS),
    }


def _share(
    rows: Sequence[Mapping[str, object]], hit: Callable[[Mapping[str, object]], bool]
) -> dict[str, object]:
    """n, k (rows that `hit`), k_verdict, the rate and its Clopper-Pearson interval (04 §8)."""
    n, k = len(rows), sum(1 for r in rows if hit(r))
    k_verdict = sum(1 for r in rows if r["verdict_hash_replayed"] == r["verdict_hash"])
    if n == 0:
        return {"n": 0, "k": 0, "k_verdict": 0, "rate": None, "ci_low": None, "ci_high": None, "level": LEVEL}
    ci = clopper_pearson(k, n, level=LEVEL)
    return {
        "n": n,
        "k": k,
        "k_verdict": k_verdict,
        "rate": k / n,
        "ci_low": ci.low,
        "ci_high": ci.high,
        "level": LEVEL,
    }


def _exit_0(row: Mapping[str, object]) -> bool:
    return row["exit_code"] == 0 and row["reason"] is None  # 04 §7 Tier 1


def _proposals_match(row: Mapping[str, object]) -> bool:
    return row["proposals_match"] is True  # 04 §7 Tier 2: byte-identical


def tier1(rows: Sequence[Mapping[str, object]], excluded: Counter[str]) -> dict[str, object]:
    share = _share(rows, _exit_0)
    outcomes = Counter(str(r["exit_code"]) if r["exit_code"] is not None else str(r["reason"]) for r in rows)
    experiments = sorted({e for r in rows for e in cast("list[str]", r["experiments"])})
    by = [
        {
            "experiment_id": e,
            "n": sum(1 for r in rows if e in cast("list[str]", r["experiments"])),
            "k": sum(1 for r in rows if e in cast("list[str]", r["experiments"]) and _exit_0(r)),
        }
        for e in experiments
    ]
    return share | {
        "outcomes": {o: outcomes[o] for o in OUTCOMES},
        "excluded": {e: excluded[e] for e in EXCLUDED},
        "by_experiment": by,
    }


def tier2(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    eid, method, seed = TIER2_FROM
    selection = {
        "experiment_id": eid,
        "method": method,
        "seed": seed,
        "rng_seed": TIER2_RNG_SEED,
        "n_requested": TIER2_N,
    }
    return _share(rows, _proposals_match) | {"selection": selection}


def site(role: str) -> dict[str, object]:
    """Where this replay runs; `ci` needs GitHub Actions' variables."""
    url = None
    if role == CI:
        if os.environ.get("GITHUB_ACTIONS") != "true" or not all(os.environ.get(v) for v in GITHUB):
            raise UsageError("--role ci runs only in GitHub Actions (GITHUB_ACTIONS and the run variables)")
        server, repo, run = (os.environ[v] for v in GITHUB)
        url = f"{server}/{repo}/actions/runs/{run}"
    env = env_info()
    host = hashlib.sha256(platform.node().encode()).hexdigest()[:12]
    return {
        "host_id": host,
        "os": env["os"],
        "python": env["python"],
        "cpu": platform.processor() or None,
        "ci_run_url": url,
    }


def same_code(repo: Path, code: Mapping[str, object], commit: str) -> bool:
    """Whether this checkout runs `commit`'s code: core's DIRTY_PATHS are unchanged since it. The
    R-16 results are committed after results-code-v1, so HEAD may be a later, results-only commit."""
    if code["commit"] == commit:
        return True
    if code["dirty"]:
        return False
    spec = [*DIRTY_PATHS, *(f":(exclude){p}" for p in DIRTY_EXCLUDES)]
    diff = subprocess.run(
        ["git", "diff", "--quiet", commit, "HEAD", "--", *spec], cwd=repo, capture_output=True, check=False
    )
    return diff.returncode == 0


def _check(
    role: str,
    sources: Sequence[Source],
    code: Mapping[str, object],
    results: Path,
    here: Mapping[str, object],
) -> None:
    """Refuse results of other code, other sources than the recording's, or a second laptop that is not."""
    repo = find_config_dir().parent
    if bad := sorted(s.experiment_id for s in sources if not same_code(repo, code, s.manifest.code.commit)):
        raise ConfigError(
            f"the run code at {code['commit']} is not the code of these results: {', '.join(bad)}"
        )
    if role == RECORDING:
        return
    path = results / REPLAY_DIR / RECORDING / SUMMARY
    recording = cast("BenchReplaySummary", io.read_path("bench_replay_summary", path, validate=True))
    if [(s.experiment_id, s.manifest_sha256) for s in recording.sources] != [
        (s.experiment_id, s.manifest_sha256) for s in sources
    ]:
        raise ConfigError(f"{role}: the sources differ from the recording result's (replay/{RECORDING})")
    if role == SECOND and recording.site.host_id == here["host_id"]:
        raise UsageError("--role second-laptop on the recording host (same host_id)")


def run_dirs_bytes(runs: Iterable[Run], kept: Path) -> int:
    """Total bytes of the runs' directories: what a CI archive must carry (--dry-run)."""
    dirs = (run_dir_for(kept, r.dataset, r.case_id, r.run_id) for r in runs)
    return sum(f.stat().st_size for d in dirs if d.is_dir() for f in d.rglob("*") if f.is_file())


def replay(
    results: Path,
    runs_root: Path,
    role: str,
    *,
    tier: int = 1,
    experiments: Sequence[str] = (),
    dry_run: bool = False,
    table: bool = False,
) -> Path | tuple[int, int]:
    """Replay (tier 1) or regenerate (tier 2) the recorded runs of the source experiments and write
    `<results>/replay/<role>/`; with `dry_run`, (run count, total bytes) and nothing written."""
    if role not in ROLES or tier not in (1, 2):
        raise UsageError(f"--role is one of {', '.join(ROLES)}; --tier is 1 or 2")
    kept = runs_root / ai_arms.KEPT
    sources = load_sources(results, experiments)
    code = code_state(find_config_dir().parent)
    if table and (code["dirty"] or code["bench_dirty"]):
        raise UsageError("--table refuses a dirty work tree (bench/AGENTS.md Never 3); commit first")
    here: dict[str, object] = {}
    if not dry_run:
        here = site(role)
        _check(role, sources, code, results, here)
    runs = enumerate_runs(sources, kept) if role == RECORDING else recorded_runs(results)
    chosen = sorted(runs.values(), key=lambda r: r.run_id) if tier == 1 else sample(runs)
    if dry_run:
        return len(chosen), run_dirs_bytes(chosen, kept)
    timeout = max(s.timeout_s for s in sources)
    if tier == 1:
        rows = [replay_one(r, kept, timeout) for r in chosen]
    else:
        with tempfile.TemporaryDirectory(prefix="veyltrace-regen-runs-") as scratch:
            rows = [regenerate_one(r, kept, Path(scratch), timeout) for r in chosen]
    out = results / REPLAY_DIR / role
    head = {
        "producer": PRODUCER,
        "role": role,
        "site": here,
        "code": code,
        "uv_lock_sha256": uv_lock_sha256(),
        "sources": [
            {"experiment_id": s.experiment_id, "manifest_sha256": s.manifest_sha256} for s in sources
        ],
    }
    kept_rows, other = _previous(out, head, 3 - tier)
    summary = head | {
        f"tier{tier}": tier1(rows, excluded_rows(sources)) if tier == 1 else tier2(rows),
        f"tier{3 - tier}": other,
    }
    out.mkdir(parents=True, exist_ok=True)
    io.write_path("bench_replay", sorted(rows + kept_rows, key=lambda r: (r["tier"], r["run_id"])), out / CSV)
    io.write_path("bench_replay_summary", summary, out / SUMMARY)  # last: marks a whole result
    return out


def _previous(out: Path, head: Mapping[str, object], tier: int) -> tuple[list[dict[str, object]], object]:
    """The other tier's committed rows and summary entry, kept when sources and commit match."""
    try:
        old = cast("BenchReplaySummary", io.read_path("bench_replay_summary", out / SUMMARY, validate=True))
        table = cast("pa.Table", io.read_path("bench_replay", out / CSV, validate=True))
    except (ArtifactMissing, VeyltraceError):
        return [], None
    same = old.code.commit == cast("Mapping[str, object]", head["code"])["commit"]
    if not same or [s.model_dump() for s in old.sources] != head["sources"]:
        return [], None
    entry = getattr(old, f"tier{tier}")
    rows = [r for r in table.to_pylist() if r["tier"] == tier]
    return rows, entry.model_dump(by_alias=True) if entry is not None else None
