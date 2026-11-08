"""Assemble run directories from producer fixtures, and track which upstream fixtures a golden used.

Why: consumers test their engine on the producers' current fixtures, so a test needs a run directory
holding exactly the artefacts the pipeline would have written before its step
(`fixture_run_dir`). Each consumer fixture directory also records the canonical-content hashes of
the upstream fixtures it was generated from (`upstream.lock.json`); when an upstream fixture
changes, the consumer's golden is reported STALE by the non-required `fixtures-stale` job instead
of turning main red across lanes (critic gap "fixture cascade"; M0 lead decision 2026-11-06 §2.10).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.hashing import sha256_text_lf
from veyltrace_core.steps import STEPS, Step, index_of
from veyltrace_core.testing.compare import content_sha256
from veyltrace_core.testing.fixtures import (
    PRODUCER,
    TWO_PHASE,
    VARIANTS,
    fixture_case,
    fixture_dir,
    fixture_relpath,
    missing_fixture,
)

__all__ = [
    "DEFAULT_THROUGH",
    "UPSTREAM_LOCK",
    "UpstreamLock",
    "compute_upstream_lock",
    "fixture_run_dir",
    "read_upstream_lock",
    "stale_upstream",
    "step_fixture_files",
    "synth_run_dir",
    "upstream_fixtures",
    "write_upstream_lock",
]

#: Default last sub-step of fixture_run_dir: everything a finished run holds before the manifest.
DEFAULT_THROUGH: Final = "causivra.card"
UPSTREAM_LOCK: Final = "upstream.lock.json"
#: Steps whose outputs exist only with AI on; the runner skips them when AI is off (02 §4).
_AI_ONLY_STEPS: Final = frozenset({"relentra"})
#: Optional extra files of a step (only copied when the producer ships them).
_OPTIONAL_FILES: Final = frozenset({"cassette/", "receipt.json.minisig"})
_RUN_DIR_PREFIX: Final = "run-"


def _ai_mode(case_dir_name: str) -> str:
    variant = VARIANTS.get(case_dir_name)
    return variant.ai_mode if variant is not None else "off"


def step_fixture_files(step: Step, case_dir_name: str) -> list[tuple[str, str, str, bool]]:
    """(producer, fixture relpath, run-dir relpath, required) for every file `step` writes."""
    skip_ai = step.name in _AI_ONLY_STEPS and _ai_mode(case_dir_name) == "off"
    files: list[tuple[str, str, str, bool]] = []
    for contract in step.outputs:
        phase = TWO_PHASE[contract][step.name] if contract in TWO_PHASE else None
        files.append(
            (PRODUCER[contract], fixture_relpath(contract, phase), CONTRACTS[contract].path, not skip_ai)
        )
    producer = step.engine if step.engine is not None else "core"
    for rel in step.files:
        required = rel not in _OPTIONAL_FILES and not skip_ai
        files.append((producer, rel, rel, required))
    return files


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        for child in sorted(src.rglob("*")):
            if child.is_file():
                target = dst / child.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(child, target)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def fixture_run_dir(
    case: str,
    tmp_path: Path,
    *,
    through: str = DEFAULT_THROUGH,
    include: Iterable[str] = (),
    variant: str | None = None,
) -> Path:
    """A run directory under `tmp_path` holding every fixture output of the steps up to `through`.

    Steps run in pipeline order, so `evidence.parquet` is the main-pass fixture until `through`
    reaches faultloom.claim_pass, and the final one after it. Relentra's outputs are left out for
    variants with AI off (the runner skips Relentra). `include` adds contracts from later steps
    (two-phase contracts in their final version). A missing required fixture raises ArtifactMissing
    naming the producer's --update-golden command.
    """
    name = fixture_case(case, variant)
    run_dir = tmp_path / f"{_RUN_DIR_PREFIX}{name}"
    run_dir.mkdir(parents=True, exist_ok=False)
    last = index_of(through)
    for step in STEPS[: last + 1]:
        for producer, rel, run_rel, required in step_fixture_files(step, name):
            src = fixture_dir(producer, name) / rel
            if not src.exists():
                if required:
                    raise missing_fixture(rel, src, producer)
                continue
            _copy(src, run_dir / PurePosixPath(run_rel))
    for contract in include:
        phase = "final" if contract in TWO_PHASE else None
        src = fixture_dir(PRODUCER[contract], name) / fixture_relpath(contract, phase)
        if not src.is_file():
            raise missing_fixture(contract, src, PRODUCER[contract])
        _copy(src, run_dir / PurePosixPath(CONTRACTS[contract].path))
    return run_dir


def synth_run_dir(case: str, tmp_path: Path, *, variant: str | None = None) -> Path:
    """A run directory with case_manifest, telemetry.* and alert for `case` (through the alert step)."""
    return fixture_run_dir(case, tmp_path, through="alert", variant=variant)


# --- upstream.lock.json -----------------------------------------------------------------------
@dataclass(frozen=True)
class UpstreamLock:
    """Canonical-content hashes of the upstream fixtures a consumer's golden was built from.

    `entries` are ("<producer>/<fixture relpath>", sha256) pairs, sorted by name.
    """

    consumer: str
    case: str
    entries: tuple[tuple[str, str], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "case": self.case,
            "upstream": [{"name": n, "content_sha256": h} for n, h in self.entries],
        }


def _consumer_last_step(package: str) -> int:
    indexes = [s.index for s in STEPS if s.runner == package]
    if not indexes:
        msg = f"package {package!r} runs no pipeline step"
        raise KeyError(msg)
    return max(indexes)


def _file_hash(rel: str, path: Path) -> str:
    """Content hash of one fixture file: canonical content for contracts, LF text otherwise."""
    for contract in sorted(CONTRACTS):
        if contract not in PRODUCER:
            continue
        phases: tuple[str | None, ...] = ("main", "final") if contract in TWO_PHASE else (None,)
        if any(fixture_relpath(contract, phase) == rel for phase in phases):
            return content_sha256(contract, path)
    return sha256_text_lf(path)


def upstream_fixtures(package: str, case: str, *, variant: str | None = None) -> tuple[tuple[str, Path], ...]:
    """Every existing upstream fixture file of `package` for `case`: all files written by other
    producers' steps before the package's last pipeline step, as ("<producer>/<relpath>", path)."""
    name = fixture_case(case, variant)
    last = _consumer_last_step(package)
    found: dict[str, Path] = {}
    for step in STEPS[:last]:
        for producer, rel, _run_rel, _required in step_fixture_files(step, name):
            if producer == package:
                continue
            src = fixture_dir(producer, name) / rel
            if src.is_file():
                found[f"{producer}/{rel}"] = src
            elif src.is_dir():
                for child in sorted(src.rglob("*")):
                    if child.is_file():
                        found[f"{producer}/{rel}{child.relative_to(src).as_posix()}"] = child
    return tuple(sorted(found.items()))


def compute_upstream_lock(package: str, case: str, *, variant: str | None = None) -> UpstreamLock:
    """The lock `package`'s fixtures for `case` would record now."""
    name = fixture_case(case, variant)
    entries: list[tuple[str, str]] = []
    for label, path in upstream_fixtures(package, case, variant=variant):
        rel = label.split("/", 1)[1]
        entries.append((label, _file_hash(rel, path)))
    return UpstreamLock(consumer=package, case=name, entries=tuple(entries))


def write_upstream_lock(package: str, case: str, *, variant: str | None = None) -> Path:
    """Write `<fixture dir>/upstream.lock.json` (canonical JSON + LF); run by --update-golden."""
    lock = compute_upstream_lock(package, case, variant=variant)
    path = fixture_dir(package, case, variant=variant) / UPSTREAM_LOCK
    textio.write_bytes(path, canonical_json(lock.to_json()) + b"\n")
    return path


def read_upstream_lock(path: Path) -> UpstreamLock:
    """Parse an upstream.lock.json file; raises ValueError if it is malformed."""
    raw: object = json.loads(textio.read_text(path))
    if not isinstance(raw, Mapping):
        msg = f"{path}: upstream lock must be a JSON object"
        raise ValueError(msg)
    obj = cast("Mapping[str, Any]", raw)
    try:
        entries = tuple(sorted((str(e["name"]), str(e["content_sha256"])) for e in obj["upstream"]))
        return UpstreamLock(consumer=str(obj["consumer"]), case=str(obj["case"]), entries=entries)
    except (KeyError, TypeError) as exc:
        msg = f"{path}: malformed upstream lock ({exc})"
        raise ValueError(msg) from exc


def stale_upstream(package: str, case: str, *, variant: str | None = None) -> tuple[str, ...]:
    """Why `package`'s golden for `case` is stale: one line per changed, added or removed upstream
    fixture, or a missing lock. Empty means the golden was built from the current upstream."""
    path = fixture_dir(package, case, variant=variant) / UPSTREAM_LOCK
    if not path.is_file():
        return (f"{package}/{fixture_case(case, variant)}: no {UPSTREAM_LOCK}",)
    recorded = dict(read_upstream_lock(path).entries)
    current = dict(compute_upstream_lock(package, case, variant=variant).entries)
    reasons: list[str] = []
    for label in sorted(recorded.keys() | current.keys()):
        if label not in current:
            reasons.append(f"removed upstream fixture {label}")
        elif label not in recorded:
            reasons.append(f"new upstream fixture {label}")
        elif recorded[label] != current[label]:
            reasons.append(f"changed upstream fixture {label}")
    return tuple(reasons)
