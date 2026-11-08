"""The pipeline runner: one case, the 14 sub-steps of `steps.STEPS`, in order, in-process.

`execute(plan)` is the single analysis code path for offline, batch, live and replay runs
(02 §5). It resolves the config and the run id before step 0, checks that every engine (and,
under the detected protocol, the alert detector) is installed, then runs the selected sub-steps
sequentially (D-17). It owns the run directory (02 §4.1):

- `runs/<dataset>/<case_id>/<run_id>/` for a full run; a partial run (stopping before
  causivra.receipt) writes to `<run_id>~<last sub-step>/` so it never clears a full run
  (M0 lead decision 2026-11-06).
- A finished directory (receipt.json present) is returned unchanged, except that `record`
  refuses to overwrite it without `force_record`, and nothing is reused while the work tree is
  dirty (code_commit = "<sha>+dirty.<12 hex>", lead decision §2.9). Anything else is cleared and
  re-run, under a lock file so a concurrent worker's directory is never cleared.
- The `manifest` sub-step writes config.lock.json and run_manifest.json, whose `outputs` and
  `steps[].outputs` come from the known run-dir paths only; any other file fails the step.

Outcomes: `NoAlert` → no_alert, `CaseRejected` → rejected, anything else → failed; none of them
writes a manifest or receipt. Errors found before the run starts (bad usage, config, missing
plugins, a held lock) are raised. Wall time per step comes from time.perf_counter, is reported in
`RunSummary.wall_ms` only and never reaches an artefact (lead decision §2.12).

Not engine-facing: imports importlib.metadata (plugins, env_info) and runs git in a subprocess.
"""

from __future__ import annotations

import hashlib
import math
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from veyltrace_contracts.models import CaseManifest, RunManifest
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io as contract_io
from veyltrace_core import plugins, textio
from veyltrace_core.adapters import adapter_for
from veyltrace_core.alert import run_alert_step
from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import (
    ResolvedConfig,
    data_root,
    find_config_dir,
    load_section_file,
    resolve_config,
)
from veyltrace_core.context import AIManifest, EngineResult, EngineStatus, RunContext, RunPlan
from veyltrace_core.errors import (
    ArtifactMissing,
    CaseRejected,
    ConfigError,
    ContractValidationError,
    DiagnoseExit,
    InputChanged,
    NoAlert,
    RunDirUnavailable,
    StepFailed,
    UsageError,
    VeyltraceError,
    exit_code_for,
)
from veyltrace_core.hashing import manifest_hash, sha256_bytes, sha256_file, sha256_json, sha256_text_lf
from veyltrace_core.hint import HINT_READERS
from veyltrace_core.ids import AIMode, derived_run_id, dirty_commit, is_case_id, is_code_commit, is_run_id
from veyltrace_core.ids import run_id as make_run_id
from veyltrace_core.locks import PathLock
from veyltrace_core.log import get_logger
from veyltrace_core.steps import CORE_ENGINE, FIRST_STEP, STEPS, Step, index_of, select

__all__ = [
    "CASSETTE_DIR",
    "DIRTY_EXCLUDES",
    "DIRTY_PATHS",
    "ENV_LIBS",
    "EXCLUDED_OUTPUTS",
    "PARTIAL_SEPARATOR",
    "UNCALIBRATED_SHA256",
    "Outcome",
    "RunSummary",
    "StepEvent",
    "StepRecord",
    "code_commit",
    "env_info",
    "execute",
    "find_run",
    "is_finished",
    "run_case",
    "run_dir_for",
    "runs_root",
    "summary_dict",
    "uv_lock_sha256",
    "write_summary",
]

Outcome = Literal["ok", "failed", "no_alert", "rejected"]
EventKind = Literal["started", "finished", "skipped", "failed"]

#: Analysis-relevant distributions recorded in run_manifest.env.libs. A fixed tuple, because the
#: set of installed distributions differs by OS (colorama, tzdata on Windows) and replay must not
#: report drift for a Windows-recorded receipt on Linux CI (critic gap, accepted).
ENV_LIBS: tuple[str, ...] = (
    "drain3",
    "duckdb",
    "networkx",
    "numpy",
    "pyarrow",
    "pydantic",
    "pyyaml",
    "scipy",
)
#: Work-tree paths whose uncommitted changes make a run dirty, and the exclusions inside them
#: (lead decision §2.9): bench writes calibration files and results mid-experiment.
#: The root uv.lock and pyproject.toml count too: an uncommitted dependency change (uv lock
#: --upgrade, uv add) changes library versions, so a finished run dir must not be reused.
DIRTY_PATHS: tuple[str, ...] = ("packages", "contracts", "config", "uv.lock", "pyproject.toml")
DIRTY_EXCLUDES: tuple[str, ...] = ("config/calibration", "bench/results", "runs")
#: Files a run directory holds that run_manifest.outputs never lists (03 §12).
EXCLUDED_OUTPUTS: frozenset[str] = frozenset({"run_manifest.json", "receipt.json", "receipt.json.minisig"})
#: Scratch directories at the top of a run dir (DuckDB spill, lead decision §2.3) and OS clutter
#: files anywhere in it; neither is an output nor a reason to fail the manifest step.
_IGNORED_DIRS: frozenset[str] = frozenset({".duck-tmp", ".tmp"})
_IGNORED_FILES: frozenset[str] = frozenset({"desktop.ini", "Thumbs.db", ".DS_Store"})
#: `<run_id>~<last sub-step>` names a partial run directory (lead decision §2.4).
PARTIAL_SEPARATOR = "~"
#: run_manifest.calibration_sha256 of an uncalibrated run (03 §12).
UNCALIBRATED_SHA256 = sha256_json({"family": "uncalibrated"})
#: uv_lock_sha256 when no uv.lock is found next to the code (an installed wheel); a priori.
NO_UV_LOCK_SHA256 = sha256_json({"uv_lock": None})
_UNKNOWN_COMMIT = "unknown"
_FIXTURE_COMMIT = "fixture"
_MS_PER_S = 1000.0
_SUMMARY_SCHEMA = "veyltrace.run_summary/1"  # same key as cli.SUMMARY_FORMAT
_PATHS_KEY = "core.paths"  # ResolvedConfig.environment key of the paths subtree
_DEFAULT_RUNS = "runs"  # config/core.yaml paths.runs default (02 §4.1)
#: The LLM cassette directory in a run dir (02 §4.1; steps.STEPS "cassette/").
CASSETTE_DIR = "cassette"
_MAX_LISTED = 10  # how many unexpected paths an error message names

_log = get_logger(__name__)


# --- Results -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class StepEvent:
    """A progress notification: a sub-step started, finished, was skipped or failed."""

    index: int
    name: str
    event: EventKind
    result: EngineResult | None


@dataclass(frozen=True)
class StepRecord:
    """One run_manifest.steps entry: sub-step name, status and the files it wrote (name, sha256)."""

    name: str
    status: EngineStatus
    outputs: tuple[tuple[str, str], ...] = ()

    def as_json(self) -> dict[str, Any]:
        """The run_manifest.steps[] form."""
        files = [{"name": name, "sha256": digest} for name, digest in self.outputs]
        return {"name": self.name, "status": self.status, "outputs": files}


@dataclass(frozen=True)
class RunSummary:
    """What one execute() call did (core_api_spec §10, with the critic's summary fields).

    `steps` and `results` are aligned, one entry per selected sub-step, in pipeline order;
    `outputs` equals run_manifest.outputs (or the same listing for a partial run). `cached` is
    True when a finished run directory was returned unchanged (then `steps` and `results` are
    empty). `wall_ms` is per sub-step and never written into the run directory. `error` keeps the
    exception of a failed step for the CLI; it is not part of equality.
    """

    dataset: str
    case_id: str
    run_id: str
    run_dir: Path
    outcome: Outcome
    reason: str | None
    failed_step: str | None
    results: tuple[EngineResult, ...]
    outputs: tuple[tuple[str, str], ...]
    wall_ms: Mapping[str, float]
    steps: tuple[StepRecord, ...] = ()
    cached: bool = False
    exit_code: int = int(DiagnoseExit.OK)
    error: BaseException | None = field(default=None, compare=False, repr=False)


# --- Environment -------------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> bytes:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}
    done = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        env=env,
    )
    return done.stdout


def _pathspecs() -> list[str]:
    return [*DIRTY_PATHS, *(f":(exclude){path}" for path in DIRTY_EXCLUDES)]


def code_commit(repo: Path | None = None) -> tuple[str, bool]:
    """(code commit, dirty) of the work tree holding `repo` (default: this package's source).

    Clean: (HEAD sha, False). Dirty under packages/, contracts/ or config/ (excluding
    config/calibration/), or in the root uv.lock or pyproject.toml: ("<sha>+dirty.<12 hex>",
    True), where the hex hashes `git diff HEAD` plus the names and bytes of untracked files
    there, so different edits give different run ids.
    Outside a git checkout (an installed wheel) or without git: ("unknown", True).
    """
    cwd = repo if repo is not None else Path(__file__).resolve().parent
    try:
        head = _git(cwd, "rev-parse", "HEAD").decode("ascii").strip()
        top = Path(_git(cwd, "rev-parse", "--show-toplevel").decode("utf-8").strip())
        status = _git(top, "status", "--porcelain", "--untracked-files=all", "--", *_pathspecs())
        if not status.strip():
            return head, False
        digest = hashlib.sha256(_git(top, "diff", "HEAD", "--binary", "--", *_pathspecs()))
        untracked = _git(top, "ls-files", "--others", "--exclude-standard", "-z", "--", *_pathspecs())
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        return _UNKNOWN_COMMIT, True
    for name in sorted(n for n in untracked.split(b"\0") if n):
        digest.update(b"\0untracked\0" + name + b"\0")
        digest.update(sha256_file(top / name.decode("utf-8")).encode("ascii"))
    if not is_code_commit(head):
        return _UNKNOWN_COMMIT, True
    return dirty_commit(head, digest.hexdigest()), True


def env_info() -> dict[str, Any]:
    """run_manifest.env: Python version, OS name (reported, never compared) and ENV_LIBS versions.

    Distributions from ENV_LIBS that are not installed are left out.
    """
    libs: dict[str, str] = {}
    for name in ENV_LIBS:
        try:
            libs[name] = dist_version(name)
        except PackageNotFoundError:
            continue
    return {"python": platform.python_version(), "os": platform.system().lower(), "libs": libs}


def uv_lock_sha256(start: Path | None = None) -> str:
    """sha256_text_lf of the nearest uv.lock above `start` (default: this package's source), so a
    CRLF checkout hashes like an LF one; NO_UV_LOCK_SHA256 if there is none."""
    here = (start if start is not None else Path(__file__)).resolve()
    for folder in (here, *here.parents):
        candidate = folder / "uv.lock"
        if candidate.is_file():
            return sha256_text_lf(candidate)
    return NO_UV_LOCK_SHA256


# --- Run-directory layout ----------------------------------------------------------------------
def _step_paths(step: Step) -> tuple[frozenset[str], tuple[str, ...]]:
    """(exact run-dir files, directory prefixes ending in "/") a sub-step may write."""
    exact = {CONTRACTS[name].path for name in step.outputs}
    prefixes: list[str] = []
    for entry in step.files:
        if entry.endswith("/"):
            prefixes.append(entry)
        else:
            exact.add(entry)
    return frozenset(exact), tuple(prefixes)


def _layout(steps: Iterable[Step]) -> tuple[frozenset[str], tuple[str, ...]]:
    exact: set[str] = set()
    prefixes: set[str] = set()
    for step in steps:
        files, dirs = _step_paths(step)
        exact |= files
        prefixes |= set(dirs)
    return frozenset(exact), tuple(sorted(prefixes))


_ALL_FILES, _ALL_PREFIXES = _layout(STEPS)


def _is_known(
    rel: str, exact: frozenset[str] = _ALL_FILES, prefixes: tuple[str, ...] = _ALL_PREFIXES
) -> bool:
    return rel in exact or any(rel.startswith(prefix) and rel != prefix for prefix in prefixes)


def _is_tmp(rel: str) -> bool:
    """A leftover atomic-write temp file (<known path>.tmp-<pid>, textio)."""
    head, sep, pid = rel.rpartition(textio.TMP_INFIX)
    return bool(sep) and pid.isdigit() and _is_known(head)


def _walk(run_dir: Path) -> list[str]:
    """Every file under `run_dir` as a sorted POSIX relative path, without ignored entries."""
    found: list[str] = []
    if not run_dir.is_dir():
        return found
    for root, dirs, files in os.walk(run_dir):
        here = Path(root)
        if here == run_dir:
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]
        dirs.sort()
        for name in sorted(files):
            if name not in _IGNORED_FILES:
                found.append((here / name).relative_to(run_dir).as_posix())
    return sorted(found)


def _files_under(run_dir: Path, prefix: str) -> list[str]:
    return [f"{prefix}{rel}" for rel in _walk(run_dir / prefix)]


def _hash_paths(run_dir: Path, rels: Iterable[str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((rel, sha256_file(run_dir / rel)) for rel in rels))


def _present(run_dir: Path, step: Step) -> dict[str, str]:
    """{path: sha256} of the files a sub-step may write that exist now."""
    exact, prefixes = _step_paths(step)
    rels = [rel for rel in sorted(exact) if (run_dir / rel).is_file()]
    for prefix in prefixes:
        rels.extend(_files_under(run_dir, prefix))
    return dict(_hash_paths(run_dir, rels))


def _written_by(step: Step, run_dir: Path, before: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """The files a sub-step wrote: its exact paths that exist, plus files under its directory
    prefixes (the cassette, which several steps share) that are new or changed."""
    exact, _ = _step_paths(step)
    now = _present(run_dir, step)
    return tuple(
        sorted((rel, digest) for rel, digest in now.items() if rel in exact or before.get(rel) != digest)
    )


def _collect_outputs(run_dir: Path, *, strict: bool) -> tuple[tuple[str, str], ...]:
    """run_manifest.outputs: every known file except EXCLUDED_OUTPUTS, sorted by name.

    With `strict`, any other file (unknown names, leftover temp files) is a ContractValidationError,
    so stray files never slip into or past the manifest (critic gap, accepted).
    """
    rels = [rel for rel in _walk(run_dir) if rel not in EXCLUDED_OUTPUTS]
    unexpected = [rel for rel in rels if not _is_known(rel)]
    if strict and unexpected:
        listed = ", ".join(unexpected[:_MAX_LISTED])
        raise ContractValidationError("run_manifest", f"unexpected files in the run dir: {listed}")
    return _hash_paths(run_dir, [rel for rel in rels if _is_known(rel)])


def run_dir_for(root: Path, dataset: str, case_id: str, run_id: str, last_step: str | None = None) -> Path:
    """`<root>/<dataset>/<case_id>/<run_id>[~<last_step>]` (02 §4.1; lead decision §2.4)."""
    name = run_id if last_step is None else f"{run_id}{PARTIAL_SEPARATOR}{last_step}"
    return root / dataset / case_id / name


def is_finished(run_dir: Path) -> bool:
    """True when the run wrote its receipt (the last artefact, step 10b)."""
    return (run_dir / CONTRACTS["receipt"].path).is_file()


def find_run(run_id: str, root: Path) -> Path | None:
    """The full run directory `<root>/*/*/<run_id>`, or None (partial runs are not found)."""
    if not is_run_id(run_id) or not root.is_dir():
        return None
    matches = sorted(p for p in root.glob(f"*/*/{run_id}") if p.is_dir())
    return matches[0] if matches else None


def _clear(run_dir: Path) -> None:
    """Remove a run directory's contents, refusing if it holds anything a run never writes."""
    if not run_dir.exists():
        return
    if not run_dir.is_dir():
        msg = f"run dir {run_dir} exists and is not a directory"
        raise UsageError(msg)
    rels = _walk(run_dir)
    unknown = [rel for rel in rels if not (_is_known(rel) or rel in EXCLUDED_OUTPUTS or _is_tmp(rel))]
    if unknown:
        listed = ", ".join(unknown[:_MAX_LISTED])
        msg = f"refusing to clear {run_dir}: it holds files no run writes ({listed})"
        raise UsageError(msg)
    shutil.rmtree(run_dir)


def _remove(run_dir: Path, rels: Iterable[str]) -> None:
    for rel in rels:
        (run_dir / rel).unlink(missing_ok=True)


# --- Execution ---------------------------------------------------------------------------------
@dataclass
class _Run:
    """Mutable state of one execute() call (private)."""

    plan: RunPlan
    resolved: ResolvedConfig
    case_id: str
    run_id: str
    run_dir: Path
    commit: str
    dirty: bool
    config_bytes: bytes
    config_sha256: str
    cassette_dir: Path | None
    preflight: plugins.Preflight
    progress: Callable[[StepEvent], None] | None
    prior: list[StepRecord] = field(default_factory=lambda: [])
    records: list[StepRecord] = field(default_factory=lambda: [])
    results: list[EngineResult] = field(default_factory=lambda: [])
    wall_ms: dict[str, float] = field(default_factory=lambda: {})

    def emit(self, step: Step, event: EventKind, result: EngineResult | None) -> None:
        if self.progress is not None:
            self.progress(StepEvent(index=step.index, name=step.name, event=event, result=result))

    def context(self, step: Step) -> RunContext:
        return RunContext(
            case_id=self.case_id,
            run_id=self.run_id,
            dataset=self.plan.dataset,
            run_dir=self.run_dir,
            ai_mode=self.plan.ai_mode,
            engine=step.runner,
            config=self.resolved.engine(step.engine if step.engine is not None else CORE_ENGINE),
            phase=step.phase,
            step=step.name,
            cassette_dir=self.cassette_dir,
            force_record=self.plan.force_record,
            resolved=self.resolved,
            unredacted_hint=step.name in HINT_READERS,
        )


def _resolve(plan: RunPlan) -> ResolvedConfig:
    if plan.config is not None:
        return plan.config.with_overrides(plan.overrides) if plan.overrides else plan.config
    if plan.config_dir is not None:
        return resolve_config(
            plan.overrides, config_dir=plan.config_dir, dataset=plan.dataset, ai_mode=plan.ai_mode
        )
    return resolve_config(plan.overrides, dataset=plan.dataset, ai_mode=plan.ai_mode)


def _case_id(plan: RunPlan) -> str:
    if is_case_id(plan.case):
        return plan.case
    return adapter_for(plan.dataset).resolve(plan.dataset, plan.case, data_root()).case_id


def _code(plan: RunPlan) -> tuple[str, bool]:
    if plan.code_commit is None:
        return code_commit()
    if not is_code_commit(plan.code_commit):
        msg = (
            f"code_commit must be a git sha, 'fixture' or 'unknown' (+dirty.<hex>), got {plan.code_commit!r}"
        )
        raise UsageError(msg)
    dirty = "+dirty." in plan.code_commit or plan.code_commit.startswith(_UNKNOWN_COMMIT)
    return plan.code_commit, dirty


def _get(mapping: Mapping[str, Any], *keys: str) -> object:
    node: object = mapping
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = cast("Mapping[str, object]", node)[key]
    return node


def runs_root(resolved: ResolvedConfig | None = None) -> Path:
    """The absolute runs root: `core.paths.runs` (an environment key, never in the lock), relative
    to the repository root (the config directory's parent), so the CWD does not matter.

    Uses the run's config when it knows its source directory, else finds config/ from the CWD
    (find_config_dir; ConfigError if there is none).
    """
    if resolved is not None and resolved.source is not None:
        config_dir = resolved.source.config_dir
        paths = resolved.environment.get(_PATHS_KEY)
    else:
        config_dir = find_config_dir()
        paths = load_section_file(CORE_ENGINE, config_dir=config_dir).get("paths")
    configured = _get(cast("Mapping[str, Any]", {"paths": paths}), "paths", "runs")
    root = Path(configured) if isinstance(configured, str) and configured else Path(_DEFAULT_RUNS)
    return root if root.is_absolute() else config_dir.parent / root


def _cassette_dir(
    plan: RunPlan, run_dir: Path, root: Path | None, case_id: str, config_sha256: str, commit: str
) -> Path | None:
    """record: <run_dir>/cassette; replay: the plan's (D-9), else the matching record run's."""
    if plan.ai_mode == "off":
        return None
    if plan.ai_mode == "record":
        return run_dir / CASSETTE_DIR
    if plan.cassette_dir is not None:
        return plan.cassette_dir
    if root is None:  # pragma: no cover - execute() computes the root for this case
        msg = "replay needs cassette_dir or a runs root to find the record run"
        raise UsageError(msg)
    record_id = make_run_id(case_id, config_sha256, commit, "record")
    return run_dir_for(root, plan.dataset, case_id, record_id) / CASSETTE_DIR


def _check_result(step: Step, result: object, run_dir: Path) -> EngineResult:
    """The engine returned an EngineResult for itself whose outputs are its own files, as written."""
    if not isinstance(result, EngineResult):
        raise ContractValidationError(step.name, f"engine returned {type(result).__name__}, not EngineResult")
    if result.engine != step.runner:
        raise ContractValidationError(step.name, f"result is for {result.engine!r}, expected {step.runner!r}")
    exact, prefixes = _step_paths(step)
    for name, digest in result.outputs:
        rel = CONTRACTS[name].path if name in CONTRACTS else name
        if not _is_known(rel, exact, prefixes):
            raise ContractValidationError(
                step.name, f"reports output {name!r}, which this step does not write"
            )
        path = run_dir / rel
        if not path.is_file():
            raise ContractValidationError(step.name, f"reports output {name!r}, but {rel} is missing")
        actual = sha256_file(path)
        if actual != digest:
            raise ContractValidationError(step.name, f"reports {name!r} as {digest}, file is {actual}")
    return result


def _write_external_proposals(run: _Run, step: Step) -> EngineResult:
    """Derived MCP run (02 §4.1): the caller's proposals take Relentra's place at step 7."""
    proposals = run.plan.external_proposals
    if proposals is None:  # pragma: no cover - guarded by the caller
        raise ContractValidationError(step.name, "no external proposals")
    digest = contract_io.write("proposals", proposals, run.run_dir)
    return EngineResult(
        engine=CORE_ENGINE, status="ok", outputs=(("proposals", digest),), notes=("external proposals",)
    )


def _merge_ai(run: _Run) -> dict[str, Any]:
    """run_manifest.ai: merge every engine's AIManifest (02 §6.10; core_api_spec §7)."""
    mode: AIMode = run.plan.ai_mode
    empty: dict[str, Any] = dict.fromkeys(
        ("provider", "model", "gguf_sha256", "prompt_sha256", "schema_sha256", "cassette_sha256")
    )
    if mode == "off":
        return {"mode": "off", **empty}
    identity: dict[str, set[str]] = {"provider": set(), "model": set(), "gguf_sha256": set()}
    prompts: dict[str, str] = {}
    schemas: dict[str, str] = {}
    for result in run.results:
        report: AIManifest | None = result.ai_manifest
        if report is None:
            continue
        for key, value in (
            ("provider", report.provider),
            ("model", report.model),
            ("gguf_sha256", report.gguf_sha256),
        ):
            if value is not None:
                identity[key].add(value)
        for target, pairs in ((prompts, report.prompts), (schemas, report.schemas)):
            for name, digest in pairs:
                key = f"{result.engine}/{name}"
                if target.setdefault(key, digest) != digest:
                    msg = f"engines report two hashes for {key}"
                    raise ConfigError(msg)
    merged: dict[str, Any] = {"mode": mode, **empty}
    for key, values in identity.items():
        if len(values) > 1:
            msg = f"engines disagree on the LLM {key}: {sorted(values)}"
            raise ConfigError(msg)
        merged[key] = next(iter(values)) if values else None
    merged["prompt_sha256"] = manifest_hash(prompts.items()) if prompts else None
    merged["schema_sha256"] = manifest_hash(schemas.items()) if schemas else None
    cassette = run.cassette_dir
    if cassette is not None and cassette.is_dir():
        entries = [(rel, sha256_file(cassette / rel)) for rel in _walk(cassette)]
        merged["cassette_sha256"] = manifest_hash(entries) if entries else None
    return merged


def _write_manifest(run: _Run, step: Step) -> tuple[EngineResult, StepRecord]:
    """The manifest sub-step: config.lock.json, then run_manifest.json (03 §12, §12.2)."""
    lock_rel = CONTRACTS["config_lock"].path
    textio.write_bytes(run.run_dir / lock_rel, run.config_bytes)
    lock_sha = sha256_file(run.run_dir / lock_rel)
    if lock_sha != run.config_sha256:  # pragma: no cover - write_bytes is byte-exact
        raise ContractValidationError("config_lock", "written bytes differ from the resolved lock")
    case = contract_io.read("case_manifest", run.run_dir)
    if not isinstance(case, CaseManifest):  # pragma: no cover - io returns the model
        raise ContractValidationError("case_manifest", "did not read as a CaseManifest")
    if case.case_id != run.case_id or case.dataset != run.plan.dataset:
        detail = f"is for {case.dataset}/{case.case_id}, the run is {run.plan.dataset}/{run.case_id}"
        raise ContractValidationError("case_manifest", detail)
    env = dict(run.plan.env) if run.plan.env is not None else env_info()
    uv_lock = str(env.pop("uv_lock_sha256", None) or uv_lock_sha256())
    calibration = run.resolved.calibration
    record = StepRecord(name=step.name, status="ok", outputs=((lock_rel, lock_sha),))
    data: dict[str, Any] = {
        "schema_version": CONTRACTS["run_manifest"].version,
        "run_id": run.run_id,
        "case_id": run.case_id,
        "dataset": run.plan.dataset,
        "code": {"commit": run.commit, "dirty": run.dirty},
        "env": env,
        "config_sha256": run.config_sha256,
        "uv_lock_sha256": uv_lock,
        "calibration_sha256": UNCALIBRATED_SHA256 if calibration is None else calibration.sha256,
        "inputs": [{"name": i.name, "sha256": i.sha256} for i in sorted(case.inputs, key=lambda i: i.name)],
        "outputs": [{"name": n, "sha256": h} for n, h in _collect_outputs(run.run_dir, strict=True)],
        "ai": _merge_ai(run),
        "steps": [r.as_json() for r in (*run.prior, *run.records, record)],
    }
    manifest_sha = contract_io.write("run_manifest", data, run.run_dir)
    result = EngineResult(
        engine=CORE_ENGINE,
        status="ok",
        outputs=(("config_lock", lock_sha), ("run_manifest", manifest_sha)),
    )
    return result, record


def _run_step(run: _Run, step: Step) -> tuple[EngineResult, StepRecord]:
    """Run one sub-step and return its result and run_manifest.steps record."""
    if step.name == "manifest":
        return _write_manifest(run, step)
    before = _present(run.run_dir, step)
    if step.name == "alert":
        result = run_alert_step(run.context(step), detector=run.preflight.alert_detector)
    elif step.name == "relentra" and run.plan.external_proposals is not None:
        result = _write_external_proposals(run, step)
    elif step.name == "relentra" and run.plan.ai_mode == "off":
        result = EngineResult.skipped(step.runner, "ai_mode is off (02 §4 step 7)")
    else:
        engine = step.engine if step.engine is not None else CORE_ENGINE
        result = _check_result(step, run.preflight.engines[engine](run.context(step)), run.run_dir)
    outputs = () if result.status == "skipped" else _written_by(step, run.run_dir, before)
    return result, StepRecord(name=step.name, status=result.status, outputs=outputs)


def _failure(exc: BaseException) -> tuple[Outcome, str]:
    if isinstance(exc, NoAlert):
        return "no_alert", str(exc) or "no alert"
    if isinstance(exc, CaseRejected):
        return "rejected", exc.reason
    return "failed", f"{type(exc).__name__}: {exc}"


def _run_all(run: _Run, selected: tuple[Step, ...]) -> RunSummary:
    outcome: Outcome = "ok"
    reason: str | None = None
    failed_step: str | None = None
    error: BaseException | None = None
    exit_code = int(DiagnoseExit.OK)
    for step in selected:
        if failed_step is not None:
            skipped = EngineResult.skipped(step.runner, f"not run: {failed_step} failed")
            run.results.append(skipped)
            run.records.append(StepRecord(name=step.name, status="skipped"))
            run.emit(step, "skipped", skipped)
            continue
        run.emit(step, "started", None)
        start = time.perf_counter()
        try:
            result, record = _run_step(run, step)
        except Exception as exc:
            outcome, reason = _failure(exc)
            failed_step = step.name
            error = StepFailed(step.name, exc)
            exit_code = exit_code_for(error)
            result = EngineResult(engine=step.runner, status="failed", notes=(reason,))
            record = StepRecord(name=step.name, status="failed")
            _log.error("step.failed", exc=exc, step=step.name, run_id=run.run_id)
        run.wall_ms[step.name] = (time.perf_counter() - start) * _MS_PER_S
        if result.status == "failed" and failed_step is None:
            outcome, failed_step = "failed", step.name
            reason = "; ".join(result.notes) or f"{step.name} reported failed"
            exit_code = int(DiagnoseExit.ERROR)
        run.results.append(result)
        run.records.append(record)
        event: EventKind = (
            "failed"
            if failed_step == step.name
            else ("skipped" if result.status == "skipped" else "finished")
        )
        run.emit(step, event, result)
        _log.debug("step.done", step=step.name, status=result.status, run_id=run.run_id)
    manifest_written = any(r.name == "manifest" and r.status == "ok" for r in run.records)
    if manifest_written:
        stored = contract_io.read("run_manifest", run.run_dir)
        outputs = _manifest_outputs(stored)
    else:
        outputs = _collect_outputs(run.run_dir, strict=False)
    return RunSummary(
        dataset=run.plan.dataset,
        case_id=run.case_id,
        run_id=run.run_id,
        run_dir=run.run_dir,
        outcome=outcome,
        reason=reason,
        failed_step=failed_step,
        results=tuple(run.results),
        outputs=outputs,
        wall_ms=MappingProxyType(dict(run.wall_ms)),
        steps=tuple(run.records),
        exit_code=exit_code,
        error=error,
    )


def _manifest_outputs(stored: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(stored, RunManifest):  # pragma: no cover - io returns the model
        raise ContractValidationError("run_manifest", "did not read as a RunManifest")
    return tuple((f.name, f.sha256) for f in stored.outputs)


def _read_manifest(run_dir: Path) -> RunManifest | None:
    if not (run_dir / CONTRACTS["run_manifest"].path).is_file():
        return None
    stored = contract_io.read("run_manifest", run_dir)
    return stored if isinstance(stored, RunManifest) else None


def _cached(run: _Run) -> RunSummary:
    stored = _read_manifest(run.run_dir)
    if stored is None:
        msg = f"finished run {run.run_dir} has no run_manifest.json"
        raise ContractValidationError("run_manifest", msg)
    return RunSummary(
        dataset=run.plan.dataset,
        case_id=run.case_id,
        run_id=run.run_id,
        run_dir=run.run_dir,
        outcome="ok",
        reason=None,
        failed_step=None,
        results=(),
        outputs=_manifest_outputs(stored),
        wall_ms=MappingProxyType({}),
        cached=True,
    )


def _prior_records(
    source: RunManifest | None, run_dir: Path, earlier: tuple[Step, ...], ai_mode: str
) -> list[StepRecord]:
    """run_manifest.steps entries for the reused sub-steps: copied from the source manifest when
    there is one, otherwise rebuilt from the files present (status ok, or skipped for Relentra
    with AI off)."""
    if source is not None:
        names = {s.name for s in earlier}
        return [
            StepRecord(name=s.name, status=s.status, outputs=tuple((f.name, f.sha256) for f in s.outputs))
            for s in source.steps
            if s.name in names
        ]
    records: list[StepRecord] = []
    for step in earlier:
        if step.name == "relentra" and ai_mode == "off":
            records.append(StepRecord(name=step.name, status="skipped"))
        else:
            records.append(
                StepRecord(
                    name=step.name, status="ok", outputs=tuple(sorted(_present(run_dir, step).items()))
                )
            )
    return records


def _check_prior(source: RunManifest, run_dir: Path, earlier: tuple[Step, ...]) -> None:
    """Every file the reused sub-steps wrote must hold the hash recorded by the last of them that
    wrote it (run_manifest.steps, not run_manifest.outputs).

    evidence.parquet is written by faultloom and rewritten by faultloom.claim_pass, so a finished
    run holds the claim-pass version. A run restarted from causentra may reuse it; one restarted
    from causatrix, relentra or faultloom.claim_pass would take it for FaultLoom's main output,
    so it is refused with InputChanged (critic gap "evidence.parquet has two versions but one
    path"). A run directory without run_manifest.json (a partial run) cannot be checked.
    """
    recorded = {s.name: {f.name: f.sha256 for f in s.outputs} for s in source.steps}
    want: dict[str, tuple[str, str]] = {}
    for step in earlier:
        for rel, digest in recorded.get(step.name, {}).items():
            want[rel] = (step.name, digest)
    for rel in sorted(want):
        producer, digest = want[rel]
        path = run_dir / rel
        if not path.is_file():
            raise ArtifactMissing(rel, path)
        got = sha256_file(path)
        if got != digest:
            err = InputChanged(rel, digest, got)
            err.add_note(
                f"{rel} no longer holds the output of {producer!r} (a later sub-step rewrote it or "
                f"it was edited); run from {producer!r} instead"
            )
            raise err


def _prepare(run: _Run) -> None:
    """Make the run directory ready for the selected sub-steps (under the lock)."""
    plan, run_dir = run.plan, run.run_dir
    start = index_of(plan.from_step)
    earlier, later = STEPS[:start], STEPS[start:]
    if start == index_of(FIRST_STEP):
        _clear(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        return
    if plan.reuse_dir is not None:
        source = _read_manifest(plan.reuse_dir)
        if source is not None:
            _check_prior(source, plan.reuse_dir, earlier)
        _clear(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        for step in earlier:
            for rel in _present(plan.reuse_dir, step):
                textio.write_bytes(run_dir / rel, textio.read_bytes(plan.reuse_dir / rel))
        run.prior = _prior_records(source, run_dir, earlier, plan.ai_mode)
        return
    if not run_dir.is_dir():
        msg = f"from_step {plan.from_step!r} needs reuse_dir or an existing run dir {run_dir}"
        raise UsageError(msg)
    source = _read_manifest(run_dir)
    if source is not None:
        _check_prior(source, run_dir, earlier)
    keep_exact, keep_prefixes = _layout(earlier)
    drop = [
        rel
        for rel in _walk(run_dir)
        if rel in EXCLUDED_OUTPUTS
        or (_is_known(rel, *_layout(later)) and not _is_known(rel, keep_exact, keep_prefixes))
    ]
    _remove(run_dir, drop)
    run.prior = _prior_records(source, run_dir, earlier, plan.ai_mode)


def execute(plan: RunPlan, *, progress: Callable[[StepEvent], None] | None = None) -> RunSummary:
    """Run `plan` and return its summary (see the module docstring for the run-dir rules).

    Raises UsageError, ConfigError (including missing plugins, exit 4) or LockHeld before any
    step runs; step failures are reported in the summary instead.
    """
    resolved = _resolve(plan)
    core = resolved.engine(CORE_ENGINE).core
    protocol = _get(core, "alert", "protocol")
    case_id = _case_id(plan)
    commit, dirty = _code(plan)
    config_bytes = resolved.lock_bytes()
    config_sha = sha256_bytes(config_bytes)
    rid = plan.run_id or make_run_id(case_id, config_sha, commit, plan.ai_mode)
    if plan.external_proposals is not None and plan.run_id is None:
        rid = derived_run_id(rid, plan.external_proposals)
    root = plan.runs_root
    if root is None and (plan.out_dir is None or (plan.ai_mode == "replay" and plan.cassette_dir is None)):
        root = runs_root(resolved)
    if plan.out_dir is not None:
        run_dir = plan.out_dir
    elif root is not None:
        run_dir = run_dir_for(root, plan.dataset, case_id, rid, plan.last_step if plan.partial else None)
    else:  # pragma: no cover - root is computed whenever out_dir is None
        msg = "no run directory: pass out_dir or runs_root"
        raise UsageError(msg)
    selected = select(plan.from_step, plan.last_step)
    checked = plugins.preflight(selected, ai_mode=plan.ai_mode, alert_protocol=str(protocol))
    run = _Run(
        plan=plan,
        resolved=resolved,
        case_id=case_id,
        run_id=rid,
        run_dir=run_dir.resolve(),
        commit=commit,
        dirty=dirty,
        config_bytes=config_bytes,
        config_sha256=config_sha,
        cassette_dir=_cassette_dir(plan, run_dir.resolve(), root, case_id, config_sha, commit),
        preflight=checked,
        progress=progress,
    )
    lock = PathLock(run.run_dir)
    try:
        lock.acquire()
    except OSError as exc:  # e.g. a file where a runs directory should be
        msg = f"cannot lock the run directory {run.run_dir}: {exc}"
        raise RunDirUnavailable(msg) from exc
    try:
        return _execute_locked(run, selected)
    finally:
        lock.release()


def _execute_locked(run: _Run, selected: tuple[Step, ...]) -> RunSummary:
    """execute() under the run-dir lock: reuse a finished run, or prepare the dir and run."""
    plan = run.plan
    if not plan.partial and index_of(plan.from_step) == 0 and is_finished(run.run_dir):
        if plan.ai_mode == "record" and not plan.force_record:
            msg = f"{run.run_dir} is an existing recording; pass force_record to overwrite it"
            raise UsageError(msg)
        if not run.dirty and plan.ai_mode != "record":
            _log.info("run.cached", run_id=run.run_id)
            return _cached(run)
        _log.info("run.rerun", run_id=run.run_id, dirty=run.dirty)
    try:
        _prepare(run)
    except VeyltraceError:
        raise
    except OSError as exc:  # a file in the way, or one Windows keeps open while clearing
        msg = f"cannot prepare the run directory {run.run_dir}: {exc}"
        raise RunDirUnavailable(msg) from exc
    return _run_all(run, selected)


def run_case(
    dataset: str,
    case: str,
    ai_mode: AIMode = "off",
    overrides: Mapping[str, Any] | None = None,
    *,
    progress: Callable[[StepEvent], None] | None = None,
    **plan: Any,
) -> RunSummary:
    """Diagnose one case: `execute(RunPlan(dataset, case, ai_mode, overrides, **plan))`."""
    return execute(
        RunPlan(dataset=dataset, case=case, ai_mode=ai_mode, overrides=overrides or {}, **plan),
        progress=progress,
    )


# --- Summary JSON ------------------------------------------------------------------------------
def summary_dict(summary: RunSummary) -> dict[str, Any]:
    """The canonical JSON form of a RunSummary (`diagnose --summary-json`, lead decision §2.8).

    Bench maps `outcome` to bench_result.run_outcome and reads per-step metrics and wall_ms. It is
    written outside the run directory and is not a contract artefact.
    """
    steps = [
        {
            "name": record.name,
            "engine": result.engine,
            "status": result.status,
            "notes": list(result.notes),
            "metrics": dict(result.metrics),
            "outputs": [{"name": n, "sha256": h} for n, h in record.outputs],
            "wall_ms": summary.wall_ms.get(record.name),
        }
        for record, result in zip(summary.steps, summary.results, strict=True)
    ]
    return {
        "schema": _SUMMARY_SCHEMA,
        "dataset": summary.dataset,
        "case_id": summary.case_id,
        "run_id": summary.run_id,
        "run_dir": summary.run_dir.as_posix(),
        "outcome": summary.outcome,
        "reason": summary.reason,
        "failed_step": summary.failed_step,
        "exit_code": summary.exit_code,
        "cached": summary.cached,
        "outputs": [{"name": n, "sha256": h} for n, h in summary.outputs],
        "steps": steps,
        "wall_ms_total": math.fsum(summary.wall_ms.values()),
    }


def write_summary(summary: RunSummary, path: Path) -> None:
    """Write summary_dict(summary) as canonical JSON plus a newline (atomic, UTF-8)."""
    textio.write_bytes(path, canonical_json(summary_dict(summary)) + b"\n")
