"""Regenerate a producer's golden fixtures by running its pipeline sub-steps on upstream fixtures.

Why: consumers build against producers' goldens (02 §7 rule 3), so goldens must come from the
producer's real code, run on exactly the upstream fixtures a consumer will see. For each fixture
case (`synth-0N` and the `VARIANTS`) and each selected sub-step, this module:

1. assembles a run directory from the fixtures of every earlier sub-step
   (`fixture_run_dir(through=<previous sub-step>)`);
2. runs that one sub-step through the pipeline (`RunPlan(from_step=S, to_step=S, reuse_dir=…)`)
   with `code_commit="fixture"` and constant `FIXTURE_ENV`, so run_id, run_manifest and the
   receipt do not change with the machine, the Python patch level or the commit (M0 lead decision
   2026-11-06 §2.10: that pinning is the normalisation of run_manifest/receipt);
3. replaces the step's files in `packages/<producer>/fixtures/<case>/`, two-phase artefacts
   phase-qualified (`evidence.main.parquet` / `evidence.final.parquet`);
4. rewrites the consumer's `upstream.lock.json`, which the `fixtures-stale` job compares.

Run it through `scripts/check.py --package <name> --update-golden [--cascade]` (never in CI);
`python -m veyltrace_core.testing.update_golden --package P [--step S]… [--case C]…` directly.
A case whose plugins are not installed yet (ConfigError before any step runs, e.g. the detected
alert protocol before Anomara's detector) is reported as SKIP and left unchanged. So is a
consumer whose upstream fixture is missing because an earlier sub-step cannot run for that case
either (its producer was SKIPped for the same reason), so `--cascade` completes before O-04.
Generator variants (`synth-05@silent`) run like any case, under their own case id (R-03).
Any other failure exits 1.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from veyltrace_core import plugins
from veyltrace_core.config import resolve_config
from veyltrace_core.context import RunPlan
from veyltrace_core.errors import ArtifactMissing, ConfigError, VeyltraceError
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.pipeline import RunSummary, execute
from veyltrace_core.steps import STEPS, Step
from veyltrace_core.steps import step as step_named
from veyltrace_core.testing.fixtures import (
    FIXTURE_CODE_COMMIT,
    SYNTH_CASES,
    VARIANTS,
    fixture_dir,
    repo_root,
    split_case,
)
from veyltrace_core.testing.rundir import fixture_run_dir, step_fixture_files, write_upstream_lock

__all__ = ["FIXTURE_DATASET", "FIXTURE_ENV", "all_cases", "main", "steps_of", "update_case"]

#: Fixtures are synth cases (02 §7).
FIXTURE_DATASET: Final = "synth"
#: run_manifest.env and uv_lock_sha256 for fixture generation: constants, not this machine's, so
#: goldens are the same on every laptop and on CI (lead §2.10). Values are placeholders by design.
FIXTURE_ENV: Final[Mapping[str, Any]] = MappingProxyType(
    {"python": "3.12", "os": "fixture", "libs": {}, "uv_lock_sha256": "0" * 64}
)
EXIT_OK: Final = 0
EXIT_FAILED: Final = 1


def steps_of(package: str, names: Sequence[str] = ()) -> tuple[Step, ...]:
    """The sub-steps `package` runs (all of them, or the named ones), in pipeline order."""
    if names:
        chosen = [step_named(n) for n in names]
        wrong = [s.name for s in chosen if s.runner != package]
        if wrong:
            msg = f"steps {wrong} are not run by {package!r}"
            raise ValueError(msg)
        return tuple(sorted(chosen, key=lambda s: s.index))
    found = tuple(s for s in STEPS if s.runner == package)
    if not found:
        msg = f"package {package!r} runs no pipeline step"
        raise ValueError(msg)
    return found


def all_cases() -> tuple[str, ...]:
    """Every fixture directory name: the synth cases, then the variants (sorted)."""
    return (*SYNTH_CASES, *sorted(VARIANTS))


def _clear_step(step: Step, name: str) -> None:
    for producer, rel, _run_rel, _required in step_fixture_files(step, name):
        target = fixture_dir(producer, name) / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()


def _store(step: Step, name: str, run_dir: Path) -> list[str]:
    """Copy what `step` wrote in `run_dir` into the producers' fixture dirs; returns the labels."""
    written: list[str] = []
    for producer, rel, run_rel, _required in step_fixture_files(step, name):
        src = run_dir / PurePosixPath(run_rel)
        dst = fixture_dir(producer, name) / rel
        files = sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else [src]
        for path in files:
            if not path.is_file():
                continue
            target = dst / path.relative_to(src) if src.is_dir() else dst
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            written.append(f"{producer}/{target.relative_to(fixture_dir(producer, name)).as_posix()}")
    return written


def _run_step(step: Step, name: str, work: Path, config_dir: Path) -> RunSummary:
    base, _variant = split_case(name)
    variant = VARIANTS.get(name)
    # A generator variant is its own synth case: the adapter resolves the fixture name
    # ("synth-05@silent") as its canonical key, so its case id hashes that name (R-03).
    key = name if variant is not None and variant.generator is not None else base
    reuse = None
    if step.index > 0:
        reuse = fixture_run_dir(name, work / "upstream", through=STEPS[step.index - 1].name)
    plan = RunPlan(
        dataset=FIXTURE_DATASET,
        case=make_case_id(key),
        ai_mode=variant.ai_mode if variant is not None else "off",
        overrides=variant.overrides if variant is not None else {},
        from_step=step.name,
        to_step=step.name,
        reuse_dir=reuse,
        out_dir=work / "out",
        runs_root=work / "runs",
        config_dir=config_dir,
        code_commit=FIXTURE_CODE_COMMIT,
        env=FIXTURE_ENV,
    )
    return execute(plan)


def _upstream_blocked(step: Step, name: str, config_dir: Path) -> str | None:
    """Why an earlier sub-step cannot run for fixture case `name` (plugin gap), or None.

    Why: a producer SKIPped for a plugin gap leaves no fixture, so its consumers must SKIP for the
    same reason instead of failing on the missing upstream artefact.
    """
    if step.index == 0:
        return None
    variant = VARIANTS.get(name)
    ai_mode = variant.ai_mode if variant is not None else "off"
    overrides: Mapping[str, Any] = variant.overrides if variant is not None else {}
    resolved = resolve_config(overrides, config_dir=config_dir, dataset=FIXTURE_DATASET, ai_mode=ai_mode)
    protocol = resolved.engine("core").get_path("alert.protocol")
    try:
        plugins.preflight(STEPS[: step.index], ai_mode=ai_mode, alert_protocol=str(protocol))
    except ConfigError as exc:
        return str(exc)
    return None


def update_case(package: str, steps: Sequence[Step], name: str, *, config_dir: Path) -> str:
    """Regenerate `package`'s fixtures of `steps` for fixture case `name`; returns a status line.

    Raises VeyltraceError (other than a pre-step ConfigError, reported as SKIP) when a step fails.
    """
    written: list[str] = []
    for step in steps:
        with tempfile.TemporaryDirectory(prefix="vt-golden-") as tmp:
            try:
                summary = _run_step(step, name, Path(tmp), config_dir)
            except ConfigError as exc:  # raised before any step ran: a plugin is not installed
                return f"SKIP {package} {name} {step.name}: {exc}"
            except ArtifactMissing:
                blocked = _upstream_blocked(step, name, config_dir)
                if blocked is None:
                    raise
                return f"SKIP {package} {name} {step.name}: upstream cannot run yet ({blocked})"
            record = next((r for r in summary.steps if r.name == step.name), None)
            if summary.outcome != "ok" or record is None or record.status == "failed":
                reason = summary.reason or (record.status if record is not None else "not run")
                msg = f"{package} {name} {step.name}: outcome {summary.outcome} ({reason})"
                raise VeyltraceError(msg)
            _clear_step(step, name)
            written.extend(_store(step, name, summary.run_dir))
    write_upstream_lock(package, name)
    return f"OK {package} {name}: {len(written)} file(s)"


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m veyltrace_core.testing.update_golden")
    ap.add_argument("--package", required=True, help="producer package (core, infralume, ...)")
    ap.add_argument("--step", action="append", default=[], help="only this sub-step (repeatable)")
    ap.add_argument("--case", action="append", default=[], help="only this fixture case (repeatable)")
    ap.add_argument("--config-dir", type=Path, default=None, help="config/ to resolve (default: repo)")
    return ap.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry (see module doc); prints one status line per case."""
    args = _parse(sys.argv[1:] if argv is None else argv)
    package: str = args.package
    try:
        steps = steps_of(package, args.step)
    except (KeyError, ValueError) as exc:
        print(f"update-golden: {exc}", file=sys.stderr)
        return EXIT_FAILED
    cases: list[str] = list(args.case) or list(all_cases())
    config_dir: Path = args.config_dir if args.config_dir is not None else repo_root() / "config"
    failed = 0
    for name in cases:
        try:
            print(update_case(package, steps, name, config_dir=config_dir), flush=True)
        except (VeyltraceError, KeyError, ValueError) as exc:
            failed += 1
            print(f"FAIL {package} {name}: {exc}", flush=True)
            for note in getattr(exc, "__notes__", ()):
                print(f"  {note}", flush=True)
    return EXIT_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
