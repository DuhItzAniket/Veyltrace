"""Committed results of one experiment, as the table generator reads them (R-17, 04 §9, §10).

Numbers come from `summary.json` only (04 §9: tables are generated from summary files). The
manifest gives the provenance every row prints (experiment id, code commit, dirtiness), and the
SHA-256 of all three result files traces each number back to them (04 §10.2). An experiment
without usable results is still a `Results`, holding the reason it is "not run": a missing
directory (with the reason from the R-16 cut list in `<results>/not_run.yaml` when it has one),
an incomplete result, an older summary version, or a dirty work tree. A file that claims the
current version but breaks its contract is an error, never a silent "not run".
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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
REGISTER = "not_run.yaml"  # <results>/not_run.yaml: {experiment_id: reason}, the R-16 cut list
SUMMARY_VERSION = "1.1."  # the bench_summary minor the generator reads (03 §13.3)
NO_RESULTS = "no committed results in bench/results"  # the row names the experiment
NO_GROUP = "its summary.json has no group for this dataset, system and method"
SHORT_COMMIT = 8  # commit prefix printed in a row's source cell; the sources list has the full id

#: Case-mean summary keys, the ones bench_summary 1.1 gives a bootstrap interval (03 §13.3).
CASE_MEAN = frozenset(
    {f"{m}_at_{k}" for m in ("ac", "fine_ac", "chance", "chance_diff") for k in range(1, 6)}
    | {"avg_at_5", "mrr", "retrieval_at_k", "pool_retrieval", "decoy_ranked_first"}
)


def read_register(results_root: Path) -> dict[str, str]:
    """The not-run reasons of `<results>/not_run.yaml` ({} when the file is absent)."""
    path = results_root / REGISTER
    if not path.is_file():
        return {}
    data = load_yaml_bytes(textio.read_bytes(path), source=REGISTER)
    if not isinstance(data, dict):
        raise ConfigError(f"{REGISTER}: expected a mapping of experiment id to reason")
    register: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise ConfigError(f"{REGISTER}: {key!r} needs a non-empty reason string")
        register[key] = value
    return dict(sorted(register.items()))


@dataclass(frozen=True)
class Point:
    """A summary value as a figure plots it: `value` None when it is not plotted, and `status`
    says why ("ok", "undefined: …" or "not run: …")."""

    value: float | None
    low: float | None = None
    high: float | None = None
    status: str = "ok"


@dataclass(frozen=True)
class Results:
    """One experiment's results, or the reason it has none (`reason` is then set)."""

    experiment_id: str
    reason: str | None = None
    commit: str | None = None
    hashes: tuple[tuple[str, str], ...] = ()  # (file name, sha256) in FILES order
    summary: BenchSummary | None = None
    manifest: BenchManifest | None = None  # dataset parts and case counts (Table 3)
    _groups: dict[tuple[str, str, str], SummaryGroup] = field(
        default_factory=dict[tuple[str, str, str], SummaryGroup]
    )
    _intervals: dict[tuple[str, str | None, str, str], SummaryInterval] = field(
        default_factory=dict[tuple[str, str | None, str, str], SummaryInterval]
    )

    @property
    def label(self) -> str:
        """The source cell of a row: experiment id and short commit, or "(not run)"."""
        if self.commit is None:
            return f"{self.experiment_id} (not run)"
        return f"{self.experiment_id} @ {self.commit[:SHORT_COMMIT]}"

    @property
    def stats_reason(self) -> str | None:
        """The reason of a `statistics` string ("not run: …"), None for a statistics object."""
        if self.summary is None:
            return self.reason
        stats = self.summary.statistics
        return stats if isinstance(stats, str) else None

    def group(self, dataset: str, system: str, method: str) -> SummaryGroup | None:
        return self._groups.get((dataset, system, method))

    def missing(self, dataset: str, system: str | None, method: str) -> str | None:
        """Why (dataset, system, method) has no group, or None when it has one."""
        if self.reason is not None:
            return self.reason
        if system is not None and self.group(dataset, system, method) is None:
            return NO_GROUP  # the row names the system and method
        return None

    def metric(self, dataset: str, system: str, method: str, entry: str, key: str) -> Cell:
        """The summary value `metrics[entry][key]` of one group, with its interval when the key is
        a case mean; a rate-like value (cells.rate) unless the key is a count or percentile."""
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
        if key not in CASE_MEAN or value is None:
            return cells.rate(value)
        interval = self._intervals.get((dataset, system, method, key))
        if interval is not None:
            return cells.rate(value, (interval.low, interval.high))
        why = self.stats_reason or f"summary.json statistics has no `{key}` interval for this group"
        return cells.rate(value, note=f"no interval: {why}")

    def point(self, dataset: str, system: str, method: str, entry: str, key: str) -> Point:
        """`metrics[entry][key]` of one group with its interval bounds, for a figure."""
        if (why := self.missing(dataset, system, method)) is not None:
            return Point(None, status=cells.not_run(why).note or "")
        group = self.group(dataset, system, method)
        assert group is not None
        if (values := getattr(group.metrics, entry)) is None:
            return Point(
                None, status=cells.not_run(f"the experiment does not list the metric `{entry}`").note or ""
            )
        if (value := getattr(values, key)) is None:
            return Point(None, status="undefined: " + cells.UNDEFINED_NOTE)
        interval = self._intervals.get((dataset, system, method, key))
        return Point(float(value), *((interval.low, interval.high) if interval else (None, None)))

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


def load(results_root: Path, experiment_id: str, register: Mapping[str, str]) -> Results:
    """The committed results of `experiment_id` under `results_root`, or why it has none."""
    out = results_root / experiment_id
    if not out.is_dir():
        reason = register.get(experiment_id, NO_RESULTS)
        return Results(experiment_id, reason)
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
