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
from veyltrace_bench.tables.results import (
    REGISTER,
    REPLAY_ROLES,
    RQ3_DIR,
    Replay,
    Results,
    Rq3Intervals,
    load,
    load_replay,
    load_rq3,
    read_register,
)
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_file, sha256_text_lf
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
REVISES = "revises "  # the role of a revision's results: "revises <pre-registered id>"
#: bench/results folders that are neither an experiment nor generated output, and the RQ each
#: serves: RQ3 intervals (scripts/rq3_intervals.py, #555), RQ6 replay sites (03 §13.5),
#: AI model time and tokens (rq5-ai-cost) and Observe's slowest-laptop measurement (perf-o11, O-11).
SIDE_RQ = {"perf-o11": "RQ5", "replay": "RQ6", RQ3_DIR: "RQ3", "rq5-ai-cost": "RQ5"}
NESTED = frozenset({"replay", RQ3_DIR})  # one result per subfolder
GENERATED_DIRS = frozenset({"figures", "tables"})  # the generator's own output (generate.GENERATED)


@dataclass(frozen=True)
class Side:
    """A committed results folder that is not an experiment: `source` names it by its path
    under bench/results and hashes its files; `rq3` when it is an rq3-intervals folder."""

    source: Results
    rq: str
    rq3: Rq3Intervals | None = None


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
    replays: Mapping[str, Replay] = field(default_factory=dict[str, Replay])  # RQ6 role -> result (#440)
    sides: tuple[Side, ...] = ()  # the other committed results folders, sorted by path

    def revisions_of(self, experiment_id: str) -> tuple[str, ...]:
        """The 04 §12 revisions of a pre-registered experiment, sorted; () when it has none."""
        return tuple(sorted(new for new, old in self.revises.items() if old == experiment_id))

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

    def revised(self, new: str) -> Context:
        """This context with the results and spec of the experiment `new` revises replaced by
        `new`'s, so a builder's pass on it yields the revised rows. The spec keeps the
        pre-registered id, so a builder looking it up by id gets the revision's results, which say
        "revises <id>" in their source cell and stand in for it (`stands_in_for`, which tells
        generate.paired these rows from the revision's own, cited by its id)."""
        old = self.revises[new]
        results, specs = dict(self.results), dict(self.specs)
        results[old] = replace(self.results[new], role=f"{REVISES}{old}", stands_in_for=old)
        specs[old] = self.spec(new).model_copy(update={"experiment_id": old})
        return replace(self, results=results, specs=specs)


def reportable(experiments_dir: Path) -> tuple[Experiment, ...]:
    """Every experiment YAML except synth smoke runs, sorted by experiment id."""
    found = (load_experiment(p) for p in sorted(experiments_dir.glob("*.yaml"), key=by_name))
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
    yamls = sorted(experiments_dir.glob("*.yaml"), key=by_name)
    loaded = ((load_experiment(p), sha256_text_lf(p)) for p in yamls)
    found = sorted(loaded, key=lambda es: es[0].experiment_id)
    keep = [(e, sha) for e, sha in found if set(e.dataset.parts) != {SYNTH}]
    register, ids = read_register(results_root), {e.experiment_id for e, _ in keep}
    if unknown := sorted(set(register.reasons) - ids - CELLS):
        raise ConfigError(
            f"{REGISTER} names neither an experiment YAML nor a 04 §6 cell: {', '.join(unknown)}"
        )
    if bad := sorted(f"{k} -> {v}" for k, v in register.revises.items() if not {k, v} <= ids or k == v):
        raise ConfigError(f"{REGISTER} revises unknown experiments: {', '.join(bad)}")
    prereg = {e.experiment_id for e, _ in keep if e.prereg}
    if bad := sorted(
        f"{k} -> {v}" for k, v in register.revises.items() if v in register.revises or v not in prereg
    ):
        raise ConfigError(
            f"{REGISTER}: a revision names a pre-registered experiment directly, no chain: {', '.join(bad)}"
        )
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
        if (old := register.revises.get(exp.experiment_id)) is not None:
            role = f"{REVISES}{old}"  # a revision names what it revises wherever it is cited
        results[exp.experiment_id] = replace(res, protocol=protocol(spec), role=role)
    for old, res in list(results.items()):  # the arms the revisions of a revised experiment run
        if res.revised_as:
            ran = {m.id for new in res.revised_as for m in (specs.get(new) or _yaml(keep, new)).methods}
            results[old] = replace(res, revision_methods=frozenset(ran))
    cells = {k: v for k, v in register.reasons.items() if k in CELLS and k not in ids}
    root = experiments_dir.resolve().parents[1]  # bench/experiments -> the repo
    replays = {role: load_replay(results_root, role) for role in REPLAY_ROLES}
    sides = _sides(results_root, {e.experiment_id for e, _ in found})
    return Context(
        tuple(e for e, _ in keep), results, specs, cells, register.revises, dev, root, replays, sides
    )


def _yaml(keep: list[tuple[Experiment, str]], experiment_id: str) -> Experiment:
    return next(e for e, _ in keep if e.experiment_id == experiment_id)


def by_name(path: Path) -> str:
    """Sort key for files and folders of one directory: the name by code point, the same on every
    platform. Sorting `Path` objects is case-insensitive on Windows and by code point on POSIX, so
    `README.md` next to lower-case names moved between hosts (#664)."""
    return path.name


def _side(results_root: Path, folder: Path) -> Side:
    name = folder.relative_to(results_root).as_posix()
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=by_name)
    hashes = tuple((p.name, sha256_file(p)) for p in files)
    top = name.split("/", 1)[0]
    rq3 = load_rq3(results_root, folder.name) if top == RQ3_DIR else None
    return Side(Results(name, hashes=hashes, path=folder), SIDE_RQ.get(top, "-"), rq3)


def _sides(results_root: Path, experiment_ids: set[str]) -> tuple[Side, ...]:
    """Every committed results folder besides the experiments', the generated tables and figures,
    and the RQ6 replay roles (Context.replays), sorted by path."""
    if not results_root.is_dir():
        return ()
    out: list[Side] = []
    for top in sorted((p for p in results_root.iterdir() if p.is_dir()), key=by_name):
        if top.name in experiment_ids or top.name in GENERATED_DIRS:
            continue
        if top.name not in NESTED:
            out.append(_side(results_root, top))
            continue
        for sub in sorted((p for p in top.iterdir() if p.is_dir()), key=by_name):
            if not (top.name == "replay" and sub.name in REPLAY_ROLES):
                out.append(_side(results_root, sub))
    return tuple(out)
