"""The experiment YAML of `veyltrace bench run` (04 §9; R-04, #66; the command itself is #14).

One file fixes one experiment: dataset parts and case selection, split, alert protocol and
perturbations, methods, calibration, metrics, statistics and resources. It is parsed like config/
(YAML 1.2, duplicate keys rejected) and validated strictly: an unknown key is an error, and every
default cites its source in 04 or the config file it feeds. `unsupported` lists what the v0 runner
(#67) cannot run yet, so it can refuse an experiment that needs it before the first case, naming
each one (and its task or reason, if known). `select_cases` resolves the case lists, `code_state` the
code it runs from.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from veyltrace_bench.summary import METRIC_KEYS
from veyltrace_contracts.models import AiMode, Source
from veyltrace_core import textio, yaml12
from veyltrace_core.adapters import adapter_for
from veyltrace_core.config import data_root
from veyltrace_core.errors import ArtifactMissing, ConfigError
from veyltrace_core.ids import is_case_id
from veyltrace_core.pipeline import code_commit

#: Config keys the protocol block sets (04 §9: "each value maps to a pipeline hook"; §5.1, §5.2).
PROTOCOL_KEYS = ("core.alert.protocol", "core.alert.shift_s", "infralume.sources.drop")
MetricName = Literal[  # the 04 §9 `metrics` vocabulary
    "ac_at_k", "avg_at_5", "mrr", "fine_ac_at_k", "retrieval_at_k", "rerank_at_1", "chance", "lift",
    "onset_error", "coverage", "set_size", "risk_coverage", "no_fault_rates", "cost",
]  # fmt: skip
#: The 04 §9 metrics v0 does not compute (summary.METRIC_KEYS has the rest), with the adding task.
METRIC_TASKS = {
    "coverage": "R-13 held-out folds",
    "set_size": "R-12 conformal sets",
    "risk_coverage": "R-12 statuses",
    "no_fault_rates": "R-13 normal windows",
    "cost": "per-stage wall time and peak RSS need a subprocess runner",
}


class _Strict(BaseModel):
    """Only the 04 §9 fields: an unknown key is an error, and a loaded experiment is frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetSpec(_Strict):
    parts: tuple[str, ...] = Field(min_length=1)  # case_manifest.dataset ids
    cases: str = "all"  # all, or a YAML list of 12-hex case ids (path relative to the repo root)
    exclude: str | None = None  # a case-id list shared by all parts, e.g. bench/dev_cases.yaml
    normal_windows: Literal["none", "rcaeval_pre_injection", "veyllab"] = "none"  # 04 §5.4


class SplitSpec(_Strict):
    family: str | None = None
    scheme: Literal["crossfit2", "loso", "none"] = "none"  # none: bench_result.fold stays null
    cluster: tuple[str, ...] = ("system", "service", "fault")  # 04 §5.4 item 1
    stratify: tuple[str, ...] = ("system", "fault")  # 04 §5.4 item 2
    seed: int = 20261108  # 04 §5.4 item 2


class ProtocolSpec(_Strict):
    alert: Literal["oracle", "detected"] = "oracle"  # 04 §5.1: oracle unless stated
    shift_s: int = 0  # core.alert.shift_s default (config/core.yaml)
    sources_drop: tuple[Source, ...] = ()  # infralume.sources.drop default (config/infralume.yaml)
    decoys: dict[str, object] | None = None  # {pi, rate_per_h, window_s} (04 §5.2)
    anonymize_services: bool = False
    inject_proposals: dict[str, object] | None = None
    permute_proposals: dict[str, int] | None = None  # {n, seed}


class AISpec(_Strict):
    mode: AiMode = "off"
    relentra_mode: Literal["brief", "investigate"] | None = None
    model: str | None = None
    seeds: tuple[int, ...] = ()  # empty: a deterministic method (bench_result.seed null)


class MethodSpec(_Strict):
    id: str = Field(min_length=1)
    # causatrix: the pipeline scored on its slate, not the verdict (04 §3 `causatrix:<ranker>`, `:rrf`)
    kind: Literal["veyltrace", "causatrix", "rcaeval", "internal_baseline", "agent_only"]
    ai: AISpec = AISpec()
    overrides: dict[str, object] = Field(default_factory=dict)  # dotted config keys
    rcaeval: dict[str, object] | None = None  # {method, length}


class CalibrationSpec(_Strict):
    fit: bool = False
    alpha: float = 0.10  # 09 §3.7; 04 §5.4 item 5
    no_fault_beta: float = 0.10  # 04 §5.4 item 6


class BootstrapSpec(_Strict):
    resamples: int = 2000  # 04 §8
    seed: int = 1  # 04 §9


class PermutationSpec(_Strict):
    n: int = 10000  # 04 §8
    seed: int = 2  # 04 §9


class StatisticsSpec(_Strict):
    primary_metric: str = "ac_at_1"  # 04 §8 primary test
    per: str = "system"  # 04 §8: per-system results are primary
    noninferiority: dict[str, object] | None = None
    holm_family: str | None = None
    bootstrap: BootstrapSpec = BootstrapSpec()
    permutation: PermutationSpec = PermutationSpec()
    mcnemar: bool = True  # 04 §8 secondary test


class ResourcesSpec(_Strict):
    workers: int = Field(default=1, ge=1)  # a priori: cases run one after another, in sorted order
    timeout_s: int = Field(default=600, ge=1)  # 04 §9; per case per method, a timeout is a miss
    max_rss_mb: int | None = None  # None: not enforced (04 §9's 3072 needs a subprocess runner)


class Experiment(_Strict):
    experiment_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")  # names the results directory
    description: str
    prereg: bool = False
    rq: tuple[str, ...] = ()
    dataset: DatasetSpec
    split: SplitSpec = SplitSpec()
    protocol: ProtocolSpec = ProtocolSpec()
    methods: tuple[MethodSpec, ...] = Field(min_length=1)
    calibration: CalibrationSpec = CalibrationSpec()
    metrics: tuple[MetricName, ...] = Field(min_length=1)  # required: summary.json holds just these
    statistics: StatisticsSpec = StatisticsSpec()
    resources: ResourcesSpec = ResourcesSpec()

    @model_validator(mode="after")
    def _runs_are_distinct(self) -> Experiment:
        for what, ids in (
            ("method ids", [m.id for m in self.methods]),
            ("dataset parts", self.dataset.parts),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"{what} must be unique (per_case.csv key), got {list(ids)}")
        for m in self.methods:
            if clash := sorted(set(m.overrides) & set(PROTOCOL_KEYS)):
                raise ValueError(f"method {m.id} overrides {clash}: set them in `protocol`")
        return self


def read_yaml(path: Path, what: str) -> object:
    """A YAML 1.2 file bench reads (experiment, case list); a missing file is a missing input."""
    if not path.is_file():
        raise ArtifactMissing(what, path)
    return yaml12.load_yaml_bytes(textio.read_bytes(path), source=path.as_posix())


def load_experiment(path: Path) -> Experiment:
    """Parse (YAML 1.2, duplicate keys rejected, as config/) and validate an experiment file."""
    try:
        return Experiment.model_validate(read_yaml(Path(path), "experiment"))
    except ValidationError as exc:
        raise ConfigError(f"experiment {Path(path).as_posix()}: {exc}") from None


def unsupported(exp: Experiment) -> list[str]:
    """What `exp` asks for that the v0 runner cannot run yet, with the adding task or reason if known."""
    p, r = exp.protocol, exp.resources
    checks = (
        (exp.dataset.normal_windows != "none", "dataset.normal_windows (R-13)"),
        (exp.split.scheme != "none", f"split.scheme {exp.split.scheme} (R-13)"),
        (exp.calibration.fit, "calibration.fit (R-13)"),
        (p.decoys is not None, "protocol.decoys (O-13)"),
        (p.anonymize_services or p.inject_proposals or p.permute_proposals, "protocol AI perturbations"),
        (r.workers != 1, "resources.workers > 1 (v0 runs sequentially)"),
        (r.max_rss_mb is not None, "resources.max_rss_mb (needs a subprocess runner)"),
    )
    todo = [what for bad, what in checks if bad]
    todo += [f"metrics {m} ({METRIC_TASKS[m]})" for m in exp.metrics if m not in METRIC_KEYS]
    for m in exp.methods:
        if m.kind not in ("veyltrace", "causatrix"):
            todo.append(f"methods {m.id}: kind {m.kind} (baselines, R-05)")
        elif m.ai.mode != "off" or m.ai.seeds:
            todo.append(f"methods {m.id}: AI arms (ai.mode {m.ai.mode}, seeds)")
    return todo


def select_cases(exp: Experiment, repo: Path) -> dict[str, tuple[list[str], list[str]]]:
    """Per dataset part: (case ids to run, excluded case ids), both sorted. A case list is a YAML
    list of 12-hex case ids, unique across datasets, so one file (bench/dev_cases.yaml) serves every
    part: each part keeps the ids it lists. A `cases` id that no part lists is an error."""
    listed = {d: set(adapter_for(d).list_cases(d, data_root())) for d in exp.dataset.parts}

    def ids(rel: str) -> set[str]:
        names = read_yaml(repo / rel, "case list")
        if not isinstance(names, list) or not all(isinstance(n, str) and is_case_id(n) for n in names):
            raise ConfigError(f"{rel}: expected a YAML list of 12-hex case ids")
        return set(cast("list[str]", names))

    spec = exp.dataset
    chosen = set[str]().union(*listed.values()) if spec.cases == "all" else ids(spec.cases)
    if stray := sorted(chosen.difference(*listed.values())):
        raise ConfigError(f"{spec.cases}: case ids in no dataset part {list(listed)}: {stray}")
    excluded = ids(spec.exclude) if spec.exclude else set()
    picked = {d: have & chosen for d, have in listed.items()}
    selected = {d: (sorted(have - excluded), sorted(have & excluded)) for d, have in picked.items()}
    if empty := [d for d, (cases, _) in selected.items() if not cases]:
        raise ConfigError(f"dataset parts {empty} select no case")
    return selected


def code_state(repo: Path) -> dict[str, object]:
    """run_manifest-style {commit, dirty} from core, plus bench_dirty: core's dirtiness ignores
    bench/, whose metrics and experiment YAMLs shape every reported number too (04 §10.2)."""
    commit, dirty = code_commit()
    spec = ["--", "bench", ":(exclude)bench/results"]
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", *spec],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        status = b"unknown"  # outside git the state is unknown, which counts as dirty (as in core)
    return {"commit": commit, "dirty": dirty, "bench_dirty": bool(status.strip())}
