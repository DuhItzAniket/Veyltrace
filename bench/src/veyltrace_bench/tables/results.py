"""Committed results of one experiment, as the table generator reads them (R-17, 04 §9, §10).

Numbers come from `summary.json` only (04 §9: tables are generated from summary files). The
manifest gives the provenance every row prints (experiment id, code commit, dirtiness), and the
SHA-256 of all three result files traces each number back to them (04 §10.2). An experiment
without usable results is still a `Results`, holding the reason it is "not run": a missing
directory (with the reason from the R-16 cut list in `<results>/not_run.yaml` when it has one),
an incomplete result, a dirty work tree, or results of another version of the experiment YAML than
the committed one. Two cases are not "not run" (lead rules R1 and R5 of R-17 #46): a pre-registered
experiment that a 04 §12 revision replaces says "revised as <id>", and results in an older summary
version ran, so they keep their provenance and say they are not tabulated. A file that claims the
current version but breaks its contract is an error, never a silent "not run".

Besides summary.json, one committed side result gives intervals (R3, R4):
`rq3-intervals/<id>/summary.json` holds the 95% cluster-bootstrap intervals of the RQ3 rates and
areas that summary.json leaves without one (scripts/rq3_intervals.py, #555); its files are hashed
into the experiment's sources.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from veyltrace_bench.summary import METRIC_KEYS
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_contracts.models import (
    BenchManifest,
    BenchReplaySummary,
    BenchSummary,
    SummaryGroup,
    SummaryInterval,
)
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
#: The 04 §12 row the register's revisions cite (2026-11-25, #532; the not_run.yaml comment above
#: them). The register names no row per revision, so a revised experiment's cells name this one (R1).
REVISION_ROW = "04 §12, 25 Nov"
#: Why that row's revisions drop an arm of the pre-registered experiment (the 04 §12 row of
#: 2026-11-25 and the YAML headers of its revisions), so a dropped arm cites the cut, not a gap (R1).
REVISION_CUT = "cut for v1.0 for the LLM budget; #532, ADR 20261121-ak-r16-cut-list, addendum of 25 Nov"
SUMMARY_VERSIONS = ("1.1.", "1.2.")  # the bench_summary minors the generator reads (03 §13.3)
#: The reason of results in another bench_summary minor: they ran, so they are "not tabulated" (R5).
OLD_FORMAT = (
    "ran (bench_summary {}); its summary.json is not tabulated: the tables read 1.1 and 1.2 (03 §13.3)"
)
#: Entries bench_summary 1.2 added (CCR #404): a 1.1 file has them null although they are listed.
NEW_IN_1_2 = frozenset({"coverage", "set_size", "no_fault_rates", "risk_coverage", "selective_accuracy",
                        "decoy_top1_change", "permutation_invariance"})  # fmt: skip
#: Shares over independent (case, seed) pairs and their counts, which get an exact binomial
#: interval (04 §8 "Proportions": no clusters, so exact binomial CIs; 03 §13.3).
EXACT_SHARES = {"decoy_top1_change": "n_pairs", "permutation_invariance": "n_cases"}
NO_RESULTS = "no committed results in bench/results"  # the row names the experiment
NO_GROUP = "its summary.json has no group for this dataset, system and method"
UNLISTED = "the experiment does not list the metric `{}`"  # n/a, never "not run" (R2)
#: A value without an interval in any committed file (R3: 04 §8 asks for one; no new statistics here).
NO_INTERVAL = "no interval in the committed results (04 §8 asks for one)"
SHORT_COMMIT = 8  # commit prefix printed in a row's source cell; the sources list has the full id
SHORT_SHA = 12  # experiment_sha256 prefix in a not-run reason

#: Case-mean summary keys, the ones bench_summary 1.1 gives a bootstrap interval (03 §13.3).
CASE_MEAN = frozenset(
    {f"{m}_at_{k}" for m in ("ac", "fine_ac", "chance", "chance_diff") for k in range(1, 6)}
    | {"avg_at_5", "mrr", "retrieval_at_k", "pool_retrieval", "decoy_ranked_first"}
)
#: The summary entry of each key (03 §13.3), to tell an unlisted entry from a null value.
ENTRY_OF = {key: entry for entry, keys in METRIC_KEYS.items() for key in keys}

RQ3_DIR = "rq3-intervals"  # bench/results/rq3-intervals/<experiment_id>/ (#555, #635)
RQ3_FILES = ("rows.csv", "summary.json")  # sorted, as FILES
POOLED_SCOPE = "pooled"  # the rq3-intervals scope of the pooled estimate (system as stratum, 04 §8)
#: An rq3-intervals estimate must equal the summary.json value it bounds; both files write 9
#: decimals, so they agree to well within this (a priori).
RQ3_TOLERANCE = 1e-8


def revised_reason(revisions: tuple[str, ...]) -> str:
    """The reason of a pre-registered experiment its 04 §12 revisions replace (R1)."""
    return f"{cells.REVISED_AS}{' and '.join(revisions)} ({REVISION_ROW})"


@dataclass(frozen=True)
class Register:
    """The parsed not_run.yaml: not-run reasons by id, and revised → pre-registered ids."""

    reasons: dict[str, str] = field(default_factory=dict[str, str])
    revises: dict[str, str] = field(default_factory=dict[str, str])

    def revised_by(self, experiment_id: str) -> tuple[str, ...]:
        """The revisions of a pre-registered experiment, sorted; () when it has none."""
        return tuple(new for new, old in self.revises.items() if old == experiment_id)


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
class Point:
    """A summary value as a figure plots it: `value` None when it is not plotted, and `status`
    says why ("ok", "undefined: …" or "not run: …")."""

    value: float | None
    low: float | None = None
    high: float | None = None
    status: str = "ok"


@dataclass(frozen=True)
class Rq3Intervals:
    """`rq3-intervals/<id>/summary.json`: (system or "pooled", metric) -> (estimate, low, high), at
    `level` with `resamples` cluster resamples, for the experiment's one method."""

    name: str  # rq3-intervals/<id>, the path a table's sources cite
    level: float
    resamples: int
    intervals: dict[tuple[str, str], tuple[float, float, float]]
    hashes: tuple[tuple[str, str], ...]  # (rq3-intervals/<id>/<file>, sha256) in RQ3_FILES order
    #: The literal 04 §5.4 τ_nf sensitivity analysis (04 §12 row of 2026-11-21, logged 26 Nov): its
    #: rates as (scope, metric) -> (estimate, low, high), and each held-out fold's fit, sorted by fold.
    literal: dict[tuple[str, str], tuple[float, float, float]] = field(
        default_factory=dict[tuple[str, str], tuple[float, float, float]]
    )
    held_out: tuple[tuple[str, dict[str, object]], ...] = ()


@dataclass(frozen=True)
class OldSummary:
    """What a summary.json of an older bench_summary minor shows, read without validation (R5)."""

    version: str
    groups: int | None  # its number of groups, None when it has no group list
    statistics: str | None  # its `statistics` when that is a string


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
    path: Path | None = None  # bench/results/<id>/, for the per_case.csv a subset point reads (H1)
    interval_note: str | None = None  # why values recomputed outside summary.json have no interval
    file_version: str = ""  # schema_version as summary.json records it (io reads an older minor as current)
    revised_as: tuple[str, ...] = ()  # the 04 §12 revisions replacing it, when it has no results (R1)
    revision_methods: frozenset[str] | None = None  # the methods those revisions run (set by context)
    stands_in_for: str | None = None  # the pre-registered id whose slot a revision fills (Context.revised)
    old: OldSummary | None = None  # an older summary minor: what it shows (R5)
    rq3: Rq3Intervals | None = None  # the RQ3 intervals of the experiment's one method (R3, R4)
    _groups: dict[tuple[str, str, str], SummaryGroup] = field(
        default_factory=dict[tuple[str, str, str], SummaryGroup]
    )
    _intervals: dict[tuple[str, str | None, str, str], SummaryInterval] = field(
        default_factory=dict[tuple[str, str | None, str, str], SummaryInterval]
    )

    @property
    def label(self) -> str:
        """The source cell of a row: experiment id and short commit, "(not run)" or the revisions
        replacing it, and its role; a side result without a commit is its path."""
        if self.revised_as:
            role = f"{self.role}; " if self.role else ""
            return f"{self.experiment_id} ({role}{cells.REVISED_AS}{' and '.join(self.revised_as)})"
        if self.commit is not None:
            base = f"{self.experiment_id} @ {self.commit[:SHORT_COMMIT]}"
        else:
            base = self.experiment_id if self.reason is None else f"{self.experiment_id} (not run)"
        return f"{base} ({self.role})" if self.role else base

    def why(self, method: str | None = None) -> str | None:
        """Why the experiment has no values (None when it has them); for a revised experiment, also
        that its revisions do not run `method`."""
        if self.reason is None:
            return None
        if method is not None and self.revision_methods is not None and method not in self.revision_methods:
            return f"{self.reason}; the revision does not run {method} ({REVISION_CUT})"
        return self.reason

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
        if (why := self.why(method)) is not None:
            return why
        if system is not None and self.group(dataset, system, method) is None:
            return NO_GROUP  # the row names the system and method
        return None

    def metric(self, dataset: str, system: str, method: str, entry: str, key: str) -> Cell:
        """The summary value `metrics[entry][key]` of one group, with its interval when the key is
        a case mean (bootstrap) or a share over pairs (exact binomial); a rate-like value
        (cells.rate) unless the key is a count or percentile.
        Retrieval@K also names its K, the slate sizes of the group's runs (`retrieval_k`)."""
        if (why := self.missing(dataset, system, method)) is not None:
            return cells.not_run(why)
        group = self.group(dataset, system, method)
        assert group is not None  # missing() returned None
        values = getattr(group.metrics, entry)
        if values is None and self.interval_note is not None:  # recomputed from per_case.csv (H1)
            return cells.not_applicable(
                f"a value recomputed from per_case.csv cannot give `{entry}` "
                "(it needs the answer key or services)"
            )
        if values is None and entry in NEW_IN_1_2 and self.file_version.startswith("1.1."):
            return cells.not_run(f"summary.json is bench_summary 1.1, which has no `{entry}` entry (re-run)")
        if values is None:
            return cells.not_applicable(UNLISTED.format(entry))
        value = getattr(values, key)
        if isinstance(value, list):  # retrieval_k: the slate sizes K of the group's runs
            return cells.text(";".join(str(v) for v in value))
        if key.startswith("n_") or key.endswith(("_p50", "_p95", "_ms")):
            return cells.count(value)
        if key in EXACT_SHARES:
            return cells.exact_share(value, getattr(values, EXACT_SHARES[key]))
        cell = (
            self._case_mean(dataset, system, method, key, value)
            if key in CASE_MEAN
            else self._other_rate(system, key, value)
        )
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
        if self.interval_note is not None:
            return cells.rate(value, note=self.interval_note)
        why = self.stats_reason or f"summary.json statistics has no `{key}` interval for this group"
        return cells.rate(value, note=f"no interval: {why}")

    def _other_rate(self, system: str, key: str, value: float | None) -> Cell:
        """A rate that is not a case mean: its rq3-intervals interval, else why it has none (R3)."""
        if value is None:
            return cells.rate(value)
        if (bounds := self._rq3(system, key, value)) is not None:
            return cells.rate(value, bounds)
        return cells.rate(value, note=self.interval_note or NO_INTERVAL)

    def _rq3(self, scope: str, key: str, value: float | None) -> tuple[float, float] | None:
        """The rq3-intervals bounds of `key` in `scope` (a system or "pooled"). The file is for the
        experiment's one method, and its estimate must equal the summary's value."""
        if self.rq3 is None or (found := self.rq3.intervals.get((scope, key))) is None:
            return None
        if len({m for _, _, m in self._groups}) != 1:
            raise ConfigError(f"{self.rq3.name} is for one method, but the summary has several")
        estimate, low, high = found
        if value is not None and abs(estimate - value) > RQ3_TOLERANCE:
            raise ConfigError(f"{self.rq3.name}: {scope} {key} {estimate!r} is not summary.json's {value!r}")
        return low, high

    def side_bounds(self, scope: str, key: str) -> tuple[float, float, float] | None:
        """(estimate, low, high) of a quantity only rq3-intervals has (e.g. `aurc_difference`, the
        H3c difference V − F) in `scope`, a system or "pooled"; None without that entry."""
        if self.rq3 is None or (found := self.rq3.intervals.get((scope, key))) is None:
            return None
        self._rq3(scope, key, None)  # the file is for the experiment's one method
        return found

    def point(self, dataset: str, system: str, method: str, entry: str, key: str) -> Point:
        """`metrics[entry][key]` of one group with its interval bounds, for a figure; a value without
        an interval in any committed file says so in its status (R3)."""
        if (why := self.missing(dataset, system, method)) is not None:
            return Point(None, status=cells.not_run(why).note or "")
        group = self.group(dataset, system, method)
        assert group is not None
        if (values := getattr(group.metrics, entry)) is None:
            return Point(None, status=cells.not_applicable(UNLISTED.format(entry)).note or "")
        if (value := getattr(values, key)) is None:
            return Point(None, status="undefined: " + cells.UNDEFINED_NOTE)
        if (interval := self._intervals.get((dataset, system, method, key))) is not None:
            return Point(float(value), interval.low, interval.high)
        if key not in CASE_MEAN and (bounds := self._rq3(system, key, float(value))) is not None:
            return Point(float(value), *bounds)
        return Point(float(value), status=f"ok; {self.interval_note or NO_INTERVAL}")

    def count(self, dataset: str, system: str, method: str, key: str) -> Cell:
        """A group count (`n_fault`, `n_unranked`, …, or an `outcomes` entry)."""
        if (why := self.missing(dataset, system, method)) is not None:
            return cells.not_run(why)
        group = self.group(dataset, system, method)
        assert group is not None
        value = getattr(group.outcomes, key) if hasattr(group.outcomes, key) else getattr(group, key)
        return cells.count(value)

    def _undefined_pooled(self, bench: str, method: str, key: str) -> Cell | None:
        """n/a when no per-system group of `method` in `bench` has a value for `key`: its entry is
        unlisted or null in every group (R2). None when a group has a value or there is no group."""
        mine = [g for (d, _, m), g in self._groups.items() if m == method and d.split("-", 1)[0] == bench]
        if not mine or (entry := ENTRY_OF.get(key)) is None:
            return None
        values = [getattr(g.metrics, entry) for g in mine]
        if all(v is None for v in values):
            return cells.not_applicable(UNLISTED.format(entry))
        if all(v is None or getattr(v, key) is None for v in values):
            return cells.rate(None)
        return None

    def pooled(self, bench: str, method: str, key: str) -> Cell:
        """A pooled estimate over the experiment's parts of `bench`, system as stratum (03 §13.3):
        the interval's estimate and bounds (summary.json, else rq3-intervals), n/a when no part has
        a value, or why the summary has none."""
        if (why := self.why(method)) is not None:
            return cells.not_run(why)
        if (interval := self._intervals.get((bench, None, method, key))) is not None:
            return cells.rate(interval.estimate, (interval.low, interval.high))
        if self.rq3 is not None and (found := self.rq3.intervals.get((POOLED_SCOPE, key))) is not None:
            self._rq3(POOLED_SCOPE, key, None)  # the file is for the experiment's one method
            return cells.rate(found[0], (found[1], found[2]))
        if (undefined := self._undefined_pooled(bench, method, key)) is not None:
            return undefined
        if (why := self.stats_reason) is not None:
            return cells.not_run(why)
        if self.summary is None:  # values recomputed from per_case.csv: no pooled interval either
            return cells.not_applicable(  # the table code computes no new statistics (R3)
                f"no pooled value for values recomputed from per_case.csv ({self.role})"
                if self.role
                else "no summary.json"
            )
        assert not isinstance(self.summary.statistics, str)
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
        if experiment_id not in register.reasons and (revisions := register.revised_by(experiment_id)):
            return Results(experiment_id, revised_reason(revisions), revised_as=revisions)
        return Results(experiment_id, register.reasons.get(experiment_id, NO_RESULTS))
    for name in FILES:
        if not (out / name).is_file():
            return Results(experiment_id, f"incomplete result: no {name} (bench writes {MANIFEST} last)")
    if not (version := _version(out / SUMMARY)).startswith(SUMMARY_VERSIONS):
        return _old(out, experiment_id, version, yaml_sha256)
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
    rq3 = load_rq3(results_root, experiment_id)
    return Results(
        experiment_id,
        commit=manifest.code.commit,
        hashes=tuple((name, sha256_file(out / name)) for name in FILES) + (rq3.hashes if rq3 else ()),
        summary=summary,
        manifest=manifest,
        path=out,
        file_version=version,
        rq3=rq3,
        _groups={(g.dataset, g.system, g.method): g for g in summary.groups},
        _intervals=intervals,
    )


def _json_object(path: Path, name: str) -> dict[str, object]:
    data: object = json.loads(textio.read_bytes(path))
    if not isinstance(data, dict):
        raise ConfigError(f"{name}: expected a JSON object")
    return {str(k): v for k, v in cast(dict[object, object], data).items()}


def _old(out: Path, experiment_id: str, version: str, yaml_sha256: str | None) -> Results:
    """Results in an older bench_summary minor (R5): they ran, so they keep their commit and hashes
    and say they are not tabulated. The manifest is read as JSON, without its contract, for the
    same provenance checks as a current one."""
    where = f"bench/results/{experiment_id}"
    manifest = _json_object(out / MANIFEST, f"{where}/{MANIFEST}")
    summary = _json_object(out / SUMMARY, f"{where}/{SUMMARY}")
    for found in (manifest.get("experiment_id"), summary.get("experiment_id", experiment_id)):
        if found != experiment_id:
            raise ConfigError(f"{where}/ holds results of {found!r}")
    code = manifest.get("code")
    commit = cast(dict[str, object], code).get("commit") if isinstance(code, dict) else None
    if not isinstance(commit, str):
        raise ConfigError(f"{where}/{MANIFEST} has no code.commit")
    flags = cast(dict[str, object], code)
    if flags.get("dirty") is not False or flags.get("bench_dirty") is not False:
        return Results(experiment_id, "results from a dirty work tree are never used (04 §10.2)")
    ran = manifest.get("experiment_sha256")
    if yaml_sha256 is not None and ran != yaml_sha256:
        shown, now = str(ran)[:SHORT_SHA], yaml_sha256[:SHORT_SHA]
        return Results(
            experiment_id, f"results are from another version of the YAML (sha {shown}…, committed {now}…)"
        )
    groups, stats = summary.get("groups"), summary.get("statistics")
    old = OldSummary(
        version,
        len(cast(list[object], groups)) if isinstance(groups, list) else None,
        stats if isinstance(stats, str) else None,
    )
    return Results(
        experiment_id,
        OLD_FORMAT.format(version),
        commit=commit,
        hashes=tuple((name, sha256_file(out / name)) for name in FILES),
        path=out,
        file_version=version,
        old=old,
    )


def _bounds(name: str, scope: str, metric: str, entry: object) -> tuple[float, float, float]:
    """(estimate, low, high) of one rq3-intervals entry."""
    got = (
        [cast(dict[str, object], entry).get(k) for k in ("estimate", "low", "high")]
        if isinstance(entry, dict)
        else []
    )
    nums = [float(v) for v in got if isinstance(v, int | float) and not isinstance(v, bool)]
    if len(nums) != 3:
        raise ConfigError(f"{name}: {scope}.{metric} needs numeric estimate, low and high")
    return nums[0], nums[1], nums[2]


def load_rq3(results_root: Path, experiment_id: str) -> Rq3Intervals | None:
    """`rq3-intervals/<experiment_id>/` when both its files are committed, else None; a file that
    names another experiment or is malformed is an error."""
    out, name = results_root / RQ3_DIR / experiment_id, f"{RQ3_DIR}/{experiment_id}"
    if not all((out / f).is_file() for f in RQ3_FILES):
        return None
    data = _json_object(out / RQ3_FILES[1], f"{name}/{RQ3_FILES[1]}")
    if data.get("experiment_id") != experiment_id:
        raise ConfigError(f"{name}/ holds the intervals of {data.get('experiment_id')!r}")
    level, resamples, scopes = data.get("level"), data.get("resamples"), data.get("intervals")
    if not isinstance(level, float) or not isinstance(resamples, int) or not isinstance(scopes, dict):
        raise ConfigError(f"{name}/{RQ3_FILES[1]} needs level, resamples and intervals")
    intervals = _scopes(name, "intervals", cast(dict[str, object], scopes))
    literal: dict[tuple[str, str], tuple[float, float, float]] = {}
    held_out: list[tuple[str, dict[str, object]]] = []
    if (sens := data.get(LITERAL)) is not None:
        if not isinstance(sens, dict) or not isinstance(folds := sens.get(HELD_OUT), dict):
            raise ConfigError(f"{name}: {LITERAL} needs a {HELD_OUT} object")
        rates = {k: v for k, v in cast(dict[str, object], sens).items() if k != HELD_OUT}
        literal = _scopes(name, LITERAL, rates)
        for fold, fit in sorted(cast(dict[str, object], folds).items()):
            if not isinstance(fit, dict):
                raise ConfigError(f"{name}: {LITERAL}.{HELD_OUT}.{fold} is not an object")
            held_out.append((fold, {str(k): v for k, v in cast(dict[object, object], fit).items()}))
    hashes = tuple((f"{name}/{f}", sha256_file(out / f)) for f in RQ3_FILES)
    return Rq3Intervals(name, level, resamples, intervals, hashes, literal, tuple(held_out))


LITERAL, HELD_OUT = "literal_tau_sensitivity", "held_out_fold"  # rq3-intervals summary.json (#555)


def _scopes(
    name: str, where: str, scopes: dict[str, object]
) -> dict[tuple[str, str], tuple[float, float, float]]:
    """(scope, metric) -> (estimate, low, high) of an rq3-intervals `{scope: {metric: interval}}`."""
    out: dict[tuple[str, str], tuple[float, float, float]] = {}
    for scope, metrics in sorted(scopes.items()):
        if not isinstance(metrics, dict):
            raise ConfigError(f"{name}: {where}.{scope} is not an object")
        for metric, entry in sorted(cast(dict[str, object], metrics).items()):
            out[(scope, metric)] = _bounds(name, f"{where}.{scope}", metric, entry)
    return out


REPLAY_ROLES = ("recording", "second-laptop", "ci")  # bench/results/replay/<role>/ (03 §13.5-§13.6)
REPLAY_FILES = ("replay.csv", "replay_summary.json")  # sorted, as FILES


@dataclass(frozen=True)
class Replay:
    """One RQ6 site's committed replay result (`source` cites it like an experiment), or why none."""

    source: Results
    summary: BenchReplaySummary | None = None


def load_replay(results_root: Path, role: str) -> Replay:
    """The committed `veyltrace bench replay --role <role>` result under `results_root`."""
    out, name = results_root / "replay" / role, f"replay/{role}"
    if not all((out / f).is_file() for f in REPLAY_FILES):
        return Replay(Results(name, f"no committed result (veyltrace bench replay --role {role})"))
    summary = io.read_path("bench_replay_summary", out / REPLAY_FILES[1], validate=True)
    assert isinstance(summary, BenchReplaySummary)
    if summary.role != role:
        raise ConfigError(f"bench/results/{name}/ holds the {summary.role!r} result")
    if summary.code.dirty or summary.code.bench_dirty:
        return Replay(Results(name, "results from a dirty work tree are never used (04 §10.2)"))
    hashes = tuple((f, sha256_file(out / f)) for f in REPLAY_FILES)
    s = summary.site
    where = f"{role}: {s.os}, Python {s.python}, host {s.host_id}" + (
        f", {s.ci_run_url}" if s.ci_run_url else ""
    )
    return Replay(Results(name, commit=summary.code.commit, hashes=hashes, protocol=where, path=out), summary)


AI_COST_DIR = "rq5-ai-cost"  # bench/results/rq5-ai-cost/ (scripts/rq5_ai_cost.py): recorded model cost


@dataclass(frozen=True)
class AiCost:
    """`rq5-ai-cost/summary.json`: the AI path's recorded model time and tokens per system (R4),
    read from the recording of `experiment_id`'s AI arms (`origin`, as the file names it)."""

    experiment_id: str
    origin: str
    systems: dict[str, dict[str, object]]


def load_ai_cost(folder: Path) -> AiCost:
    """The parsed `summary.json` of an rq5-ai-cost folder; a malformed file is an error."""
    name = f"{AI_COST_DIR}/{SUMMARY}"
    data = _json_object(folder / SUMMARY, name)
    eid, origin, systems = data.get("experiment_id"), data.get("source"), data.get("systems")
    if not isinstance(eid, str) or not isinstance(origin, str) or not isinstance(systems, dict):
        raise ConfigError(f"{name} needs experiment_id, source and systems")
    out: dict[str, dict[str, object]] = {}
    for system, entry in sorted(cast(dict[str, object], systems).items()):
        if not isinstance(entry, dict):
            raise ConfigError(f"{name}: systems.{system} is not an object")
        out[system] = {str(k): v for k, v in cast(dict[object, object], entry).items()}
    return AiCost(eid, origin, out)


PERF_DIR = "perf-o11"  # bench/results/perf-o11/ (O-11, #36): pipeline time and memory per case
PERF_COLUMNS = ("case", "system", "pass", "outcome", "wall_ms", "peak_rss_mb")  # then one `<step>_ms` each


def load_perf(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """A perf-o11 CSV as (its step columns, its rows); a file without the PERF_COLUMNS is an error."""
    rows = list(csv.DictReader(textio.read_text(path).splitlines()))
    header = tuple(rows[0]) if rows else ()
    if not set(PERF_COLUMNS) <= set(header):
        raise ConfigError(f"{PERF_DIR}/{path.name} needs the columns {', '.join(PERF_COLUMNS)}")
    steps = tuple(c for c in header if c not in PERF_COLUMNS and c.endswith("_ms"))
    return steps, rows
