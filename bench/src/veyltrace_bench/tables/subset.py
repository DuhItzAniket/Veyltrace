"""One arm's accuracy on a case subset, computed from a committed per_case.csv (R-17 review, H1).

The `re2-shift-*-brief-v1` arms run on the 90-case subset (bench/re2_investigate_cases.yaml), and
their frozen YAMLs compare them with re2-oracle-rq2-v1's brief rows *of the same case ids and
seeds*. summary.json pools all cases, so that 0 s point is computed here: the committed
per_case.csv rows of the arm, restricted to the subset's case ids and seeds and to unperturbed
runs, scored by bench's own `CaseScore` and aggregated by `summary.summarize`, exactly as bench
builds a summary group. per_case.csv keeps hits at 1, 3 and 5 only, so a row's position is the
first of those it hits: exact for AC@1, AC@3, AC@5 and Retrieval@K, the only metrics computed
here. There is no bootstrap interval (its clusters need the answer key) and no Chance@k (it needs
the case's services). Committed results stay the only source (AGENTS.md Never 8).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

import pyarrow as pa

from veyltrace_bench.metrics import HIT_COLUMN_KS, OK, RUN_OUTCOMES, CaseScore
from veyltrace_bench.summary import METRIC_KEYS, summarize
from veyltrace_bench.tables.results import PER_CASE, Results
from veyltrace_contracts.models import SummaryGroup, SummaryGroupMetrics
from veyltrace_core import io, textio
from veyltrace_core.errors import ConfigError
from veyltrace_core.yaml12 import load_yaml_bytes

COMPUTED = "computed from per_case.csv"
LISTED = ("ac_at_k", "retrieval_at_k")  # the summary entries per_case.csv determines exactly


def case_list(path: Path) -> frozenset[str]:
    """A 04 §9 case list (YAML list of 12-hex case ids)."""
    data = load_yaml_bytes(textio.read_bytes(path), source=path.name)
    if not isinstance(data, list) or not all(isinstance(c, str) for c in data):
        raise ConfigError(f"{path.name}: expected a list of case ids")
    return frozenset(str(c) for c in data)


def _score(row: dict[str, object]) -> CaseScore:
    """A per_case.csv row as the CaseScore bench scored it, as far as the row records it."""
    hits = {k: row[f"hit_at_{k}"] for k in HIT_COLUMN_KS}
    truth = hits[HIT_COLUMN_KS[0]] is not None  # a hit is null exactly when the case has no truth
    ranks = tuple(str(r) for r in row["ranks"]) if isinstance(row["ranks"], list) else ()
    outcome = str(row["run_outcome"])

    def flag(column: str) -> bool | None:
        value = row[column]
        return None if value is None else bool(value)

    return CaseScore(
        outcome=outcome, has_truth=truth, unranked=outcome == OK and not ranks, ranks=ranks,
        position=next((k for k in HIT_COLUMN_KS if hits[k]), None) if truth else None,
        fine_position=None, fine_applicable=False, retrieval_hit=flag("retrieval_hit"),
        pool_hit=flag("pool_hit"), in_set=flag("in_set"), set_size=None,
        fault_class_hit=flag("fault_class_hit"),
        n_candidates=None, in_universe=None, slate_k=None,
    )  # fmt: skip


def on_subset(
    res: Results, method: str, cases: Collection[str], seeds: Collection[int], label: str
) -> Results:
    """`res` with one group per (dataset, system) of `method`, recomputed over its unperturbed
    per_case.csv rows whose case id is in `cases` and seed in `seeds`; `label` names the subset."""
    tag = f"{COMPUTED}, {label}"
    if res.reason is not None or res.path is None:
        return replace(res, role=tag)
    table = io.read_path("bench_result", res.path / PER_CASE, validate=True)
    if not isinstance(table, pa.Table):  # bench_result is a CSV contract, so io returns a table
        raise ConfigError(f"{PER_CASE} of {res.experiment_id} did not read as a table")
    rows = [r for r in table.to_pylist() if r["method"] == method and r["variant"] is None]
    picked: defaultdict[tuple[str, str], list[CaseScore]] = defaultdict(list)
    for row in rows:
        if row["case_id"] in cases and row["seed"] in seeds:
            picked[(str(row["dataset"]), str(row["system"]))].append(_score(row))
    if not picked:
        why = f"its per_case.csv has no {method} rows for the {label}'s case ids and seeds"
        return replace(res, reason=why, role=tag)
    groups: dict[tuple[str, str, str], SummaryGroup] = {}
    for (dataset, system), scores in sorted(picked.items()):
        flat = summarize(scores, LISTED)
        counted = flat.pop("outcomes")
        assert isinstance(counted, dict)
        entries = {  # every entry of the contract's group (null unless listed), as bench writes a group
            name: {k: flat.pop(k) for k in METRIC_KEYS[name]} if name in LISTED else None
            for name in SummaryGroupMetrics.model_fields
        }
        outcomes = {o: counted.get(o, 0) for o in sorted(RUN_OUTCOMES)}
        group = {
            "dataset": dataset,
            "system": system,
            "method": method,
            **flat,
            "outcomes": outcomes,
            "metrics": entries,
        }
        groups[(dataset, system, method)] = SummaryGroup.model_validate(group)
    return replace(
        res, role=tag, interval_note=f"no interval: {tag}", summary=None, _groups=groups, _intervals={}
    )
