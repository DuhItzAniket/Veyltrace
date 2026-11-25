"""RQ6 second-laptop replay in one command (X-08 #41; 04 §2 H6a; ADR 20261122-ak-rq6-replay-results).

Usage (on the second laptop, from any checkout of the repository):

    uv run --no-project python scripts/explain/rq6_replay.py --commit <results commit>
        --release <draft release tag> --runs-root C:\\veyltrace-runs [--expect-runs N] [--expect-bytes B]

or, with the archive already downloaded: `--archive <file> [--archive <file> ...]` instead of
`--release`.

Why: the AI arms are recorded on the recording host (Aniket's laptop, docs/team/ak.md). This laptop
has no model, so RQ6 Tier 1 here only replays the kept record runs: bench's
`veyltrace bench replay --role second-laptop` runs `veyltrace replay <receipt> --report` on each,
which reads the run's cassette and never calls a model. That command needs four things put in
place by hand, and each can go wrong silently or only after hours: a checkout whose run code equals
the results' code (bench refuses any other, so `main` after `results-code-v1` does not work), the
committed `bench/results/replay/recording/` result, the private run archive extracted so that
`<runs root>/bench-ai/` exists, and a dry run whose count matches the recording's. This script does
them in order and stops at the first that fails, then runs the replay with `--table` and prints the
Tier 1 rate.

Steps: (1) a detached git worktree at `--commit` (or `--checkout`, which must already be at it);
(2) `uv sync --all-packages` there; (3) read the recording result and check that the checkout's run
code (core's DIRTY_PATHS) equals each source manifest's `code.commit`; (4) download the release
assets with `gh` and extract them (zip or tar; members outside the target are refused); (5)
`--dry-run`: the run count must equal the recording's Tier 1 `n`; (6) the replay; (7) report.

Exit codes: 0 every recorded run replayed (exit 0, Tier 1 rate 100%); 1 a step failed or the rate is
below 100%; 2 refused before any replay (usage, wrong checkout, missing recording result, count
mismatch). Only the standard library is imported, so the script runs before `uv sync`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ROLE = "second-laptop"
KEPT = "bench-ai"  # veyltrace_bench.ai_arms.KEPT
REPLAY_DIR, RECORDING = "replay", "recording"  # veyltrace_bench.replay
SUMMARY, CSV, MANIFEST = "replay_summary.json", "replay.csv", "manifest.json"
# veyltrace_core.pipeline.DIRTY_PATHS / DIRTY_EXCLUDES (test_explain_rq6_replay checks they agree)
DIRTY_PATHS = ("packages", "contracts", "config", "uv.lock", "pyproject.toml")
DIRTY_EXCLUDES = ("config/calibration", "bench/results", "runs")
OK, FAILED, REFUSED = 0, 1, 2


class Refused(Exception):
    """A precondition does not hold; nothing was replayed (exit 2)."""


def say(msg: str) -> None:
    print(f"rq6: {msg}", flush=True)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def resolve(repo: Path, ref: str) -> str:
    got = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    if got.returncode != 0:
        raise Refused(f"{ref!r} is not a commit here; run `git fetch origin` first")
    return got.stdout.strip()


def checkout(commit: str, path: Path | None) -> Path:
    """A worktree at `commit`: `path` if it is already there, else a new detached worktree."""
    sha = resolve(ROOT, commit)
    target = path if path is not None else ROOT.parent / f"vt-rq6-{sha[:12]}"
    if target.exists():
        head = resolve(target, "HEAD")
        if head != sha:
            raise Refused(f"{target} is at {head[:12]}, not {sha[:12]}")
        return target
    say(f"git worktree add --detach {target} {sha[:12]}")
    git(ROOT, "worktree", "add", "--detach", str(target), sha)
    return target


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def recording(results: Path) -> dict[str, Any]:
    path = results / REPLAY_DIR / RECORDING / SUMMARY
    if not path.is_file():
        raise Refused(f"no recording result at {path}: the recording host commits it first")
    got = read_json(path)
    if not got.get("tier1"):
        raise Refused(f"{path} has no Tier 1 result")
    return got


def same_code(repo: Path, commit: str) -> bool:
    """As veyltrace_bench.replay.same_code: the checkout's run code equals `commit`'s."""
    if resolve(repo, "HEAD") == commit:
        return True
    spec = [*DIRTY_PATHS, *(f":(exclude){p}" for p in DIRTY_EXCLUDES)]
    return git(repo, "diff", "--quiet", commit, "HEAD", "--", *spec, check=False).returncode == 0


def check_code(repo: Path, results: Path, summary: Mapping[str, Any]) -> None:
    for src in summary["sources"]:
        eid = src["experiment_id"]
        manifest = results / eid / MANIFEST
        if not manifest.is_file():
            raise Refused(f"the recording result names {eid}, but {manifest} is missing")
        commit = read_json(manifest)["code"]["commit"]
        sha, dirty = commit.split("+", 1)[0], "+dirty" in commit  # core.pipeline.code_commit
        if dirty:  # recorded from an uncommitted tree: only that tree can match; bench decides
            if sha != resolve(repo, "HEAD"):
                raise Refused(f"{eid} was run on a dirty tree at {sha[:12]}; a table needs a clean run")
            continue
        if git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode != 0:
            raise Refused(f"{eid} was run at {commit}, which this clone does not have (git fetch origin)")
        if not same_code(repo, commit):
            raise Refused(
                f"{eid} was run at {commit[:12]}, and this checkout's packages/, contracts/, config/ or "
                "uv.lock differ from it, so bench would refuse. Use a commit that adds only "
                "bench/results/ on top of that code (for R-16: results-code-v1), not main."
            )


def _member_ok(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and not (p.parts and p.parts[0].endswith(":"))


def extract(archive: Path, into: Path) -> None:
    """Extract a zip or tar archive into `into`; refuse any member that would land outside it."""
    into.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            if bad := [n for n in z.namelist() if not _member_ok(n)]:
                raise Refused(f"{archive.name}: member outside the runs root: {bad[0]}")
            z.extractall(into)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data")  # refuses absolute paths, `..` and links outside
    else:
        raise Refused(f"{archive.name}: not a zip or tar archive")


def download(repo: Path, tag: str, pattern: str, into: Path) -> list[Path]:
    into.mkdir(parents=True, exist_ok=True)
    say(f"gh release download {tag} --pattern {pattern!r} --dir {into}")
    cmd = ["gh", "release", "download", tag, "--pattern", pattern, "--dir", str(into), "--skip-existing"]
    subprocess.run(cmd, cwd=repo, check=True)
    return sorted(p for p in into.iterdir() if p.is_file())


def command(text: str) -> list[str]:
    """`--veyltrace` as argv; on Windows a double-quoted token (a path with spaces) loses its quotes."""
    if os.name != "nt":
        return shlex.split(text)
    return [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t for t in shlex.split(text, posix=False)]


def child_env(data: Path | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # the checkout's own venv
    if data is not None:
        env["VEYLTRACE_DATA"] = str(data)
    return env


def bench_replay(
    veyltrace: Sequence[str], repo: Path, args: Sequence[str], env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    cmd = [*veyltrace, "bench", "replay", "--role", ROLE, *args]
    say(" ".join(cmd))
    got = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=dict(env), check=False)
    sys.stdout.write(got.stdout)
    sys.stderr.write(got.stderr)
    return got


def dry_run_count(out: str) -> tuple[int, int]:
    """(runs, bytes) from `runs: N, bytes: B`, bench's --dry-run line."""
    for line in out.splitlines():
        if line.startswith("runs: "):
            runs, size = (part.split(": ")[1] for part in line.split(", "))
            return int(runs), int(size)
    raise Refused("the dry run printed no `runs: N, bytes: B` line")


def report(out: Path) -> tuple[bool, list[str]]:
    """(rate is 100%, lines) from the written second-laptop result."""
    t1 = read_json(out / SUMMARY)["tier1"]
    lines = [
        f"Tier 1 on {ROLE}: {t1['k']}/{t1['n']} replayed with exit 0 (rate {t1['rate']}, "
        f"95% CI [{t1['ci_low']}, {t1['ci_high']}]); verdict hash equal on {t1['k_verdict']}",
        "outcomes: " + (", ".join(f"{k}={v}" for k, v in t1["outcomes"].items() if v) or "none"),
    ]
    with (out / CSV).open(encoding="utf-8", newline="") as f:
        bad = [r for r in csv.DictReader(f) if r["tier"] == "1" and (r["exit_code"] != "0" or r["reason"])]
    for r in bad:
        lines.append(
            f"  not replayed: {r['dataset']}/{r['case_id']} {r['run_id']} exit={r['exit_code'] or '-'} "
            f"reason={r['reason'] or '-'} first_divergence={r['first_divergence'] or '-'}"
        )
    return t1["n"] > 0 and t1["k"] == t1["n"], lines


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="rq6_replay.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--commit", required=True, help="the results commit the recording host posted")
    ap.add_argument("--checkout", type=Path, help="an existing worktree at --commit (default: a new one)")
    ap.add_argument(
        "--runs-root", type=Path, required=True, help="extract the archive here (holds bench-ai/)"
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--release", help="draft release tag holding the run archive (downloaded with gh)")
    src.add_argument("--archive", type=Path, action="append", default=[], help="archive file (repeatable)")
    ap.add_argument("--pattern", default="*", help="release asset pattern (default every asset)")
    ap.add_argument("--download-dir", type=Path, help="default <runs root>.download")
    ap.add_argument("--results", type=Path, help="results root (default <checkout>/bench/results)")
    ap.add_argument("--data", type=Path, help="sets VEYLTRACE_DATA for the replay children")
    ap.add_argument("--expect-runs", type=int, help="the recording host's --dry-run run count")
    ap.add_argument("--expect-bytes", type=int, help="the recording host's --dry-run byte count")
    ap.add_argument("--skip-sync", action="store_true", help="do not run `uv sync --all-packages`")
    ap.add_argument("--no-table", action="store_true", help="omit --table (tests; never for the paper)")
    ap.add_argument("--veyltrace", default="uv run veyltrace", help="the CLI to call in the checkout")
    return ap.parse_args(argv)


def run(a: argparse.Namespace) -> int:
    repo = checkout(a.commit, a.checkout.resolve() if a.checkout else None)
    results = (a.results or repo / "bench" / "results").resolve()
    runs_root = a.runs_root.resolve()
    if not a.skip_sync:
        say(f"uv sync --all-packages in {repo}")
        subprocess.run(["uv", "sync", "--all-packages"], cwd=repo, env=child_env(None), check=True)
    rec = recording(results)
    check_code(repo, results, rec)
    n_recorded = int(rec["tier1"]["n"])
    site, code = rec["site"]["host_id"], rec["code"]["commit"][:12]
    say(f"recording result: {n_recorded} runs, host {site}, code {code}")
    archives = list(a.archive)
    if a.release:
        archives = download(repo, a.release, a.pattern, a.download_dir or runs_root.with_suffix(".download"))
    for archive in archives:
        say(f"extract {archive} -> {runs_root}")
        extract(archive.resolve(), runs_root)
    if not (runs_root / KEPT).is_dir():
        raise Refused(f"{runs_root / KEPT} does not exist: extract the archive so that it holds bench-ai/")
    veyltrace = command(a.veyltrace)
    env = child_env(a.data)
    common = ["--runs-root", str(runs_root), "--results", str(results)]
    dry = bench_replay(veyltrace, repo, [*common, "--dry-run"], env)
    if dry.returncode != 0:
        raise Refused(f"the dry run exited {dry.returncode}")
    runs, size = dry_run_count(dry.stdout)
    expected = a.expect_runs if a.expect_runs is not None else n_recorded
    if runs != expected or runs != n_recorded:
        raise Refused(f"dry run: {runs} runs, expected {expected} (recording result: {n_recorded})")
    if a.expect_bytes is not None and size != a.expect_bytes:
        raise Refused(f"dry run: {size} bytes, expected {a.expect_bytes}: the archive differs")
    got = bench_replay(veyltrace, repo, [*common, *([] if a.no_table else ["--table"])], env)
    if got.returncode != 0:
        say(f"bench replay exited {got.returncode}")
        return FAILED
    out = results / REPLAY_DIR / ROLE
    full, lines = report(out)
    for line in lines:
        say(line)
    say(f"result: {out}")
    say(
        "next: copy that folder into a branch off origin/main, add changes/<issue>.exp.md, open a PR"
        if full
        else "below 100%: post the lines above to the recording host before opening the result PR"
    )
    return OK if full else FAILED


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse(argv))
    except Refused as exc:
        print(f"rq6: refused: {exc}", file=sys.stderr)
        return REFUSED
    except subprocess.CalledProcessError as exc:
        print(f"rq6: {shlex.join(map(str, exc.cmd))} exited {exc.returncode}", file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    sys.exit(main())
