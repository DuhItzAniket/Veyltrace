"""Answer keys of nezha-ob and nezha-tt (03 §13.1), derived from Nezha's fault lists.

Evaluation only, like the RCAEval keys in `answer_keys` (same row type, writer, path and loader).
A Nezha case is one entry of a day's `<date>-fault_list.json` (01 §3.3). Its identity and order
come from the adapter's own layout module, never re-derived here (#436 review): `discover` lists
the cases, `parse_key` gives (system, date, index), and `fault_times_ns` (ascending by `inject_time`)
gives the index and the injection time. This module reads the two truth fields the adapter never
opens: `inject_pod` (the root service) and `inject_type` (the fault). Service names go through
Infralume's own name rules from config/infralume.yaml, on the same input the adapter normalises for a
pod's metric file (the pod name without its generated suffix), so key and run name one service alike.
04 §3 labels Nezha "service; inner-service indicator": the inner-service JSON (`root_cause_*.json`,
a log template or metric per fault) is not read. Its log templates have no `indicator` value
(03 §1), and the metric answers follow from `inject_type` (`FAULTS`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from pydantic import ValidationError

from veyltrace_bench.answer_keys import FaultTruth, LayoutError, write_answer_keys
from veyltrace_contracts.models import AnswerKeyRow, System
from veyltrace_core import textio
from veyltrace_core.config import data_root as default_data_root
from veyltrace_core.config import load_config
from veyltrace_core.errors import UsageError
from veyltrace_infralume.adapters.nezha_layout import (
    DATASETS,
    SRC,
    discover,
    fault_list_name,
    fault_times_ns,
    parse_key,
)
from veyltrace_infralume.names import NameRules, strip_pod_suffix

#: `inject_time` text, UTC (01 §3.3). Parsed only to match an entry to its `fault_times_ns` index:
#: a parse that disagreed with the adapter's would find no index and fail.
INJECT_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
NS_PER_S: Final = 1_000_000_000
#: Nezha's five fault types (labels and their resource/code split: benchmarks_and_testbed §Q1) -> truth
#: in the 03 §1 vocabularies; the reading of each label is a priori. Resource faults: `cpu_contention`
#: and `network_delay`, indicators as RCAEval's cpu -> cpu, delay -> latency (04 §7). Code faults
#: (mode `code`): `cpu_consumed` (code that burns CPU: fault class and indicator cpu), `exception`
#: (`exception`) and `return` (an error return value: `error`). `exception` and `return` have no
#: indicator: Nezha's inner-service answer for them is a log template, which no `indicator` value
#: names. Like RE3's code faults (04 §7), they are left out of fine-grained AC@k. Any other
#: `inject_type` is an error, not a new value (AGENTS §4.2).
FAULTS: Final[Mapping[str, FaultTruth]] = MappingProxyType(
    {
        "cpu_contention": FaultTruth("cpu", "resource", "cpu"),
        "network_delay": FaultTruth("delay", "network", "latency"),
        "cpu_consumed": FaultTruth("cpu", "code", "cpu"),
        "exception": FaultTruth("exception", "code", None),
        "return": FaultTruth("error", "code", None),
    }
)


def _entries(day: Path) -> list[dict[str, object]]:
    """Every entry of the day's fault list, in file order (the order is taken from `fault_times_ns`)."""
    path = day / fault_list_name(day.name)
    raw: object = json.loads(textio.read_text(path))
    if not isinstance(raw, dict):
        raise LayoutError(f"{path}: expected an object of hour -> fault entries")
    found: list[dict[str, object]] = []
    for hour, entries in sorted(cast("dict[str, object]", raw).items()):
        if not isinstance(entries, list):
            raise LayoutError(f"{path}: hour {hour!r} is not a list")
        for entry in cast("list[object]", entries):
            if not isinstance(entry, dict):
                raise LayoutError(f"{path}: hour {hour!r} holds a fault entry that is not an object")
            found.append(cast("dict[str, object]", entry))
    return found


def _field(entry: Mapping[str, object], name: str, where: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str) or not value.strip():
        raise LayoutError(f"{where}: a fault entry has no {name}")
    return value


def _by_index(day: Path) -> tuple[tuple[int, ...], dict[int, Mapping[str, object]]]:
    """The day's `fault_times_ns` and its fault entries by case index (the position of their
    `inject_time` in those times)."""
    times = fault_times_ns(day)
    index = {t: i for i, t in enumerate(times)}
    where = str(day / fault_list_name(day.name))
    out: dict[int, Mapping[str, object]] = {}
    for entry in _entries(day):
        stamp = _field(entry, "inject_time", where)
        try:
            when = datetime.strptime(stamp, INJECT_TIME_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            raise LayoutError(f"{where}: inject_time {stamp!r} is not {INJECT_TIME_FORMAT}") from None
        position = index.get(int(when.timestamp()) * NS_PER_S)
        if position is None or position in out:
            raise LayoutError(f"{where}: inject_time {stamp!r} matches no single fault_times_ns entry")
        out[position] = entry
    if len(out) != len(index):
        raise LayoutError(f"{where}: {len(index)} fault times but {len(out)} entries")
    return times, out


def root_service(inject_pod: str, rules: NameRules) -> tuple[str, str | None]:
    """(service, component) of a pod name, as the adapter names that pod's metric file: suffix
    stripped, then the system's name rules. The component is set only where a suffix folds."""
    named = rules.normalise(strip_pod_suffix(inject_pod.strip().lower()))
    if named is None:
        raise LayoutError(f"inject_pod {inject_pod!r} is a dropped container, not a service")
    return named.service, None if named.component == named.service else named.component


def nezha_answer_key_rows(dataset: str, data_root: Path | None = None) -> list[AnswerKeyRow]:
    """One row per case of `dataset` (nezha-ob or nezha-tt) under `<data root>/nezha/src/rca_data`,
    in case_id order. The case_id is the adapter's: it hashes `nezha_key(system, date, index)`."""
    if dataset not in DATASETS:
        raise UsageError(f"unknown Nezha dataset {dataset!r}; expected one of {', '.join(DATASETS)}")
    root = default_data_root() if data_root is None else Path(data_root)
    cases = [c for c in discover(root) if c.dataset == dataset]
    if not cases:
        raise LayoutError(f"no {dataset} case under {root.joinpath(*SRC)}")
    cfg = load_config("infralume")
    rules: dict[str, NameRules] = {}
    days: dict[str, tuple[tuple[int, ...], dict[int, Mapping[str, object]]]] = {}
    rows: list[AnswerKeyRow] = []
    for case in cases:
        parsed = parse_key(case.key)
        if parsed is None:  # discover builds keys with nezha_key, so this is a layout-module bug
            raise LayoutError(f"{case.key!r} is not a Nezha case key")
        system, date, index = parsed
        day = root.joinpath(*SRC, date)
        if date not in days:
            days[date] = _by_index(day)
        times, entries = days[date]
        entry = entries[index]
        where = f"{day / fault_list_name(date)} entry {index}"
        label = _field(entry, "inject_type", where)
        truth = FAULTS.get(label.strip().lower())
        if truth is None:
            known = ", ".join(FAULTS)
            raise LayoutError(f"{where}: inject_type {label!r} has no fault class (known: {known})")
        service, component = root_service(
            _field(entry, "inject_pod", where), rules.setdefault(system, NameRules.from_config(cfg, system))
        )
        try:
            rows.append(
                AnswerKeyRow(
                    case_id=case.case_id,
                    dataset=dataset,
                    system=cast("System", system),  # ob|tt: parse_key admits no other
                    is_no_fault=False,
                    root_service=service,
                    root_component=component,
                    fault_class=truth.fault_class,
                    fault_label=label,
                    indicator=truth.indicator,
                    mode=truth.mode,
                    t_inject_ns=times[index],
                    t_end_ns=None,  # the fault list has no end time
                    injection_json=None,  # injection tool not stated (benchmarks_and_testbed §Q1)
                    extra_roots_json=None,
                    decoy_changes_json=None,
                    validated=None,
                    sli_impact_json=None,
                )
            )
        except ValidationError as exc:
            raise LayoutError(f"{where}: {exc}") from None
    return sorted(rows, key=lambda r: r.case_id)


def build_nezha_answer_keys(data_root: Path | None = None) -> dict[str, tuple[Path, str]]:
    """Derive and write the answer keys of nezha-ob and nezha-tt; dataset -> (path, sha256)."""
    root = default_data_root() if data_root is None else Path(data_root)
    return {d: write_answer_keys(d, nezha_answer_key_rows(d, root), root) for d in DATASETS}
