"""Committed results of one experiment, as the table generator reads them (R-17, 04 §9, §10).

Numbers come from `summary.json` only (04 §9: tables are generated from summary files). The
manifest gives the provenance every row prints (experiment id, code commit, dirtiness), and the
SHA-256 of all three result files traces each number back to them (04 §10.2). An experiment
without usable results is still a `Results`, holding the reason it is "not run": a missing
directory (with the reason from the R-16 cut list in `<results>/not_run.yaml` when it has one),
an incomplete result, an older summary version, a dirty work tree, or results of another version
of the experiment YAML than the committed one. A file that claims the current version but breaks
its contract is an error, never a silent "not run".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_contracts.models import BenchManifest, BenchSummary, SummaryGroup, SummaryInterval
from veyltrace_core import io, textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.yaml12 import load_yaml_bytes

SUMMARY, PER_CASE, MANIFEST = "summary.json", "per_case.csv", "manifest.json"
FILES = (MANIFEST, PER_CASE, SUMMARY)  # sorted: the order of the hashes in a table's sources
#: <results>/not_run.yaml, the R-16 cut list: `<id>: <reason>`, or `<id>: {revises: <id>}` for a
#: revised experiment (04 §12) printed next to the pre-registered one it revises, with an optional
#: `reason` when the revision itself is not run.
REGISTER = "not_run.yaml"
REVISES, REASON = "revises", "reason"
SUMMARY_VERSION = "1.1."  # the bench_summary minor the generator reads (03 §13.3)
NO_RESULTS = "no committed results in bench/results"  # the row names the experiment
SHORT_COMMIT = 8  # commit prefix printed in a row's source cell; the sources list has the full id
SHORT_SHA = 12  # experiment_sha256 prefix in a not-run reason

#: Case-mean summary keys, the ones bench_summary 1.1 gives a bootstrap interval (03 §13.3).
CASE_MEAN = frozenset(
    {f"{m}_at_{k}" for m in ("ac", "fine_ac", "chance", "chance_diff") for k in range(1, 6)}
    | {"avg_at_5", "mrr", "retrieval_at_k", "pool_retrieval", "decoy_ranked_first"}
)


@dataclass(frozen=True)
class Register:
    """The parsed not_run.yaml: not-run reasons by id, and revised → pre-registered ids."""

    reasons: dict[str, str] = field(default_factory=dict[str, str])
    revises: dict[str, str] = field(default_factory=dict[str, str])


def read_register(results_root: Path) -> Register:
    """`<results>/not_run.yaml` (empty when the file is absent); a malformed entry is an error."""
    path = results_root / REGISTER
    if not path.is_file():
        return Register()
    data = load_yaml_bytes(textio.read_bytes(path), source=REGISTER)
    if not isinstance(data, dict):
        raise ConfigError(f"{REGISTER}: expected a mapping of experiment id to reason")
    reasons: dict[str, str] = {}
    revises: dict[str, str] = {}
    for key, entry in data.items():
        reason: object = entry
        if (
            isinstance(entry, dict)
            and isinstance(entry.get(REVISES), str)
            and set(entry) <= {REVISES, REASON}
        ):
            revises[str(key)] = str(entry[REVISES])
            reason = entry.get(REASON)  # a revision without a reason is run, or will be
            if reason is None:
                continue
        if not isinstance(key, str) or not isinstance(reason, str) or not reason:
            raise ConfigError(f"{REGISTER}: {key!r} needs a non-empty reason string or {{revises: <id>}}")
        reasons[key] = reason
    return Register(dict(sorted(reasons.items())), dict(sorted(revises.items())))


@dataclass(frozen=True)
class Results:
    """One experiment's results, or the reason it has none (`reason` is then set)."""

    experiment_id: str
    reason: str | None = None
    commit: str | None = None
    hashes: tuple[tuple[str, str], ...] = ()  # (file name, sha256) in FILES order
    summary: BenchSummary | None = None
    manifest: BenchManifest | None = None  # dataset parts and case counts (Table 3)
    role: str | None = None  # "pre-registered" or "revises <id>" when the register pairs them
    protocol: str = ""  # the 04 §10.4 protocol statement printed in a table's sources
    _groups: dict[tuple[str, str, str], SummaryGroup] = field(
        default_factory=dict[tuple[str, str, str], SummaryGroup]
    )
    _intervals: dict[tuple[str, str | None, str, str], SummaryInterval] = field(
        default_factory=dict[tuple[str, str | None, str, str], SummaryInterval]
    )

    @property
    def label(self) -> str:
        """The source cell of a row: experiment id and short commit, or "(not run)", and its role."""
        base = (
            f"{self.experiment_id} (not run)"
            if self.commit is None
            else f"{self.experiment_id} @ {self.commit[:SHORT_COMMIT]}"
        )
        return f"{base} ({self.role})" if self.role else base

    @property
    def stats_reason(self) -> str | None:
        """The reason of a `statistics` string ("not run: …"), None for a statistics object."""
        if self.summary is None:
            return self.reason
        stats = self.summary.statistics
        return stats if isinstance(stats, str) else None

    def system_of(self, part: str) -> str:
        """The system of a dataset part as the summary's groups record it; the part's suffix
        (`re2-ob` → `ob`, 03 §2.1) only when no group has that part."""
        found = sorted({system for dataset, system, _ in self._groups if dataset == part})
        return found[0] if len(found) == 1 else part.split("-", 1)[1]

    def group(self, dataset: str, system: str, method: str) -> SummaryGroup | None:
        return self._groups.get((dataset, system, method))

    def missing(self, dataset: str, system: str | None, method: str) -> str | None:
        """Why (dataset, system, method) has no group, or None when it has one."""
        if self.reason is not None:
            return self.reason
        if system is not None and self.group(dataset, system, method) is None:
            return f"no ({dataset}, {system}, {method}) group in its summary.json"
        return None

    def metric(self, dataset: str, system: str, method: str, entry: str, key: str) -> Cell:
        """The summary value `metrics[entry][key]` of one group, with its interval when the key is
        a case mean; a rate-like value (cells.rate) unless the key is a count or percentile.
        Retrieval@K also names its K, the slate sizes of the group's runs (`retrieval_k`)."""
        if (why := self.missing(dataset, system, method)) is not None:
            return cells.not_run(why)
        group = self.group(dataset, system, method)
        assert group is not None  # missing() returned None
        values = getattr(group.metrics, entry)
        if values is None:
            return cells.not_run(f"the experiment does not list the metric `{entry}`")
        value = getattr(values, key)
        if isinstance(value, list):  # retrieval_k: the slate sizes K of the group's runs
            return cells.text(";".join(str(v) for v in value))
        if key.startswith("n_") or key.endswith(("_p50", "_p95", "_ms")):
            return cells.count(value)
        cell = self._case_mean(dataset, system, method, key, value) if key in CASE_MEAN else cells.rate(value)
        ks = getattr(values, "retrieval_k", None) if key == "retrieval_at_k" else None
        return (
            Cell(f"{cell.text} (K={';'.join(map(str, ks))})", cell.note) if ks and value is not None else cell
        )

    def _case_mean(self, dataset: str, system: str, method: str, key: str, value: float | None) -> Cell:
        if value is None:
            return cells.rate(value)
        interval = self._intervals.get((dataset, system, method, key))
        if interval is not None:
            return cells.rate(value, (interval.low, interval.high))
        why = self.stats_reason or f"summary.json statistics has no `{key}` interval for this group"
        return cells.rate(value, note=f"no interval: {why}")

    def count(self, dataset: str, system: str, method: str, key: str) -> Cell:
        """A group count (`n_fault`, `n_unranked`, …, or an `outcomes` entry)."""
        if (why := self.missing(dataset, system, method)) is not None:
            return cells.not_run(why)
        group = self.group(dataset, system, method)
        assert group is not None
        value = getattr(group.outcomes, key) if hasattr(group.outcomes, key) else getattr(group, key)
        return cells.count(value)

    def pooled(self, bench: str, method: str, key: str) -> Cell:
        """A pooled estimate over the experiment's parts of `bench`, system as stratum (03 §13.3):
        the interval's estimate and bounds, or why the summary has none."""
        if self.reason is not None:
            return cells.not_run(self.reason)
        if (interval := self._intervals.get((bench, None, method, key))) is not None:
            return cells.rate(interval.estimate, (interval.low, interval.high))
        if (why := self.stats_reason) is not None:
            return cells.not_run(why)
        assert self.summary is not None and not isinstance(self.summary.statistics, str)
        scope = f"{bench} pooled intervals"
        for item in self.summary.statistics.not_run:
            if item.scope == scope:
                return cells.not_run(f"{scope} {item.reason}")
        return cells.not_run(f"summary.json statistics has no pooled {bench} `{key}` interval")


def _version(path: Path) -> str:
    """The `schema_version` a result file claims, read before validation so an older file becomes
    a "not run" reason instead of an error."""
    data = json.loads(textio.read_bytes(path))
    return str(data.get("schema_version")) if isinstance(data, dict) else "unknown"


def load(
    results_root: Path, experiment_id: str, register: Register, yaml_sha256: str | None = None
) -> Results:
    """The committed results of `experiment_id` under `results_root`, or why it has none.
    `yaml_sha256` is `sha256_text_lf` of the committed experiment YAML: results whose manifest
    records another hash ran another version of the experiment and are not used."""
    out = results_root / experiment_id
    if not out.is_dir():
        return Results(experiment_id, register.reasons.get(experiment_id, NO_RESULTS))
    for name in FILES:
        if not (out / name).is_file():
            return Results(experiment_id, f"incomplete result: no {name} (bench writes {MANIFEST} last)")
    if not (version := _version(out / SUMMARY)).startswith(SUMMARY_VERSION):
        return Results(experiment_id, f"summary.json is bench_summary {version}; tables read 1.1 (re-run)")
    manifest = io.read_path("bench_manifest", out / MANIFEST, validate=True)
    summary = io.read_path("bench_summary", out / SUMMARY, validate=True)
    assert isinstance(manifest, BenchManifest) and isinstance(summary, BenchSummary)
    for found in (manifest.experiment_id, summary.experiment_id):
        if found != experiment_id:
            raise ConfigError(f"bench/results/{experiment_id}/ holds results of {found!r}")
    if manifest.code.dirty or manifest.code.bench_dirty:
        return Results(experiment_id, "results from a dirty work tree are never used (04 §10.2)")
    if yaml_sha256 is not None and manifest.experiment_sha256 != yaml_sha256:
        ran, now = manifest.experiment_sha256[:SHORT_SHA], yaml_sha256[:SHORT_SHA]
        return Results(
            experiment_id, f"results are from another version of the YAML (sha {ran}…, committed {now}…)"
        )
    stats = summary.statistics
    intervals = (
        {}
        if isinstance(stats, str)
        else {(i.dataset, i.system, i.method, i.metric): i for i in stats.intervals}
    )
    return Results(
        experiment_id,
        commit=manifest.code.commit,
        hashes=tuple((name, sha256_file(out / name)) for name in FILES),
        summary=summary,
        manifest=manifest,
        _groups={(g.dataset, g.system, g.method): g for g in summary.groups},
        _intervals=intervals,
    )
