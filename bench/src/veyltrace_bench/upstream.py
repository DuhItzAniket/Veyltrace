"""Upstream reuse for slate-scored methods (R-16 B5, #413; 04 §12 deviation of 2026-11-21; ADR
20261121-ak-slate-method-upstream-reuse).

A `causatrix:<ranker>` method changes only `causatrix.*` keys, and no step before Causatrix reads
that section, so its run of a case equals the experiment's `veyltrace:off` run of the same case up
to and including Causalith. Bench therefore restarts it at `faultloom` on that run's outputs (core
`from_step` + `reuse_dir`) and stops after Causatrix (`to_step`), which is all a slate-scored
method is scored on (04 §3, §9). It cannot restart later: FaultLoom's claim pass rewrites
`evidence.parquet` in every finished run (T8 intervention atoms, #368, AI off too), and core
refuses that version as FaultLoom's main output. It reuses only when the source run finished `ok`
and nothing it would reuse differs: the `config.lock.json` sections of every reused step's engine equal the
method's resolved ones, the code commit is the same, and every file the reused steps wrote still
holds the hash its `run_manifest` recorded (core re-checks the hashes itself). Otherwise the method
runs in full, as before, and the reason is logged.

A reused row's `wall_ms` and `peak_rss_mb` cover the FaultLoom and Causatrix steps only
(bench/README.md), and its timeout is what is left of `timeout_s` after the source's run. RQ5
cost numbers come only from `veyltrace:off` runs. `causatrix:rrf` has no override, so it shares `veyltrace:off`'s whole run as before (#172).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

from veyltrace_bench.experiment import Experiment, MethodSpec
from veyltrace_contracts.models import RunManifest
from veyltrace_core import io, textio
from veyltrace_core.errors import ArtifactMissing, ContractValidationError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.pipeline import code_commit, is_finished
from veyltrace_core.steps import STEP_NAMES

PREFIX: Final = "causatrix."  # the only keys a reusing method may override
START: Final = "faultloom"  # restart here on the source run ...
STOP: Final = "causatrix"  # ... and stop after Causatrix
#: The sub-steps a reusing method takes from its source: everything before FaultLoom.
REUSED: Final = STEP_NAMES[: STEP_NAMES.index(START)]
#: Their engines' config.lock sections (the alert step is core's), which must equal the method's.
SECTIONS: Final = ("core", "infralume", "signalyth", "anomara", "causync", "causalith")
LOCK: Final = "config.lock.json"
KIND, SOURCE_KIND = "causatrix", "veyltrace"


def applies(method: MethodSpec) -> bool:
    """A slate-scored method with only causatrix.* overrides (causatrix:<ranker>), AI off."""
    keys = list(method.overrides)
    return (
        method.kind == KIND
        and method.ai.mode == "off"
        and bool(keys)
        and all(k.startswith(PREFIX) for k in keys)
    )


def source_of(exp: Experiment, method: MethodSpec) -> MethodSpec | None:
    """The veyltrace method, AI off and without non-causatrix overrides, whose runs `method` reuses."""
    for m in exp.methods:
        if m.kind == SOURCE_KIND and m.ai.mode == "off" and all(k.startswith(PREFIX) for k in m.overrides):
            return m
    return None


def _sections(lock: Mapping[str, Any]) -> dict[str, object]:
    sections = cast("Mapping[str, object]", lock.get("sections", {}))
    return {s: sections.get(s) for s in SECTIONS}


def mismatch(source_dir: Path, method_lock: bytes) -> str | None:
    """Why `source_dir` cannot serve a method whose resolved config.lock is `method_lock`; None when
    it can (finished, same upstream sections and commit, every reused output intact)."""
    if not is_finished(source_dir):
        return "the source run did not finish"
    try:
        manifest = io.read_model("run_manifest", source_dir, RunManifest)
        source_lock = cast("Mapping[str, Any]", json.loads(textio.read_text(source_dir / LOCK)))
    except (ArtifactMissing, ContractValidationError, OSError, ValueError) as exc:
        return f"the source run's manifest or lock is unreadable ({type(exc).__name__})"
    mine = cast("Mapping[str, Any]", json.loads(method_lock.decode()))
    differ = [s for s, v in _sections(source_lock).items() if _sections(mine)[s] != v]
    if differ:
        return f"config sections {differ} differ"
    if manifest.code.commit != code_commit()[0]:
        return "the code commit differs"
    for step in manifest.steps:
        if step.name not in REUSED:
            continue
        for f in step.outputs:
            path = source_dir / f.name
            if not path.is_file() or sha256_file(path) != f.sha256:
                return f"{f.name} no longer holds {step.name}'s output"
    return None
