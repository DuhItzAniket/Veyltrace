"""Nezha answer keys (03 §13.1) from synthetic days in Nezha's published layout (01 §3.3).

Each day has a fault list and empty pod metric files (the adapter reads the system from their names),
nothing else. Entries are out of time order in the file and spread over hours "9" and "10", so the
case index must come from `fault_times_ns`, not from file or hour-text order. No data is downloaded.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from veyltrace_bench import answer_keys as ak
from veyltrace_bench import nezha_keys as nk
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.config import data_root, load_config
from veyltrace_core.errors import UsageError
from veyltrace_core.ids import case_id
from veyltrace_infralume.adapters import nezha_layout as layout
from veyltrace_infralume.names import NameRules

OB_DAY, TT_DAY = "2022-08-22", "2023-01-29"
OB_PODS = ("frontend-579b9bff58-t2dbm", "cartservice-7d9b8c6f5-zxq2w")
TT_POD = "ts-auth-service-6f8c7b9d4-x2b5k"


def _clock(date: str, hh: int, mm: int) -> str:
    return f"{date} {hh:02d}:{mm:02d}:07"


def _ns(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()) * 1_000_000_000


def _day(root: Path, date: str, faults: dict[str, list[dict[str, str]]], pods: tuple[str, ...]) -> Path:
    day = root.joinpath(*layout.SRC, date)
    (day / "metric").mkdir(parents=True)
    for pod in pods:
        (day / "metric" / f"{pod}_metric.csv").write_text("Time\n", encoding="utf-8")
    (day / layout.fault_list_name(date)).write_text(json.dumps(faults), encoding="utf-8")
    return day


def _entry(stamp: str, pod: str, kind: str) -> dict[str, str]:
    # inject_timestamp is wrong on purpose (as on the real Train Ticket days): never read.
    return {"inject_time": stamp, "inject_timestamp": "1", "inject_pod": pod, "inject_type": kind}


def _tree(root: Path, *, ob_kinds: tuple[str, str, str] = ("cpu_contention", "exception", "return")) -> Path:
    first, second, third = (_clock(OB_DAY, 9, 50), _clock(OB_DAY, 9, 55), _clock(OB_DAY, 10, 1))
    _day(
        root,
        OB_DAY,
        {  # "10" sorts before "9" as text; in hour 9 the later fault is listed first
            "10": [_entry(third, OB_PODS[0], ob_kinds[2])],
            "9": [_entry(second, OB_PODS[1], ob_kinds[1]), _entry(first, OB_PODS[0], ob_kinds[0])],
        },
        OB_PODS,
    )
    _day(
        root,
        TT_DAY,
        {
            "8": [
                _entry(_clock(TT_DAY, 8, 30), TT_POD, "cpu_consumed"),
                _entry(_clock(TT_DAY, 8, 20), TT_POD, "network_delay"),
            ]
        },
        (TT_POD, "ts-order-service-5c6d7f8b9-qwrtz"),
    )
    return root


def _ob_rows(root: Path) -> dict[str, AnswerKeyRow]:
    return {row.case_id: row for row in nk.nezha_answer_key_rows("nezha-ob", root)}


def test_case_ids_and_times_are_the_adapters() -> None:
    root = _tree(data_root())
    rows = _ob_rows(root)
    times = layout.fault_times_ns(root.joinpath(*layout.SRC, OB_DAY))
    keys = [layout.nezha_key("ob", OB_DAY, i) for i in range(3)]
    assert sorted(rows) == sorted(case_id(k) for k in keys) == [r.case_id for r in rows.values()]
    assert [c.case_id for c in layout.discover(root) if c.dataset == "nezha-ob"] == [case_id(k) for k in keys]
    truth = [(r.t_inject_ns, r.root_service, r.fault_label) for r in (rows[case_id(k)] for k in keys)]
    assert truth == [
        (times[0], "frontend", "cpu_contention"),  # 09:50, listed last in hour "9"
        (times[1], "cartservice", "exception"),
        (times[2], "frontend", "return"),  # hour "10", listed first in the file
    ]
    assert times[0] == _ns(_clock(OB_DAY, 9, 50))


def test_fault_types_map_onto_the_contract_vocabularies() -> None:
    root = _tree(data_root())
    rows = [*nk.nezha_answer_key_rows("nezha-ob", root), *nk.nezha_answer_key_rows("nezha-tt", root)]
    mapped = {r.fault_label: (r.fault_class, r.mode, r.indicator) for r in rows}
    assert mapped == {
        "cpu_contention": ("cpu", "resource", "cpu"),
        "network_delay": ("delay", "network", "latency"),
        "cpu_consumed": ("cpu", "code", "cpu"),
        "exception": ("exception", "code", None),
        "return": ("error", "code", None),
    }
    assert set(mapped) == set(nk.FAULTS)
    tt = next(r for r in rows if r.dataset == "nezha-tt")
    assert (tt.system, tt.root_service, tt.root_component) == ("tt", "ts-auth-service", None)
    assert not tt.is_no_fault
    assert {tt.t_end_ns, tt.injection_json, tt.extra_roots_json, tt.decoy_changes_json} == {None}


def test_root_service_follows_infralumes_name_rules() -> None:
    ob = NameRules.from_config(load_config("infralume"), "ob")
    assert nk.root_service("FrontendService-579b9bff58-t2dbm", ob) == ("frontend", None)  # OB alias
    assert nk.root_service("redis-db-5c6d7f8b9-qwrtz", ob) == ("redis", "redis-db")  # -db folds
    assert nk.root_service("ts_route_service-0", ob) == ("ts-route-service", None)  # ordinal; _ -> -
    with pytest.raises(ak.LayoutError, match="dropped container"):
        nk.root_service("istio-proxy", ob)


def test_build_writes_both_keys_and_load_reads_them_back(tmp_path: Path) -> None:
    built = nk.build_nezha_answer_keys(_tree(tmp_path / "a"))
    assert sorted(built) == ["nezha-ob", "nezha-tt"]
    for dataset, (path, _) in built.items():
        assert path == ak.answer_key_path(dataset, tmp_path / "a")
        loaded = ak.load_answer_keys(dataset, tmp_path / "a")
        assert list(loaded.values()) == nk.nezha_answer_key_rows(dataset, tmp_path / "a")
    assert Counter(r.fault_label for r in ak.load_answer_keys("nezha-tt", tmp_path / "a").values()) == {
        "network_delay": 1,
        "cpu_consumed": 1,
    }
    again = nk.build_nezha_answer_keys(_tree(tmp_path / "b"))
    assert {d: h for d, (_, h) in again.items()} == {d: h for d, (_, h) in built.items()}  # same bytes


def test_unknown_or_missing_truth_fails_and_names_the_entry() -> None:
    root = _tree(data_root(), ob_kinds=("cpu_contention", "pod_failure", "return"))
    with pytest.raises(ak.LayoutError, match=r"entry 1: inject_type 'pod_failure' has no fault class"):
        nk.nezha_answer_key_rows("nezha-ob", root)
    day = root.joinpath(*layout.SRC, OB_DAY)
    entries = {"9": [{"inject_time": _clock(OB_DAY, 9, 50), "inject_type": "exception"}]}
    (day / layout.fault_list_name(OB_DAY)).write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(ak.LayoutError, match="no inject_pod"):
        nk.nezha_answer_key_rows("nezha-ob", root)


def test_rejects_unknown_datasets_and_empty_trees(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="unknown Nezha dataset"):
        nk.nezha_answer_key_rows("re2-ob", tmp_path)
    with pytest.raises(ak.LayoutError, match="no nezha-tt case"):
        nk.nezha_answer_key_rows("nezha-tt", tmp_path)


@pytest.mark.real_data
def test_real_nezha_counts() -> None:
    """On the fetched data: 56 OB and 45 TT cases, every inject_type mapped (04 §3)."""
    if not data_root().joinpath(*layout.SRC).is_dir():
        pytest.skip("Nezha is not fetched under VEYLTRACE_DATA")
    rows = {d: nk.nezha_answer_key_rows(d) for d in layout.DATASETS}
    assert {d: len(r) for d, r in rows.items()} == {"nezha-ob": 56, "nezha-tt": 45}
