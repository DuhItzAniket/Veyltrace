"""What the table builders read: the reportable experiments and their results (R-17).

The committed experiment YAMLs say which experiments exist; `bench/results/<id>/` says what ran.
Where results are used, a builder reads the experiment as the manifest recorded it (its methods,
seeds, coordinates), and the results must come from the committed YAML (same `sha256_text_lf`).
A builder cites experiments only through `Context.get` and `Context.spec`, so a builder naming an
experiment without a YAML fails at generation time, not in the paper. Generation also fails when a
pre-registered RE2 experiment ran a development case (04 §1: those are reported separately).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from veyltrace_bench.experiment import Experiment, load_experiment
from veyltrace_bench.tables.results import REGISTER, Results, load, read_register
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_text_lf
from veyltrace_core.yaml12 import load_yaml_bytes

SYNTH = "synth"  # smoke dataset, never reported (04 §3, §9)
DEV_CASES = "dev_cases.yaml"  # bench/dev_cases.yaml, next to bench/experiments (04 §1)
PRE_REGISTERED = "pre-registered"
_COLUMNS = ("baselines", "rankers", "off", "brief", "investigate", "agent-only")  # 04 §6 columns
#: The planned (not "—") cells of the 04 §6 matrix as `<row>/<column>`; not_run.yaml may name one
#: that has no experiment YAML (e.g. Cloud-OpsBench), and a misspelt name is still an error.
_PLANNED = {  # 04 §6 row -> the indexes of its planned columns in _COLUMNS (synth is never reported)
    "re1-oracle": "012", "re2-oracle": "012345", "re2-detected": "01235", "re2-onset-shift": "0123",
    "re2-telemetry-ablation": "012", "re2-calibration": "234", "re2-loso": "23",
    "rcaevalc-decoy-grid": "01235", "re2-proposal-decoys": "345", "re3-oracle": "01235",
    "nezha-oracle": "0123", "re2-to-nezha": "2", "fse26-oracle": "012", "veyllab-oracle": "012345",
    "cloud-opsbench": "5",
}  # fmt: skip
CELLS = frozenset(f"{row}/{_COLUMNS[int(i)]}" for row, planned in _PLANNED.items() for i in planned)


def protocol(exp: Experiment) -> str:
    """The 04 §10.4 protocol of an experiment's numbers: parts and cases, alert, shift, sources,
    decoys, calibration family and alpha, AI arms with model and seeds."""
    p, d = exp.protocol, exp.dataset
    bits = [f"{', '.join(d.parts)} ({'all cases' if d.cases == 'all' else d.cases}"
            + (f", excluding {d.exclude})" if d.exclude else ")"), f"{p.alert} alert",
            f"shift {p.shift_s:+d} s" if p.shift_s else "no shift",
            "dropped " + ";".join(p.sources_drop) if p.sources_drop else "all sources"]  # fmt: skip
    if p.decoys:
        bits.append("decoys " + ", ".join(f"{k}={v}" for k, v in sorted(p.decoys.items())))
    if exp.split.scheme != "none":
        bits.append(
            f"split {exp.split.scheme}, calibration {exp.split.family}, alpha {exp.calibration.alpha:g}"
        )
    if d.normal_windows != "none":
        bits.append(f"normal windows {d.normal_windows}")
    arms = [f"{m.id} {m.ai.model} seeds {','.join(map(str, m.ai.seeds))}" for m in exp.methods if m.ai.seeds]
    bits.append("AI: " + "; ".join(arms) if arms else "AI off")
    return "; ".join(bits)


@dataclass(frozen=True)
class Context:
    """The reportable experiments (YAMLs, sorted by id), their results and the register."""

    experiments: tuple[Experiment, ...]
    results: Mapping[str, Results]
    specs: Mapping[str, Experiment] = field(default_factory=dict[str, Experiment])  # as the manifest ran it
    cells: Mapping[str, str] = field(default_factory=dict[str, str])  # 04 §6 cell -> not-run reason
    revises: Mapping[str, str] = field(default_factory=dict[str, str])  # revised id -> pre-registered id
    dev_cases: tuple[str, ...] | None = None  # bench/dev_cases.yaml; None when the file is absent
    root: Path | None = None  # the repo root: a YAML's `dataset.cases` path is relative to it (04 §9)

    def get(self, experiment_id: str) -> Results:
        if experiment_id not in self.results:
            raise ConfigError(f"a table cites {experiment_id!r}, which has no bench/experiments YAML")
        return self.results[experiment_id]

    def spec(self, experiment_id: str) -> Experiment:
        """The experiment as its manifest ran it when its results are used; else its YAML."""
        self.get(experiment_id)  # the same error for an unknown id
        return self.specs.get(experiment_id) or next(
            e for e in self.experiments if e.experiment_id == experiment_id
        )

    def revised(self) -> Context:
        """This context with each pre-registered experiment's results and spec replaced by those of
        the experiment that revises it, so a builder's second pass yields the revised rows."""
        results, specs = dict(self.results), dict(self.specs)
        for new, old in self.revises.items():
            results[old] = replace(self.results[new], role=f"revises {old}")
            specs[old] = self.spec(new)
        return replace(self, results=results, specs=specs)


def reportable(experiments_dir: Path) -> tuple[Experiment, ...]:
    """Every experiment YAML except synth smoke runs, sorted by experiment id."""
    found = (load_experiment(p) for p in sorted(experiments_dir.glob("*.yaml")))
    return tuple(sorted((e for e in found if set(e.dataset.parts) != {SYNTH}), key=lambda e: e.experiment_id))


def _dev_cases(path: Path) -> tuple[str, ...] | None:
    if not path.is_file():
        return None
    data = load_yaml_bytes(textio.read_bytes(path), source=path.name)
    if not isinstance(data, list) or not all(isinstance(c, str) for c in data):
        raise ConfigError(f"{path.name}: expected a list of case ids")
    return tuple(sorted(str(c) for c in data))


def context(results_root: Path, experiments_dir: Path) -> Context:
    """The context of `results_root`. A register entry naming neither an experiment YAML nor a
    04 §6 cell, a revision of an unknown experiment, or a development case in a pre-registered RE2
    experiment's runs is a ConfigError."""
    found = sorted(((load_experiment(p), sha256_text_lf(p)) for p in sorted(experiments_dir.glob("*.yaml"))),
                   key=lambda es: es[0].experiment_id)  # fmt: skip
    keep = [(e, sha) for e, sha in found if set(e.dataset.parts) != {SYNTH}]
    register, ids = read_register(results_root), {e.experiment_id for e, _ in keep}
    if unknown := sorted(set(register.reasons) - ids - CELLS):
        raise ConfigError(
            f"{REGISTER} names neither an experiment YAML nor a 04 §6 cell: {', '.join(unknown)}"
        )
    if bad := sorted(f"{k} -> {v}" for k, v in register.revises.items() if not {k, v} <= ids or k == v):
        raise ConfigError(f"{REGISTER} revises unknown experiments: {', '.join(bad)}")
    results: dict[str, Results] = {}
    specs: dict[str, Experiment] = {}
    dev = _dev_cases(experiments_dir.parent / DEV_CASES)
    for exp, sha in keep:
        res = load(results_root, exp.experiment_id, register, sha)
        if res.reason is None and res.manifest is not None:
            specs[exp.experiment_id] = spec = Experiment.model_validate(res.manifest.experiment)
            ran = {c for d in res.manifest.datasets for c in d.cases}
            if (
                dev
                and exp.prereg
                and any(p.startswith("re2-") for p in exp.dataset.parts)
                and (leak := ran & set(dev))
            ):
                raise ConfigError(
                    f"{exp.experiment_id} ran development cases {sorted(leak)} (04 §1: reported separately)"
                )
        else:
            spec = exp
        role = PRE_REGISTERED if exp.experiment_id in register.revises.values() else None
        results[exp.experiment_id] = replace(res, protocol=protocol(spec), role=role)
    cells = {k: v for k, v in register.reasons.items() if k in CELLS and k not in ids}
    root = experiments_dir.resolve().parents[1]  # bench/experiments -> the repo
    return Context(tuple(e for e, _ in keep), results, specs, cells, register.revises, dev, root)
