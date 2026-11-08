"""The run context an engine receives, the result it returns, and the plan the pipeline executes.

`RunContext` is the only handle an engine gets on a run: its ids, its run directory, its own
config section and contract-typed `read`/`write`. Reads of `case_manifest` hide the alert hint from
every step except Infralume (which writes it) and core's alert step (which turns it into
`alert.json`), so the injection time never reaches analysis code (02 §5.1; M0 lead decision
2026-11-06, D-15). `EngineResult` is what an engine reports back: status, output hashes, counters
and, for engines that call an LLM, the `AIManifest` core merges into `run_manifest.ai` (02 §6.10).
`RunPlan` is the immutable description of one pipeline execution (core_api_spec §10).

Engine-facing module: it imports io, steps and ids at import time, never importlib.metadata.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

import pyarrow as pa
from pydantic import BaseModel

from veyltrace_core import io as contract_io
from veyltrace_core.errors import ConfigError, ContractValidationError, UsageError
from veyltrace_core.hashing import is_sha256
from veyltrace_core.hint import HINT_CONTRACT, HINT_READERS, redact_hint
from veyltrace_core.ids import AI_MODES, AIMode, is_case_id, is_run_id
from veyltrace_core.steps import FIRST_STEP, LAST_STEP, PHASES, STEP_NAMES, Phase, index_of

if TYPE_CHECKING:
    from veyltrace_core.config import EngineConfig, ResolvedConfig

__all__ = [
    "DATASET_PATTERN",
    "ENGINE_STATUSES",
    "EXTERNAL_PROPOSALS_MODE",
    "HINT_READERS",
    "AIManifest",
    "AIMode",
    "EngineResult",
    "EngineStatus",
    "Phase",
    "RunContext",
    "RunPlan",
    "redact_hint",
]

#: EngineResult.status vocabulary (03 §12 run_manifest.steps[].status).
EngineStatus = Literal["ok", "degraded", "skipped", "failed"]
ENGINE_STATUSES: tuple[str, ...] = get_args(EngineStatus)

#: proposals.mode of hypotheses submitted from outside Relentra (MCP verify_hypothesis).
EXTERNAL_PROPOSALS_MODE = "external"

#: 03 §1 `dataset` pattern; it also keeps a dataset name from escaping the runs root.
DATASET_PATTERN = r"[a-z0-9]+(-[a-z0-9]+)*"


def _require_sha256(value: object, what: str) -> None:
    if not is_sha256(value):
        msg = f"{what} must be a lowercase 64-hex sha256, got {value!r}"
        raise ValueError(msg)


def _sorted_pairs(pairs: Iterable[tuple[str, str]], what: str) -> tuple[tuple[str, str], ...]:
    """Validate (name, sha256) pairs and return them sorted by name; duplicate names are an error."""
    out = tuple(sorted((str(name), str(digest)) for name, digest in pairs))
    names = [name for name, _ in out]
    if len(set(names)) != len(names):
        msg = f"{what} names must be unique, got {names}"
        raise ValueError(msg)
    for name, digest in out:
        if not name:
            msg = f"{what} names must be non-empty"
            raise ValueError(msg)
        _require_sha256(digest, f"{what} {name!r}")
    return out


@dataclass(frozen=True)
class AIManifest:
    """What one LLM-calling engine (Relentra, Causivra) reports for run_manifest.ai (02 §6.10).

    `prompts` are (prompt file name, sha256_text_lf) pairs and `schemas` are (schema purpose,
    sha256_json(schema)) pairs; both are stored sorted by name so the merge in the manifest step
    does not depend on report order.
    """

    provider: str | None
    model: str | None
    gguf_sha256: str | None
    prompts: tuple[tuple[str, str], ...] = ()
    schemas: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.gguf_sha256 is not None:
            _require_sha256(self.gguf_sha256, "gguf_sha256")
        object.__setattr__(self, "prompts", _sorted_pairs(self.prompts, "prompt"))
        object.__setattr__(self, "schemas", _sorted_pairs(self.schemas, "schema"))


@dataclass(frozen=True)
class EngineResult:
    """The outcome of one engine call (core_api_spec §7).

    `failed` stops the run and later steps are marked `skipped`; `degraded` lets it continue
    (e.g. a Relentra provider error); `skipped` is reported by the runner (Relentra with AI off).
    `outputs` are (contract or run-dir file name, file sha256) pairs, stored sorted by name; the
    pipeline checks each against the file it names. `metrics` are counters for bench only and
    never enter an artefact. Construction normalises order, so equal results compare equal.
    """

    engine: str
    status: EngineStatus
    outputs: tuple[tuple[str, str], ...] = ()
    metrics: Mapping[str, int | float] = field(default_factory=lambda: MappingProxyType({}))
    notes: tuple[str, ...] = ()
    ai_manifest: AIManifest | None = None

    def __post_init__(self) -> None:
        if not self.engine:
            msg = "EngineResult.engine must be a non-empty entry-point name"
            raise ValueError(msg)
        if self.status not in ENGINE_STATUSES:
            msg = f"EngineResult.status must be one of {ENGINE_STATUSES}, got {self.status!r}"
            raise ValueError(msg)
        object.__setattr__(self, "outputs", _sorted_pairs(self.outputs, "output"))
        metrics: dict[str, int | float] = {}
        for key in sorted(self.metrics):
            value = cast("object", self.metrics[key])  # engines may be untyped: check at runtime
            if isinstance(value, bool) or not isinstance(value, int | float):
                msg = f"metric {key!r} must be an int or float counter, got {value!r}"
                raise TypeError(msg)
            if isinstance(value, float) and not math.isfinite(value):
                msg = f"metric {key!r} must be finite, got {value!r}"
                raise ValueError(msg)
            metrics[key] = value
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))

    @classmethod
    def skipped(cls, engine: str, note: str) -> EngineResult:
        """A runner-written `skipped` result with one explanatory note."""
        return cls(engine=engine, status="skipped", notes=(note,))


@dataclass(frozen=True)
class RunContext:
    """Everything an engine may know about the run it is part of (core_api_spec §7).

    `engine` is the entry-point name (or "core" for core's own steps), `step` the sub-step name
    from `steps.STEPS` and `phase` which half of a two-phase engine runs (FaultLoom main |
    claim_pass, Causivra card | receipt; D-5). `config` is the engine's own section with `.core`,
    `.section()` and calibration. `resolved` is the whole run config; it backs `with_config` and
    the alert step's detector config, and is None only in hand-built test contexts.
    `cassette_dir` is where LLM calls are recorded (record) or read (replay); None with AI off.
    `unredacted_hint` is the capability to see case_manifest.t_alert_hint_ns: the pipeline sets it
    only for the infralume and alert steps. It is a separate field, not derived from `step`, so an
    engine cannot gain it with `dataclasses.replace(ctx, step="infralume")`; its name is on the
    isolation literal scan's ban list outside core (D-15).
    """

    case_id: str
    run_id: str
    dataset: str
    run_dir: Path
    ai_mode: AIMode
    engine: str
    config: EngineConfig
    phase: Phase = "main"
    step: str = ""
    cassette_dir: Path | None = None
    force_record: bool = False
    resolved: ResolvedConfig | None = None
    unredacted_hint: bool = False

    def __post_init__(self) -> None:
        if not is_case_id(self.case_id):
            msg = f"case_id must be 12 hex, got {self.case_id!r}"
            raise ValueError(msg)
        if not is_run_id(self.run_id):
            msg = f"run_id must be 16 hex (optionally -x<12 hex>), got {self.run_id!r}"
            raise ValueError(msg)
        if self.ai_mode not in AI_MODES:
            msg = f"ai_mode must be one of {AI_MODES}, got {self.ai_mode!r}"
            raise ValueError(msg)
        if self.phase not in PHASES:
            msg = f"phase must be one of {PHASES}, got {self.phase!r}"
            raise ValueError(msg)
        if self.step and self.step not in STEP_NAMES:
            msg = f"step must be one of {STEP_NAMES} or empty, got {self.step!r}"
            raise ValueError(msg)
        object.__setattr__(self, "run_dir", Path(self.run_dir))

    @property
    def sees_hint(self) -> bool:
        """True only for the pipeline-granted infralume and alert steps (D-15)."""
        return self.unredacted_hint and self.step in HINT_READERS

    def path(self, name: str) -> Path:
        """Absolute path of contract `name` in this run directory."""
        return contract_io.path_of(name, self.run_dir)

    def read(
        self, name: str, *, columns: Sequence[str] | None = None, validate: bool = False
    ) -> BaseModel | pa.Table | list[BaseModel]:
        """Read contract `name` from the run directory (io.read).

        case_manifest comes back with the alert hint redacted unless this is the infralume or
        alert step (D-15, defence in depth behind the AST literal scan).
        """
        if name == HINT_CONTRACT and self.sees_hint:
            return contract_io.read_unredacted(name, self.run_dir, columns=columns, validate=validate)
        return contract_io.read(name, self.run_dir, columns=columns, validate=validate)

    def read_model[M: BaseModel](self, name: str, model: type[M], *, validate: bool = False) -> M:
        """`read` for a JSON contract, typed for pyright strict: `ctx.read_model("slate", Slate)`."""
        value = self.read(name, validate=validate)
        if not isinstance(value, model):
            msg = f"is read as {type(value).__name__}, not {model.__name__}"
            raise ContractValidationError(name, msg)
        return value

    def read_table(
        self, name: str, *, columns: Sequence[str] | None = None, validate: bool = False
    ) -> pa.Table:
        """`read` for a Parquet or CSV contract, typed as pa.Table."""
        value = self.read(name, columns=columns, validate=validate)
        if not isinstance(value, pa.Table):
            raise ContractValidationError(name, f"is read as {type(value).__name__}, not a table")
        return value

    def write(self, name: str, data: Any) -> str:
        """Validate, sort and write contract `name` into the run directory; returns its sha256."""
        return contract_io.write(name, data, self.run_dir)

    def write_text(self, relpath: str, text: str) -> str:
        """Write a non-contract text artefact (card.md) as UTF-8 with LF; returns its sha256."""
        return contract_io.write_text(relpath, text, self.run_dir)

    def exists(self, name: str) -> bool:
        """True if contract `name` is present in the run directory (optional inputs)."""
        return contract_io.exists(name, self.run_dir)

    def with_config(self, engine: str) -> RunContext:
        """The same context with another engine's config section (Relentra calling FaultLoom's
        evidence_cards). The step, phase and hint redaction stay those of the calling step."""
        if self.resolved is None:
            msg = f"with_config({engine!r}) needs the run's ResolvedConfig; this context has none"
            raise ConfigError(msg)
        return replace(self, config=self.resolved.engine(engine))


@dataclass(frozen=True)
class RunPlan:
    """One pipeline execution (core_api_spec §10, with the M0 lead decisions).

    `case` is a 12-hex case id or an adapter-resolvable name (synth-0N). `from_step`/`to_step` are
    sub-step names (both inclusive); a plan that stops before causivra.receipt (or with
    write_manifest/write_receipt off) is partial and writes to `<run_id>~<last sub-step>/`.
    `config` is a ready ResolvedConfig (replay: ResolvedConfig.from_lock), `run_id` a fixed id
    (replay: the receipt's, D-4), `out_dir` an explicit run directory. `reuse_dir` supplies the
    outputs of the steps before `from_step` (copied and hash-checked). `external_proposals` makes a
    derived MCP run whose proposals are written at the relentra step. The pinning fields
    `runs_root`, `config_dir`, `code_commit` and `env` let fixtures and tests fix the environment
    (M0 lead decision 2026-11-06: fixtures pin code_commit="fixture" and constant env values).
    """

    dataset: str
    case: str
    ai_mode: AIMode = "off"
    overrides: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    config: ResolvedConfig | None = None
    run_id: str | None = None
    out_dir: Path | None = None
    from_step: str = FIRST_STEP
    to_step: str = LAST_STEP
    reuse_dir: Path | None = None
    cassette_dir: Path | None = None
    external_proposals: Mapping[str, Any] | None = None
    write_manifest: bool = True
    write_receipt: bool = True
    force_record: bool = False
    runs_root: Path | None = None
    config_dir: Path | None = None
    code_commit: str | None = None
    env: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(DATASET_PATTERN, self.dataset) is None:
            msg = f"dataset must match ^{DATASET_PATTERN}$, got {self.dataset!r}"
            raise UsageError(msg)
        if not self.case:
            msg = "case must be a case id or an adapter-resolvable case name"
            raise UsageError(msg)
        if self.ai_mode not in AI_MODES:
            msg = f"ai_mode must be one of {AI_MODES}, got {self.ai_mode!r}"
            raise UsageError(msg)
        for what, name in (("from_step", self.from_step), ("to_step", self.to_step)):
            if name not in STEP_NAMES:
                msg = f"{what} must be one of {', '.join(STEP_NAMES)}, got {name!r}"
                raise UsageError(msg)
        if index_of(self.to_step) < index_of(self.from_step):
            msg = f"to_step {self.to_step!r} comes before from_step {self.from_step!r}"
            raise UsageError(msg)
        if self.run_id is not None and not is_run_id(self.run_id):
            msg = f"run_id must be 16 hex (optionally -x<12 hex>), got {self.run_id!r}"
            raise UsageError(msg)
        if self.force_record and self.ai_mode != "record":
            msg = "force_record only applies with ai_mode='record'"
            raise UsageError(msg)
        proposals = self.external_proposals
        # mode "external" marks hypotheses Relentra never produced (proposals schema, 02 §4.1): a
        # derived run must not claim brief/investigate, nor a model it did not call.
        if proposals is not None and (
            proposals.get("mode") != EXTERNAL_PROPOSALS_MODE or proposals.get("model") is not None
        ):
            msg = (
                f"external_proposals must have mode {EXTERNAL_PROPOSALS_MODE!r} and model null, "
                f"got mode={proposals.get('mode')!r}"
            )
            raise UsageError(msg)
        object.__setattr__(self, "overrides", MappingProxyType(dict(self.overrides)))

    @property
    def last_step(self) -> str:
        """The last sub-step this plan runs, after write_manifest/write_receipt are applied."""
        last = index_of(self.to_step)
        if not self.write_receipt:
            last = min(last, index_of("manifest"))
        if not self.write_manifest:
            last = min(last, index_of("causivra.card"))
        return STEP_NAMES[max(last, index_of(self.from_step))]

    @property
    def partial(self) -> bool:
        """True when the plan stops before causivra.receipt, so the run never finishes."""
        return self.last_step != LAST_STEP
