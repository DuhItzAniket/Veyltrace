"""What the table builders read: the reportable experiments and their results (R-17).

The committed experiment YAMLs say which experiments exist; `bench/results/<id>/` says what ran.
A builder cites experiments only through `Context.get` and `Context.spec`, so a builder naming an
experiment without a YAML fails at generation time, not in the paper.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from veyltrace_bench.experiment import Experiment, load_experiment
from veyltrace_bench.tables.results import REGISTER, Results, load, read_register
from veyltrace_core.errors import ConfigError

SYNTH = "synth"  # smoke dataset, never reported (04 §3, §9)


@dataclass(frozen=True)
class Context:
    """The reportable experiments (sorted by id) and their results."""

    experiments: tuple[Experiment, ...]
    results: Mapping[str, Results]

    def get(self, experiment_id: str) -> Results:
        if experiment_id not in self.results:
            raise ConfigError(f"a table cites {experiment_id!r}, which has no bench/experiments YAML")
        return self.results[experiment_id]

    def spec(self, experiment_id: str) -> Experiment:
        self.get(experiment_id)  # the same error for an unknown id
        return next(e for e in self.experiments if e.experiment_id == experiment_id)


def reportable(experiments_dir: Path) -> tuple[Experiment, ...]:
    """Every experiment YAML except synth smoke runs, sorted by experiment id."""
    found = [load_experiment(p) for p in sorted(experiments_dir.glob("*.yaml"))]
    keep = [e for e in found if set(e.dataset.parts) != {SYNTH}]
    return tuple(sorted(keep, key=lambda e: e.experiment_id))


def context(results_root: Path, experiments_dir: Path) -> Context:
    """The context of `results_root`; a not-run register entry without a YAML is a ConfigError."""
    exps = reportable(experiments_dir)
    register = read_register(results_root)
    ids = {e.experiment_id for e in exps}
    if unknown := sorted(set(register) - ids):
        raise ConfigError(f"{REGISTER} names experiments without a YAML: {', '.join(unknown)}")
    return Context(exps, {e.experiment_id: load(results_root, e.experiment_id, register) for e in exps})
