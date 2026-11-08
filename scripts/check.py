"""One entry point for every local and CI check (10 §5.2; check_ci §1, §4; M0 lead decisions).

CI and humans call the same script, so a green local run predicts a green CI run. Usage:

  uv run python scripts/check.py --package <name>      lint + types + tests + isolation for one package
  uv run python scripts/check.py --lint | --types | --tests | --isolation
  uv run python scripts/check.py --determinism [--require-synth] [--require-real-case] [--ai-fake]
  uv run python scripts/check.py --contracts-in-sync
  uv run python scripts/check.py --changelog [--base origin/main]
  uv run python scripts/check.py --fixtures-stale
  uv run python scripts/check.py --package <name> --update-golden [--cascade]   (never in CI)

Package names: the 13 under packages/, `contracts`, `bench` (path bench/), `lab` (path lab/, lint and
tests only: lab is not a workspace member) and `console` (`pnpm -C console check`).

Exit codes: 0 every check passed or was skipped, 1 a check failed, 2 usage error. The run ends with
one summary line per check (`OK lint`, `FAIL tests (3 failed)`, `SKIP determinism (...)`), so the
tail is easy to paste into a PR. Only the standard library is imported; tools (ruff, pyright,
pytest, gen_contracts.py, the pipeline) run as subprocesses of this interpreter, which `uv run`
makes the workspace venv. Every subprocess gets the thread pins (OMP/OPENBLAS/MKL_NUM_THREADS=1,
set with setdefault: lead decision §2.12) and UTF-8 stdio, so results match across laptops and CI.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
#: pytest's exit code when it collected no tests (pytest.ExitCode.NO_TESTS_COLLECTED).
PYTEST_NO_TESTS = 5

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
WORKSPACE_PACKAGES = ("core", *ENGINES, "llm", "gateway")
PACKAGE_NAMES = (*WORKSPACE_PACKAGES, "contracts", "bench", "lab", "console")

#: Thread pins for every subprocess (lead decision §2.12: BLAS/OpenMP thread counts change float
#: summation order).
THREAD_PINS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
#: Lines of subprocess output kept for summaries (enough for pytest's and ruff's final lines).
TAIL_LINES = 200

# --- tests / isolation ------------------------------------------------------------------------
TEST_PATHS = ("packages", "tests", "bench")
PYTEST_ARGS = ("-p", "no:cacheprovider", "--hypothesis-profile=ci")
ISOLATION_TESTS = ("tests/test_isolation.py", "tests/test_determinism_lint.py")
#: Read by the isolation and determinism-lint tests to restrict them to one package.
PACKAGE_FILTER_ENV = "VEYLTRACE_CHECK_PACKAGE"
CONTRACT_TESTS = ("tests/test_contracts.py", "tests/test_contracts_roundtrip.py")
GENERATED_PYTHON = "contracts/generated/python"
FIXTURE_CONSISTENCY_TEST = "tests/test_fixture_consistency.py"
#: Set by --fixtures-stale; without it the staleness test skips (it is not a required check).
FIXTURES_STALE_ENV = "VEYLTRACE_CHECK_FIXTURES_STALE"

# --- changelog (changes/README.md; 10 §5.2) ---------------------------------------------------
CHANGES_DIR = "changes"
CHANGELOG = "CHANGELOG.md"
FRAGMENT_TYPES = ("feat", "fix", "doc", "perf", "chore", "exp")
FRAGMENT_RE = re.compile(rf"^(?P<issue>[1-9][0-9]*)\.(?P<type>{'|'.join(FRAGMENT_TYPES)})\.md$")
FRAGMENT_IGNORED = frozenset({"README.md"})
CLOSES_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(?P<issue>[0-9]+)\b", re.IGNORECASE)
#: A sentence boundary inside the fragment: terminator, whitespace, then a capital letter.
SENTENCE_BOUNDARY_RE = re.compile(r"[.!?]\s+[A-Z]")
SENTENCE_END = (".", "!", "?")
DEFAULT_BASE = "origin/main"

# --- determinism gate (check_ci §4; 02 §9 rule 5; lead decision §2.13) -----------------------
SYNTH_DATASET = "synth"
SYNTH_CASES = ("synth-01", "synth-02", "synth-03", "synth-04", "synth-05")
FAKE_ARM_CASE = "synth-01"
#: FakeProvider selection for the record/replay arm (config/llm.yaml `provider: fake`).
FAKE_OVERRIDES: Mapping[str, object] = {"llm.provider": "fake"}
#: What the record/replay arm compares (check_ci §4: proposals, agent_trace, cassette, verdict).
AI_COMPARED_STEPS = frozenset({"relentra", "causentra"})
CASSETTE_PREFIX = "cassette/"
#: The two arms differ in hash seed, run root and Infralume cache state (cold, then warm), and
#: in everything a team laptop and CI may differ in (ARM_ENVIRONMENTS, working directory, data
#: root path), so an artefact that embeds a path, a time zone or a locale shows up as a diff.
HASH_SEEDS = ("0", "1")
#: Per-arm environment: UTC vs an IST laptop (DuckDB and ICU read TZ), C vs UTF-8 locale.
ARM_ENVIRONMENTS: tuple[Mapping[str, str], ...] = (
    {"TZ": "UTC", "LC_ALL": "C", "LANG": "C"},
    {"TZ": "Asia/Kolkata", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
)
CONFIG_DIR_ENV = "VEYLTRACE_CONFIG_DIR"
#: Seconds per pipeline run; the CI job's 20 min timeout bounds the whole gate (check_ci §4).
ARM_TIMEOUT_S = 600
#: Characters of a failed arm's stdout/stderr echoed into the report.
ERROR_TAIL_CHARS = 4000
#: Files the gate never compares (check_ci §4): the signature is not reproducible by design.
#: `.duck-tmp/` is DuckDB's spill dir, excluded from outputs (lead decision §2.3).
NEVER_COMPARED = frozenset({"receipt.json.minisig"})
SPILL_DIR = ".duck-tmp"
#: Read size for hashing run-dir files (1 MiB, same as veyltrace_core.hashing.FILE_CHUNK_BYTES).
FILE_CHUNK_BYTES = 1 << 20
RUN_MANIFEST = "run_manifest.json"
MANIFEST_STEP = "manifest"
RECEIPT = "receipt.json"
#: The pinned real case (critic gap: `--cases 1` does not say which case). Written after O-01.
REAL_CASE_FILE = ROOT / "scripts" / "ci_real_case.json"
DATA_ENV = "VEYLTRACE_DATA"
ADAPTERS_GROUP = "veyltrace.adapters"
RESULT_MARKER = "VEYLTRACE_CHECK_RESULT "
SYNTH_SKIP = "skipped: synth adapter not available (R-03)"
#: Run in a subprocess per arm: one pipeline run, then a single marker line with the summary and
#: the step → path table (so this script never imports the workspace).
_ARM_DRIVER = r"""
import json, sys
from pathlib import Path
args = json.loads(sys.argv[1])
from veyltrace_core.pipeline import run_case
from veyltrace_core.steps import STEPS
plan = {"out_dir": Path(args["out_dir"])}
if args.get("cassette_dir"):
    plan["cassette_dir"] = Path(args["cassette_dir"])
if args.get("run_id"):
    plan["run_id"] = args["run_id"]
summary = run_case(args["dataset"], args["case"], args["ai_mode"], args["overrides"], **plan)
result = {
    "outcome": summary.outcome,
    "reason": summary.reason,
    "failed_step": summary.failed_step,
    "run_id": summary.run_id,
    "run_dir": str(summary.run_dir),
    "steps": [[s.name, list(s.paths), list(s.files)] for s in STEPS],
}
print(args["marker"] + json.dumps(result), flush=True)
"""

# --- golden fixtures (check_ci §5; lead decision §2.10) ---------------------------------------
#: `python -m <this> --package P [--step S]...` regenerates P's fixtures (core testing module).
UPDATE_GOLDEN_MODULE = "veyltrace_core.testing.update_golden"
#: Producers in pipeline order (check_ci §5.1). Core and FaultLoom appear twice because their
#: fixtures sit at two points of the pipeline; the names are steps.STEPS sub-step names.
CASCADE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("infralume", ("infralume",)),
    ("core", ("alert",)),
    ("signalyth", ("signalyth",)),
    ("anomara", ("anomara",)),
    ("causync", ("causync",)),
    ("causalith", ("causalith",)),
    ("faultloom", ("faultloom",)),
    ("causatrix", ("causatrix",)),
    ("relentra", ("relentra",)),
    ("faultloom", ("faultloom.claim_pass",)),
    ("causentra", ("causentra",)),
    ("causivra", ("causivra.card",)),
    ("core", ("manifest",)),
    # the receipt hashes run_manifest.json, so it follows core's manifest step (steps.STEPS order)
    ("causivra", ("causivra.receipt",)),
)
TEXT_FIXTURE_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".txt"})
#: How many differing lines/rows the update summary shows per file (a priori, readable in a PR).
DIFF_PREVIEW = 10
#: difflib.unified_diff starts with the `---` / `+++` file header lines, which carry no content.
UNIFIED_DIFF_HEADER = 2
_PARQUET_SUMMARY = r"""
import json, sys
import pyarrow.parquet as pq
out = []
for old, new in json.loads(sys.argv[1]):
    a = pq.read_table(old).to_pylist() if old else []
    b = pq.read_table(new).to_pylist() if new else []
    first = [i for i in range(max(len(a), len(b))) if i >= len(a) or i >= len(b) or a[i] != b[i]]
    show = first[:int(sys.argv[2])]
    rows = [[i, repr(a[i]) if i < len(a) else None, repr(b[i]) if i < len(b) else None] for i in show]
    out.append({"old_rows": len(a) if old else None, "new_rows": len(b) if new else None, "rows": rows})
print(json.dumps(out))
"""


@dataclass(frozen=True)
class Result:
    """The outcome of one check, printed as one summary line."""

    name: str
    status: str  # "OK" | "FAIL" | "SKIP"
    detail: str = ""

    @property
    def line(self) -> str:
        return f"{self.status} {self.name}" + (f" ({self.detail})" if self.detail else "")


@dataclass(frozen=True)
class Proc:
    returncode: int
    tail: tuple[str, ...]


# --- subprocess helpers -------------------------------------------------------------------------
def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """os.environ plus the thread pins (setdefault) and UTF-8 stdio, plus `extra`.

    Only stdio is forced to UTF-8 (so output decodes the same everywhere); PYTHONUTF8 is left alone
    on purpose, so a file opened without `encoding=` still behaves as on a user's Windows laptop.
    """
    env = dict(os.environ)
    for var in THREAD_PINS:
        env.setdefault(var, "1")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def run(cmd: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path = ROOT) -> Proc:
    """Run `cmd`, streaming its output (stdout+stderr) and keeping the tail for the summary."""
    print(f"$ {' '.join(cmd)}", flush=True)
    tail: deque[str] = deque(maxlen=TAIL_LINES)
    try:
        proc = subprocess.Popen(
            list(cmd), cwd=cwd, env=dict(env or child_env()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except FileNotFoundError as exc:
        msg = f"cannot run {cmd[0]!r}: {exc}"
        print(msg, flush=True)
        return Proc(127, (msg,))
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        print(line, flush=True)
        tail.append(line)
    return Proc(proc.wait(), tuple(tail))


def python(*args: str) -> list[str]:
    return [sys.executable, *args]


def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    out = (
        proc.stdout.decode("utf-8", "replace")
        if proc.returncode == 0
        else proc.stderr.decode("utf-8", "replace")
    )
    return proc.returncode, out


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def last_match(lines: Iterable[str], pattern: re.Pattern[str]) -> re.Match[str] | None:
    found = None
    for line in lines:
        match = pattern.search(line)
        if match:
            found = match
    return found


# --- lint / types / tests / isolation -----------------------------------------------------------
RUFF_FOUND_RE = re.compile(r"Found (\d+) errors?")
RUFF_FORMAT_RE = re.compile(r"(\d+) files? would be reformatted")
PYRIGHT_RE = re.compile(r"(\d+) errors?, (\d+) warnings?")
PYTEST_COUNT_RE = re.compile(r"(\d+) (failed|passed|errors?|skipped|xfailed|xpassed|deselected)")
PYTEST_SUMMARY_RE = re.compile(
    r"\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|deselected).* in [0-9.]+s"
)


def check_lint(paths: Sequence[str], name: str = "lint", *, generated: bool = False) -> Result:
    """ruff check + ruff format --check (no auto-fix). Generated contracts get `ruff check` only."""
    problems: list[str] = []
    rc = run(python("-m", "ruff", "check", *paths))
    if rc.returncode != 0:
        m = last_match(rc.tail, RUFF_FOUND_RE)
        problems.append(f"ruff check: {m.group(1)} errors" if m else "ruff check failed")
    fmt = run(python("-m", "ruff", "format", "--check", *paths))
    if fmt.returncode != 0:
        m = last_match(fmt.tail, RUFF_FORMAT_RE)
        problems.append(f"ruff format: {m.group(1)} files" if m else "ruff format failed")
    if generated:
        gen = run(python("-m", "ruff", "check", GENERATED_PYTHON))
        if gen.returncode != 0:
            problems.append("ruff check on contracts/generated failed")
    return Result(name, "FAIL", "; ".join(problems)) if problems else Result(name, "OK")


def check_types(paths: Sequence[str] = ()) -> Result:
    """pyright with the root config (strict where [tool.pyright] strict says so)."""
    proc = run(python("-m", "pyright", *paths))
    m = last_match(proc.tail, PYRIGHT_RE)
    counts = f"{m.group(1)} errors, {m.group(2)} warnings" if m else ""
    if proc.returncode != 0:
        return Result("types", "FAIL", counts or f"pyright exited {proc.returncode}")
    return Result("types", "OK", counts)


def check_pytest(name: str, paths: Sequence[str], env: Mapping[str, str] | None = None) -> Result:
    """pytest with the CI hypothesis profile, `-x` off; the detail is pytest's own count line."""
    proc = run(python("-m", "pytest", *paths, *PYTEST_ARGS), env=env)
    summary = last_match(proc.tail, PYTEST_SUMMARY_RE)
    detail = summary.group(0).split(" in ")[0] if summary else ""
    counts: dict[str, int] = {}
    for n, kind in PYTEST_COUNT_RE.findall(detail):
        key = "error" if kind.startswith("error") else kind
        counts[key] = counts.get(key, 0) + int(n)
    if proc.returncode == PYTEST_NO_TESTS:
        return Result(name, "SKIP", "no tests collected")
    if proc.returncode != 0:
        failed = counts.get("failed", 0) + counts.get("error", 0)
        return Result(
            name, "FAIL", f"{failed} failed" if failed else detail or f"pytest exited {proc.returncode}"
        )
    return Result(name, "OK", detail)


def check_tests(package: str | None = None) -> Result:
    paths = [package_path(package)] if package else list(TEST_PATHS)
    return check_pytest("tests", paths)


def check_isolation(package: str | None = None) -> Result:
    env = child_env({PACKAGE_FILTER_ENV: package} if package else None)
    return check_pytest("isolation", ISOLATION_TESTS, env=env)


# --- contracts ----------------------------------------------------------------------------------
def check_contracts_in_sync() -> Result:
    """`uv run scripts/gen_contracts.py --check`: regenerate into a temp dir and byte-compare."""
    script = "scripts/gen_contracts.py"
    uv = shutil.which("uv")
    cmd = [uv, "run", script, "--check"] if uv else python(script, "--check")
    proc = run(cmd)
    if proc.returncode != 0:
        return Result("contracts-in-sync", "FAIL", f"gen_contracts.py --check exited {proc.returncode}")
    return Result("contracts-in-sync", "OK")


# --- changelog ----------------------------------------------------------------------------------
def _changed(base: str, *filters: str) -> list[str] | None:
    # --no-renames: a moved fragment counts as deleted + added; quotePath=false: UTF-8 paths as-is.
    rc, out = git(
        "-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", *filters, f"{base}...HEAD", "--"
    )
    return sorted(line for line in out.splitlines() if line) if rc == 0 else None


def _local_new_files(directory: str) -> list[str]:
    """Fragments added but not committed yet (local runs before the commit)."""
    files: set[str] = set()
    for args in (
        ("ls-files", "--others", "--exclude-standard", "--", directory),
        ("diff", "--name-only", "--diff-filter=A", "--cached", "--", directory),
    ):
        rc, out = git(*args)
        if rc == 0:
            files.update(line for line in out.splitlines() if line)
    return sorted(files)


def _pr_issues() -> list[int]:
    """Issue numbers named by `Closes #N` in the PR body, when GITHUB_EVENT_PATH provides one."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        return []
    try:
        event = json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        return []
    body = (event.get("pull_request") or {}).get("body") or ""
    return sorted({int(m.group("issue")) for m in CLOSES_RE.finditer(body)})


def fragment_problems(name: str, text: str) -> list[str]:
    """Why a fragment file is invalid (changes/README.md rules), or [] if it is valid."""
    problems: list[str] = []
    if not FRAGMENT_RE.match(name):
        problems.append(f"{name}: name must be <issue>.<{'|'.join(FRAGMENT_TYPES)}>.md")
    sentence = " ".join(text.split())
    if not sentence:
        problems.append(f"{name}: empty")
    elif "\n\n" in text.strip():
        problems.append(f"{name}: one sentence, one paragraph")
    elif not sentence.endswith(SENTENCE_END):
        problems.append(f"{name}: the sentence must end with '.', '!' or '?'")
    elif SENTENCE_BOUNDARY_RE.search(sentence):
        problems.append(f"{name}: more than one sentence")
    return problems


def check_changelog(base: str) -> Result:
    """Exactly one new valid fragment, unless this is a release PR that modifies CHANGELOG.md."""
    rc, _ = git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if rc != 0:
        return Result("changelog", "FAIL", f"base {base!r} not found (fetch it, or pass --base)")
    changelog = _changed(base, "--diff-filter=AM")
    if changelog is not None and CHANGELOG in changelog:
        return Result("changelog", "OK", "release PR: CHANGELOG.md modified")
    added = _changed(base, "--diff-filter=A")
    if added is None:
        return Result("changelog", "FAIL", f"git diff against {base} failed")
    candidates = sorted({*added, *_local_new_files(CHANGES_DIR)})
    fragments = [
        p
        for p in candidates
        if p.startswith(f"{CHANGES_DIR}/") and p.count("/") == 1 and Path(p).name not in FRAGMENT_IGNORED
    ]
    if len(fragments) != 1:
        found = ", ".join(fragments) or "none"
        return Result(
            "changelog", "FAIL", f"need exactly one new {CHANGES_DIR}/<issue>.<type>.md, found {found}"
        )
    rel = fragments[0]
    path = ROOT / rel
    if not path.is_file():
        return Result("changelog", "FAIL", f"{rel} is not in the working tree")
    problems = fragment_problems(path.name, path.read_bytes().decode("utf-8", "replace"))
    match = FRAGMENT_RE.match(path.name)
    issues = _pr_issues()
    if match and issues and int(match.group("issue")) not in issues:
        problems.append(
            f"{path.name}: issue does not match `Closes #{', #'.join(map(str, issues))}` in the PR body"
        )
    for problem in problems:
        print(problem, flush=True)
    return Result("changelog", "FAIL", "; ".join(problems)) if problems else Result("changelog", "OK", rel)


# --- determinism ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Arm:
    """One pipeline run of the gate and the files it left in its run dir."""

    label: str
    outcome: str
    reason: str | None
    run_id: str
    run_dir: Path
    files: Mapping[str, str]  # relative POSIX path -> sha256
    step_of: Mapping[str, tuple[int, str]]  # relative path -> (step index, step name)
    error: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(FILE_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_files(run_dir: Path) -> dict[str, str]:
    """sha256 of every file in a run dir, keyed by relative POSIX path, minus NEVER_COMPARED."""
    files: dict[str, str] = {}
    for path in sorted(run_dir.rglob("*")):
        rel = path.relative_to(run_dir).as_posix()
        if path.is_file() and rel not in NEVER_COMPARED and not rel.startswith(f"{SPILL_DIR}/"):
            files[rel] = sha256_file(path)
    return files


def _step_table(steps: list[list[Any]], files: Iterable[str]) -> dict[str, tuple[int, str]]:
    """Map each run-dir file to the first pipeline sub-step that declares it (path or dir prefix).

    `steps` rows are [name, contract paths, other files] from steps.STEPS; run_manifest.json never
    lists itself, so it is attributed to the `manifest` sub-step explicitly.
    """
    table: dict[str, tuple[int, str]] = {}
    for rel in files:
        for index, (name, paths, extra) in enumerate(steps):
            declared = [str(d) for d in (*paths, *extra)]
            if rel in declared or any(d.endswith("/") and rel.startswith(d) for d in declared):
                table[rel] = (index, str(name))
                break
        if rel == RUN_MANIFEST:
            manifest = [(i, str(row[0])) for i, row in enumerate(steps) if row[0] == MANIFEST_STEP]
            table[rel] = manifest[0] if manifest else (len(steps), MANIFEST_STEP)
    return table


def run_arm(
    label: str,
    case_args: Mapping[str, object],
    out_dir: Path,
    env: Mapping[str, str],
    *,
    cwd: Path = ROOT,
) -> Arm:
    args = dict(case_args, out_dir=str(out_dir), marker=RESULT_MARKER)
    cmd = python("-c", _ARM_DRIVER, json.dumps(args))
    print(
        f"$ [{label}] run_case({args['dataset']!r}, {args['case']!r}, {args['ai_mode']!r}) -> {out_dir}",
        flush=True,
    )
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=dict(env), capture_output=True, timeout=ARM_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        return Arm(label, "failed", None, "", out_dir, {}, {}, f"timed out after {ARM_TIMEOUT_S} s")
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    lines = [ln[len(RESULT_MARKER) :] for ln in stdout.splitlines() if ln.startswith(RESULT_MARKER)]
    if proc.returncode != 0 or not lines:
        output = f"{stdout[-ERROR_TAIL_CHARS:]}{stderr[-ERROR_TAIL_CHARS:]}"
        return Arm(label, "failed", None, "", out_dir, {}, {}, f"exit {proc.returncode}\n{output}")
    result: dict[str, Any] = json.loads(lines[-1])
    run_dir = Path(result["run_dir"])
    files = run_files(run_dir) if run_dir.is_dir() else {}
    return Arm(
        label,
        str(result["outcome"]),
        result.get("reason"),
        str(result["run_id"]),
        run_dir,
        files,
        _step_table(result["steps"], files),
    )


def _manifest_problems(arm: Arm) -> list[str]:
    """run_manifest.outputs must list exactly the files present, with their real hashes."""
    manifest = arm.run_dir / RUN_MANIFEST
    if not manifest.is_file():
        return [f"{arm.label}: no {RUN_MANIFEST}"]
    outputs = {o["name"]: o["sha256"] for o in json.loads(manifest.read_bytes()).get("outputs", [])}
    problems = [
        f"{arm.label}: {RUN_MANIFEST} lists {n} but the file is missing"
        for n in sorted(outputs)
        if n not in arm.files
    ]
    problems += [
        f"{arm.label}: {n} sha256 differs from {RUN_MANIFEST}"
        for n in sorted(outputs)
        if n in arm.files and arm.files[n] != outputs[n]
    ]
    unlisted = sorted(set(arm.files) - set(outputs) - {RUN_MANIFEST, RECEIPT})
    problems += [f"{arm.label}: {n} is in the run dir but not in {RUN_MANIFEST}.outputs" for n in unlisted]
    return problems


def compare_arms(a: Arm, b: Arm, only: Iterable[str] | None = None) -> list[str]:
    """Differences between two arms in pipeline order; the first is the one to debug."""
    names = set(a.files) | set(b.files)
    if only is not None:
        keep = tuple(only)
        names = {n for n in names if any(n == k or (k.endswith("/") and n.startswith(k)) for k in keep)}
    order = {**b.step_of, **a.step_of}
    diffs: list[tuple[int, str, str]] = []
    for name in names:
        ha, hb = a.files.get(name), b.files.get(name)
        if ha != hb:
            index, step = order.get(name, (len(order) + 1, "?"))
            if hb is None:
                what = f"only in {a.label}"
            elif ha is None:
                what = f"only in {b.label}"
            else:
                what = f"{a.label} {ha[:12]} != {b.label} {hb[:12]}"
            diffs.append((index, name, f"{name} (step {step}): {what}"))
    return [d[2] for d in sorted(diffs)]


def synth_unavailable() -> str | None:
    """Why the synth determinism gate cannot run yet, or None when it can."""
    if not module_available("veyltrace_core"):
        return "veyltrace_core is not installed (run via `uv run`)"
    if not module_available("veyltrace_core.pipeline"):
        return "veyltrace_core.pipeline is not written yet (R-02)"
    if SYNTH_DATASET not in {ep.name for ep in entry_points(group=ADAPTERS_GROUP)}:
        return f"no `{SYNTH_DATASET}` entry point in {ADAPTERS_GROUP} (R-03)"
    return None


def _gate_case(
    label: str, case_args: Mapping[str, object], work: Path, data_root: str, *, move_data: bool = True
) -> list[str]:
    """Run one case twice and compare every file. The arms differ in hash seed, TZ, locale, working
    directory (the second runs outside the checkout, with VEYLTRACE_CONFIG_DIR) and, with
    `move_data`, the data root's absolute path: the second arm reads a copy of the cache the first
    filled (cold, then warm). The real case keeps one root (its data is too large to copy)."""
    arms: list[Arm] = []
    for i, (seed, extra) in enumerate(zip(HASH_SEEDS, ARM_ENVIRONMENTS, strict=True)):
        root, cwd = data_root, ROOT
        if i:
            cwd = work / f"{label}-cwd"
            cwd.mkdir(parents=True, exist_ok=True)
            if move_data:
                root = str(work / f"{label}-data-copy")
                shutil.copytree(data_root, root, dirs_exist_ok=True)
        env = child_env(
            {"PYTHONHASHSEED": seed, DATA_ENV: root, CONFIG_DIR_ENV: str(ROOT / "config"), **extra}
        )
        out = work / f"{label}-seed{seed}" / "run"
        arms.append(run_arm(f"{label}/seed{seed}", case_args, out, env, cwd=cwd))
    problems = [f"{arm.label}: {arm.error}" for arm in arms if arm.error]
    problems += [
        f"{arm.label}: outcome {arm.outcome} ({arm.reason})"
        for arm in arms
        if not arm.error and arm.outcome != "ok"
    ]
    if problems:
        return problems
    first, second = arms
    problems = _manifest_problems(first) + _manifest_problems(second)
    diffs = compare_arms(first, second)
    if diffs:
        problems.append(f"{label}: {len(diffs)} file(s) differ; first: {diffs[0]}")
    print(f"{label}: {len(first.files)} files compared, {len(diffs)} differ", flush=True)
    return problems


def _fake_arm(work: Path, data_root: str) -> list[str]:
    """Record with FakeProvider, then replay that cassette under the record's run_id; compare the
    AI outputs (Relentra's step files, cassette, verdict) byte for byte (check_ci §4)."""
    base = {"dataset": SYNTH_DATASET, "case": FAKE_ARM_CASE, "overrides": dict(FAKE_OVERRIDES)}
    env = child_env({"PYTHONHASHSEED": HASH_SEEDS[0], DATA_ENV: data_root})
    record = run_arm("fake/record", {**base, "ai_mode": "record"}, work / "fake-record" / "run", env)
    if record.error or record.outcome != "ok":
        return [f"fake/record: {record.error or record.outcome}"]
    run_id = record.run_id
    env = child_env({"PYTHONHASHSEED": HASH_SEEDS[1], DATA_ENV: data_root})
    replay = run_arm(
        "fake/replay",
        {**base, "ai_mode": "replay", "run_id": run_id, "cassette_dir": str(record.run_dir / "cassette")},
        work / "fake-replay" / "run",
        env,
    )
    if replay.error or replay.outcome != "ok":
        return [f"fake/replay: {replay.error or replay.outcome}"]
    ai_files = [p for p, (_, step) in record.step_of.items() if step in AI_COMPARED_STEPS]
    diffs = compare_arms(record, replay, only=[*ai_files, CASSETTE_PREFIX])
    return [f"fake: {len(diffs)} file(s) differ; first: {diffs[0]}"] if diffs else []


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(FILE_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _real_case() -> tuple[dict[str, object] | None, str]:
    """The pinned real case from scripts/ci_real_case.json, checked before any arm runs.

    The file holds {"suite", "dataset", "case", "files": [{"path", "sha256"}]}, paths relative to
    $VEYLTRACE_DATA (critic gap "determinism gate": a corrupted or changed cached download must
    fail the gate, not pass silently). The dataset must resolve to an installed adapter.
    """
    rel = REAL_CASE_FILE.relative_to(ROOT).as_posix()
    if not REAL_CASE_FILE.is_file():
        return None, f"{rel} is missing (pinned after O-01)"
    pinned = json.loads(REAL_CASE_FILE.read_bytes())
    data = os.environ.get(DATA_ENV)
    if not data:
        return None, f"{DATA_ENV} is not set (the real case is fetched outside the checkout)"
    files = pinned.get("files") or []
    if not files:
        return None, f"{rel} pins no files (list {{path, sha256}} of the case's raw inputs)"
    for entry in files:
        path = Path(data) / str(entry["path"])
        if not path.is_file():
            return None, f"pinned file {entry['path']} is missing under {DATA_ENV}"
        got = _file_sha256(path)
        if got != entry["sha256"]:
            want = str(entry["sha256"])
            return None, f"pinned file {entry['path']}: sha256 {got[:12]} != pinned {want[:12]}"
    dataset = str(pinned["dataset"])
    probe = "import sys\nfrom veyltrace_core.adapters import adapter_for\nadapter_for(sys.argv[1])"
    proc = subprocess.run(python("-c", probe, dataset), cwd=ROOT, capture_output=True, check=False)
    if proc.returncode != 0:
        return None, f"dataset {dataset!r} resolves to no installed adapter"
    return {"dataset": dataset, "case": pinned["case"], "ai_mode": "off", "overrides": {}}, ""


def check_determinism(*, require_synth: bool, require_real_case: bool, ai_fake: bool) -> Result:
    """Run the pipeline twice per case in two subprocesses and compare every output hash."""
    missing = synth_unavailable()
    if missing:
        print(f"{SYNTH_SKIP}: {missing}", flush=True)
        if require_synth:
            return Result("determinism", "FAIL", f"--require-synth: {missing}")
        return Result("determinism", "SKIP", f"{SYNTH_SKIP}: {missing}")
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vt-determinism-") as tmp:
        work = Path(tmp)
        data_root = work / "data"  # one root: the first arm fills Infralume's cache, the second reads it
        data_root.mkdir()
        for case in SYNTH_CASES:
            args = {"dataset": SYNTH_DATASET, "case": case, "ai_mode": "off", "overrides": {}}
            problems += _gate_case(case, args, work, str(data_root))
        if ai_fake:
            problems += _fake_arm(work, str(data_root))
        if require_real_case:
            real, why = _real_case()
            if real is None:
                problems.append(f"--require-real-case: {why}")
            else:
                problems += _gate_case("real", real, work, os.environ[DATA_ENV], move_data=False)
    for problem in problems:
        print(problem, flush=True)
    if problems:
        return Result("determinism", "FAIL", problems[0].splitlines()[0])
    arms = (
        f"{len(SYNTH_CASES)} synth cases"
        + (" + fake AI" if ai_fake else "")
        + (" + real case" if require_real_case else "")
    )
    return Result("determinism", "OK", arms)


# --- golden fixtures -------------------------------------------------------------------------------
def fixture_snapshot(package: str) -> dict[str, bytes]:
    root = package_dir(package) / "fixtures"
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _summarise_fixtures(package: str, before: Mapping[str, bytes], after: Mapping[str, bytes]) -> int:
    """Print added/changed/removed fixture files with row counts and the first differences."""
    changed = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    root = package_dir(package) / "fixtures"
    print(f"{package}: {len(changed)} fixture file(s) changed", flush=True)
    parquet = [n for n in changed if n.endswith(".parquet")]
    with tempfile.TemporaryDirectory(prefix="vt-golden-") as tmp:
        pairs: list[tuple[str | None, str | None]] = []
        for n in parquet:
            old = None
            if n in before:
                old_path = Path(tmp) / f"{len(pairs)}.parquet"
                old_path.write_bytes(before[n])
                old = str(old_path)
            pairs.append((old, str(root / n) if n in after else None))
        stats: list[dict[str, Any]] = []
        if pairs:
            proc = subprocess.run(
                python("-c", _PARQUET_SUMMARY, json.dumps(pairs), str(DIFF_PREVIEW)),
                cwd=ROOT,
                env=child_env(),
                capture_output=True,
                check=False,
            )
            stats = json.loads(proc.stdout) if proc.returncode == 0 else []
    pq_stats = dict(zip(parquet, stats, strict=False))
    for n in changed:
        state = "added" if n not in before else "removed" if n not in after else "changed"
        print(f"  {state:8} {n} ({len(before.get(n, b''))} -> {len(after.get(n, b''))} bytes)", flush=True)
        if n in pq_stats:
            s = pq_stats[n]
            print(f"           rows {s['old_rows']} -> {s['new_rows']}", flush=True)
            for i, old, new in s["rows"]:
                print(f"           row {i}: - {old}\n           row {i}: + {new}", flush=True)
        elif Path(n).suffix in TEXT_FIXTURE_SUFFIXES and state == "changed":
            diff = difflib.unified_diff(
                before[n].decode("utf-8", "replace").splitlines(),
                after[n].decode("utf-8", "replace").splitlines(),
                lineterm="",
                n=0,
            )
            for line in list(diff)[UNIFIED_DIFF_HEADER : UNIFIED_DIFF_HEADER + DIFF_PREVIEW]:
                print(f"           {line}", flush=True)
    return len(changed)


def check_update_golden(package: str | None, cascade: bool) -> Result:
    """Regenerate golden fixtures through the core testing module, then summarise the changes."""
    if os.environ.get("CI"):
        return Result(
            "update-golden", "FAIL", "refused: CI is set (fixtures are refreshed locally and reviewed)"
        )
    if not module_available(UPDATE_GOLDEN_MODULE):
        return Result(
            "update-golden", "FAIL", f"{UPDATE_GOLDEN_MODULE} is not available yet (core testing, R-02)"
        )
    plan: list[tuple[str, tuple[str, ...]]]
    if cascade:
        start = next((i for i, (p, _) in enumerate(CASCADE) if p == package), 0) if package else 0
        plan = list(CASCADE[start:])
    else:
        assert package is not None
        plan = [(package, ())]
    changed = 0
    for pkg, steps in plan:
        before = fixture_snapshot(pkg)
        args = ["-m", UPDATE_GOLDEN_MODULE, "--package", pkg]
        for name in steps:
            args += ["--step", name]
        proc = run(python(*args), env=child_env({"PYTHONHASHSEED": HASH_SEEDS[0]}))
        if proc.returncode != 0:
            return Result("update-golden", "FAIL", f"{pkg} {' '.join(steps)}: exit {proc.returncode}")
        changed += _summarise_fixtures(pkg, before, fixture_snapshot(pkg))
    scope = "cascade" if cascade else package
    return Result("update-golden", "OK", f"{scope}: {changed} file(s) changed; review them like code")


def check_fixtures_stale() -> Result:
    """Upstream fixtures changed without a downstream refresh (non-required job, check_ci §5.3).

    The test only runs with FIXTURES_STALE_ENV set, so the required `--tests` job never fails on a
    stale fixture (critic gap "fixture cascade")."""
    if not (ROOT / FIXTURE_CONSISTENCY_TEST).is_file():
        return Result("fixtures-stale", "SKIP", f"{FIXTURE_CONSISTENCY_TEST} not written yet")
    return check_pytest(
        "fixtures-stale", [FIXTURE_CONSISTENCY_TEST], env=child_env({FIXTURES_STALE_ENV: "1"})
    )


# --- packages ----------------------------------------------------------------------------------------
def package_dir(package: str) -> Path:
    if package in WORKSPACE_PACKAGES:
        return ROOT / "packages" / package
    return ROOT / {"bench": "bench", "lab": "lab", "console": "console", "contracts": "contracts"}[package]


def package_path(package: str) -> str:
    return package_dir(package).relative_to(ROOT).as_posix()


def _has_python(path: Path) -> bool:
    return path.is_dir() and any(True for _ in path.rglob("*.py"))


def package_checks(package: str, *, lint: bool, types: bool, tests: bool, isolation: bool) -> list[Result]:
    """The selected checks scoped to one package (each package type has its own subset)."""
    path = package_path(package)
    results: list[Result] = []
    if package == "console":
        if not (ROOT / "console" / "package.json").is_file():
            return [Result("console", "SKIP", "console/package.json not present yet")]
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            return [Result("console", "FAIL", "pnpm not found on PATH")]
        proc = run([pnpm, "-C", "console", "check"])
        return [
            Result(
                "console",
                "OK" if proc.returncode == 0 else "FAIL",
                "" if proc.returncode == 0 else f"pnpm check exited {proc.returncode}",
            )
        ]
    if package == "lab":
        if not _has_python(ROOT / "lab"):
            return [Result("lab", "SKIP", "no Python under lab/ yet")]
        if lint:
            results.append(check_lint([path]))
        if tests:
            lab_tests = ROOT / "lab" / "tests"
            results.append(
                check_pytest("tests", [path])
                if lab_tests.is_dir()
                else Result("tests", "SKIP", "no lab/tests yet")
            )
        return results
    if package == "contracts":
        if lint:
            proc = run(python("-m", "ruff", "check", GENERATED_PYTHON))
            results.append(
                Result(
                    "lint",
                    "OK" if proc.returncode == 0 else "FAIL",
                    "generated: ruff check" if proc.returncode == 0 else "ruff check failed",
                )
            )
        if tests:
            present = [t for t in CONTRACT_TESTS if (ROOT / t).is_file()]
            results.append(
                check_pytest("tests", present) if present else Result("tests", "SKIP", "no contract tests")
            )
            results.append(check_contracts_in_sync())
        return results
    if lint:
        results.append(check_lint([path]))
    if types:
        results.append(check_types([path]))
    if tests:
        results.append(check_tests(package))
    if isolation and package in WORKSPACE_PACKAGES:
        results.append(check_isolation(package))
    return results


# --- CLI -------------------------------------------------------------------------------------------
def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="check.py",
        description="Veyltrace checks (10 §5.2). Exit 0 pass, 1 check failed, 2 usage.",
    )
    ap.add_argument(
        "--package", choices=PACKAGE_NAMES, help="scope lint/types/tests/isolation to one package"
    )
    ap.add_argument("--lint", action="store_true", help="ruff check + ruff format --check")
    ap.add_argument("--types", action="store_true", help="pyright (strict where configured)")
    ap.add_argument("--tests", action="store_true", help="pytest packages tests bench, hypothesis CI profile")
    ap.add_argument("--isolation", action="store_true", help="tests/test_isolation.py + determinism lint")
    ap.add_argument(
        "--determinism", action="store_true", help="pipeline twice per synth case, compare hashes"
    )
    ap.add_argument(
        "--require-synth", action="store_true", help="with --determinism: fail instead of skipping"
    )
    ap.add_argument(
        "--require-real-case", action="store_true", help="with --determinism: add the pinned real case"
    )
    ap.add_argument(
        "--ai-fake", action="store_true", help="with --determinism: add the FakeProvider record/replay arm"
    )
    ap.add_argument("--contracts-in-sync", action="store_true", help="gen_contracts.py --check")
    ap.add_argument("--changelog", action="store_true", help="one valid changes/<issue>.<type>.md fragment")
    ap.add_argument("--base", default=None, help=f"with --changelog: base ref (default {DEFAULT_BASE})")
    ap.add_argument(
        "--update-golden", action="store_true", help="regenerate --package fixtures (never in CI)"
    )
    ap.add_argument(
        "--cascade", action="store_true", help="with --update-golden: every producer in pipeline order"
    )
    ap.add_argument(
        "--fixtures-stale", action="store_true", help="report fixtures built from stale upstreams"
    )
    args = ap.parse_args(argv)
    gate_flags = args.require_synth or args.require_real_case or args.ai_fake
    if gate_flags and not args.determinism:
        ap.error("--require-synth, --require-real-case and --ai-fake need --determinism")
    if args.base is not None and not args.changelog:
        ap.error("--base needs --changelog")
    if args.cascade and not args.update_golden:
        ap.error("--cascade needs --update-golden")
    if args.update_golden and not args.package and not args.cascade:
        ap.error("--update-golden needs --package (or --cascade)")
    if args.update_golden and args.package in {"contracts", "lab", "console"}:
        ap.error(f"--update-golden: {args.package} has no golden fixtures")
    selected = (
        args.lint,
        args.types,
        args.tests,
        args.isolation,
        args.determinism,
        args.contracts_in_sync,
        args.changelog,
        args.update_golden,
        args.fixtures_stale,
    )
    if not args.package and not any(selected):
        ap.error("choose a check (e.g. --package core, --lint, --tests, --determinism)")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    results: list[Result] = []
    basic = (args.lint, args.types, args.tests, args.isolation)
    if args.package and not args.update_golden:
        everything = not any(basic) and not any(
            (args.determinism, args.contracts_in_sync, args.changelog, args.fixtures_stale)
        )
        lint, types, tests, isolation = (True,) * 4 if everything else basic
        results += package_checks(args.package, lint=lint, types=types, tests=tests, isolation=isolation)
    else:
        if args.lint:
            results.append(check_lint(["."], generated=True))
        if args.types:
            results.append(check_types())
        if args.tests:
            results.append(check_tests())
        if args.isolation:
            results.append(check_isolation())
    if args.contracts_in_sync:
        results.append(check_contracts_in_sync())
    if args.changelog:
        results.append(check_changelog(args.base or DEFAULT_BASE))
    if args.determinism:
        results.append(
            check_determinism(
                require_synth=args.require_synth,
                require_real_case=args.require_real_case,
                ai_fake=args.ai_fake,
            )
        )
    if args.fixtures_stale:
        results.append(check_fixtures_stale())
    if args.update_golden:
        results.append(check_update_golden(args.package, args.cascade))
    print("\n== summary ==", flush=True)
    for result in results:
        print(result.line, flush=True)
    return EXIT_FAIL if any(r.status == "FAIL" for r in results) else EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
