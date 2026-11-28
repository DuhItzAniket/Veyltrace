"""Set up the isolated RCAEval environment the `rcaeval:<method>` baselines run in (R-05, #15).

Why: 04 §4 runs RCAEval's own main.py, at a pinned commit, in a venv of its own that the
workspace never imports (bench/AGENTS.md). Everything comes from the `rcaeval` section of
bench/baselines.yaml (repo, commit, venv, source); nothing is pinned here.

Steps: clone the repo into `source` (or fetch, if a clone exists) and check out the pinned commit;
create `venv` with Python 3.12 (uv); install RCAEval's `core` extra (its requirements.txt without
torch, which BARO and N-Sigma do not need) from the committed lock `scripts/rcaeval/requirements.lock`,
then RCAEval itself (editable, no dependencies). `--lock` first (re)writes the lock with
`uv pip compile`, e.g. after a commit bump; commit the result. `--check` only verifies.

Usage: uv run python scripts/rcaeval/setup.py [--lock | --check]
Network: git and PyPI (about 0.5 GB installed, *estimate*). Ask the lead before the first run.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from veyltrace_bench import rcaeval
from veyltrace_core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[2]
LOCK = Path(__file__).resolve().parent / "requirements.lock"
PYTHON = "3.12"  # 04 §4: one of the versions main.py accepts (rcaeval_facts "Downloads and licence")
EXTRA_DROP = ("torch",)  # the `core` extra = requirements.txt without torch (RCAEval setup.py)


def sh(*cmd: str, cwd: Path | None = None) -> str:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"error: {cmd[0]} exited {proc.returncode}")
    return proc.stdout.strip()


def checkout(cfg: rcaeval.Settings, source: Path) -> None:
    """The clone at the pinned commit (fetched only when the commit is not there yet)."""
    if not (source / ".git").is_dir():
        source.parent.mkdir(parents=True, exist_ok=True)
        sh("git", "clone", "--filter=blob:none", "--no-checkout", cfg.repo, str(source))
    probe = ["git", "-C", str(source), "cat-file", "-e", f"{cfg.commit}^{{commit}}"]
    have = subprocess.run(probe, check=False)
    if have.returncode != 0:
        sh("git", "-C", str(source), "fetch", "origin")
    sh("git", "-C", str(source), "checkout", "--detach", cfg.commit)


def lock(source: Path) -> None:
    """Compile the core extra's pins for Python 3.12 into the committed lock.

    Why the relative input path: `uv pip compile` writes the input path into the lock's
    `# via -r <path>` annotations, so compiling from inside the temporary directory keeps the
    machine's temp path (and the user name in it) out of the committed file (#676)."""
    lines = (source / "requirements.txt").read_text(encoding="utf-8").splitlines()
    keep = [ln for ln in lines if not ln.strip().startswith(EXTRA_DROP)]
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "requirements.in").write_text("\n".join(keep) + "\n", encoding="utf-8")
        compile_cmd = ("uv", "pip", "compile", "requirements.in", "--python-version", PYTHON)
        sh(*compile_cmd, "--no-header", "-o", str(LOCK), cwd=Path(tmp))


def install(cfg: rcaeval.Settings, source: Path) -> None:
    venv = ROOT / cfg.venv
    python = rcaeval.python_path(cfg, ROOT)
    if not python.is_file():
        sh("uv", "venv", "--allow-existing", "--python", PYTHON, str(venv))  # the clone lives in src/
    sh("uv", "pip", "sync", "--python", str(python), str(LOCK))
    sh("uv", "pip", "install", "--python", str(python), "--no-deps", "-e", str(source))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Set up the isolated RCAEval environment (R-05).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--lock", action="store_true", help="(re)compile requirements.lock first")
    mode.add_argument("--check", action="store_true", help="only verify the venv and the pinned commit")
    args = parser.parse_args(argv)
    cfg = rcaeval.settings(ROOT)
    if not args.check:
        if shutil.which("git") is None or shutil.which("uv") is None:
            print("error: needs git and uv on PATH", file=sys.stderr)
            return 1
        source = ROOT / cfg.source
        checkout(cfg, source)
        if args.lock or not LOCK.is_file():
            lock(source)
        install(cfg, source)
    try:
        rcaeval.check_environment(cfg, ROOT)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"RCAEval {cfg.commit[:12]} ready in {cfg.venv}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
