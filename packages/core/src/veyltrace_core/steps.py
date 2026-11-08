"""The fixed pipeline order: 14 uniquely named sub-steps with their 02 §4 stage numbers.

02 §4 numbers the pipeline 0–10, but some stages hold more than one unit of work: stage 4 runs
Causync then Causalith, FaultLoom runs twice (stage 5 main pass, stage 8 claim pass) and stage 10
is Causivra's card, core's manifest and Causivra's receipt. A sub-step name is therefore the unit
that `RunPlan.from_step`/`to_step`, partial run directories (`<run_id>~<last sub-step>/`) and
`run_manifest.steps[].name` refer to (M0 lead decision 2026-11-06; 03 §12). The order here is the
only engine-specific knowledge core has (packages/core/AGENTS.md); it never depends on entry-point
discovery order.

This module imports only the generated contract registry, so the context, the pipeline and test
helpers can all use it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, get_args

from veyltrace_contracts.registry import CONTRACTS

__all__ = [
    "CORE_ENGINE",
    "FIRST_STEP",
    "LAST_STEP",
    "PHASES",
    "STEPS",
    "STEP_NAMES",
    "Phase",
    "Step",
    "StepName",
    "index_of",
    "select",
    "step",
    "step_for",
]

#: Which half of a two-phase engine a call runs (FaultLoom: main | claim_pass; Causivra:
#: card | receipt). Both halves share one `run(ctx)` that branches on `ctx.phase` (M0 lead decision
#: 2026-11-06); every other engine always runs in phase "main".
Phase = Literal["main", "claim_pass", "card", "receipt"]
PHASES: tuple[str, ...] = get_args(Phase)

#: The 14 sub-step names in pipeline order; the same literal as run_manifest.steps[].name (03 §12).
StepName = Literal[
    "infralume",
    "alert",
    "signalyth",
    "anomara",
    "causync",
    "causalith",
    "faultloom",
    "causatrix",
    "relentra",
    "faultloom.claim_pass",
    "causentra",
    "causivra.card",
    "manifest",
    "causivra.receipt",
]
STEP_NAMES: tuple[StepName, ...] = get_args(StepName)
FIRST_STEP: StepName = STEP_NAMES[0]
LAST_STEP: StepName = STEP_NAMES[-1]

#: EngineResult.engine of the sub-steps core runs itself (alert, manifest).
CORE_ENGINE = "core"


@dataclass(frozen=True)
class Step:
    """One pipeline sub-step.

    `engine` is the `veyltrace.engines` entry-point name, or None for a step core runs itself.
    `outputs` are the contract names the step writes; `files` are the other run-dir files it may
    write, as POSIX paths relative to the run dir, where a trailing "/" means "every file under
    this directory" (the cassette). Together they are the only files a run directory may hold
    (run_manifest.outputs is built from known paths, never from a directory listing of unknowns).
    """

    index: int
    name: StepName
    stage: int
    engine: str | None
    phase: Phase
    outputs: tuple[str, ...]
    files: tuple[str, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        """Run-dir relative POSIX paths of the contract outputs, in `outputs` order."""
        return tuple(CONTRACTS[name].path for name in self.outputs)

    @property
    def runner(self) -> str:
        """The name reported as EngineResult.engine: the entry-point name, or "core"."""
        return self.engine if self.engine is not None else CORE_ENGINE


_TELEMETRY = ("telemetry.metrics", "telemetry.logs", "telemetry.spans", "telemetry.events")
_SIGNAL_CUBE = (
    "signal_cube.series",
    "signal_cube.edges",
    "signal_cube.templates",
    "signal_cube.critical_path",
)
_GRAPH = ("graph.nodes", "graph.edges", "graph.paths")
#: LLM cassette directory (02 §4.1). Relentra records into it; Causivra's narration may add entries.
_CASSETTE = "cassette/"

# (name, stage per 02 §4, engine entry point or None for core, phase, contract outputs, other files)
_TABLE: tuple[tuple[StepName, int, str | None, Phase, tuple[str, ...], tuple[str, ...]], ...] = (
    ("infralume", 0, "infralume", "main", ("case_manifest", *_TELEMETRY), ()),
    ("alert", 1, None, "main", ("alert",), ()),
    ("signalyth", 2, "signalyth", "main", _SIGNAL_CUBE, ()),
    ("anomara", 3, "anomara", "main", ("anomalies", "onsets"), ()),
    ("causync", 4, "causync", "main", ("alignment", "changes"), ()),
    ("causalith", 4, "causalith", "main", _GRAPH, ()),
    ("faultloom", 5, "faultloom", "main", ("evidence",), ()),
    ("causatrix", 6, "causatrix", "main", ("slate",), ()),
    ("relentra", 7, "relentra", "main", ("proposals", "agent_trace"), (_CASSETTE,)),
    ("faultloom.claim_pass", 8, "faultloom", "claim_pass", ("evidence",), ()),
    ("causentra", 9, "causentra", "main", ("verdict",), ()),
    ("causivra.card", 10, "causivra", "card", ("card",), ("card.md", _CASSETTE)),
    # run_manifest.json is written here too, but it never lists itself (03 §12).
    ("manifest", 10, None, "main", ("config_lock", "run_manifest"), ()),
    ("causivra.receipt", 10, "causivra", "receipt", ("receipt",), ("receipt.json.minisig",)),
)

STEPS: tuple[Step, ...] = tuple(
    Step(index=i, name=name, stage=stage, engine=engine, phase=phase, outputs=outputs, files=files)
    for i, (name, stage, engine, phase, outputs, files) in enumerate(_TABLE)
)

_BY_NAME: Mapping[str, Step] = MappingProxyType({s.name: s for s in STEPS})
_BY_ENGINE_PHASE: Mapping[tuple[str, str], Step] = MappingProxyType(
    {(s.engine, s.phase): s for s in STEPS if s.engine is not None}
)


def step(name: str) -> Step:
    """Return the sub-step called `name`; raises KeyError naming the valid names otherwise."""
    found = _BY_NAME.get(name)
    if found is None:
        msg = f"unknown pipeline step {name!r}; expected one of {', '.join(STEP_NAMES)}"
        raise KeyError(msg)
    return found


def index_of(name: str) -> int:
    """Return the position of sub-step `name` in STEPS."""
    return step(name).index


def step_for(engine: str, phase: str = "main") -> Step | None:
    """Return the sub-step an engine runs in `phase` (e.g. ("faultloom", "claim_pass")), or None.

    Test helpers use it to give a RunContext the step name the pipeline would give it.
    """
    return _BY_ENGINE_PHASE.get((engine, phase))


def select(from_step: str = FIRST_STEP, to_step: str = LAST_STEP) -> tuple[Step, ...]:
    """Return the sub-steps from `from_step` to `to_step`, both inclusive, in pipeline order.

    Raises KeyError for an unknown name and ValueError if `to_step` comes before `from_step`.
    """
    start, end = index_of(from_step), index_of(to_step)
    if end < start:
        msg = f"to_step {to_step!r} comes before from_step {from_step!r}"
        raise ValueError(msg)
    return STEPS[start : end + 1]
