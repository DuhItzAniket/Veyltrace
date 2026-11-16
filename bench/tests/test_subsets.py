"""The seeded one-per-cluster subset (04 §6) and the committed RE2 list it generated."""

from __future__ import annotations

from pathlib import Path

import pytest

from veyltrace_bench.answer_keys import load_answer_keys
from veyltrace_bench.experiment import read_yaml
from veyltrace_bench.subsets import RE2, one_per_cluster, re2_subset
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.config import data_root

REPO = Path(__file__).resolve().parents[2]
SUBSET = REPO / "bench" / "re2_investigate_cases.yaml"
RE2_CASES_PER_PART = 90  # 04 §3: 6 faults × 5 services × 3 repetitions per RE2 system


def _row(case: str, service: str | None, fault: str | None, *, no_fault: bool = False) -> AnswerKeyRow:
    fields = dict.fromkeys(AnswerKeyRow.model_fields)
    fields |= {"case_id": case, "dataset": "re2-ob", "system": "ob", "is_no_fault": no_fault}
    return AnswerKeyRow.model_validate(fields | {"root_service": service, "fault_label": fault})


def _keys() -> dict[str, AnswerKeyRow]:
    rows = [_row(f"{i:012x}", ("cart", "ad")[i % 2], ("cpu", "mem")[i // 6]) for i in range(12)]
    rows.append(_row("00000000ffff", None, None, no_fault=True))
    return {r.case_id: r for r in rows}


def test_one_case_per_cluster_seeded_and_never_excluded() -> None:
    keys = _keys()
    picked = one_per_cluster(keys, {"000000000000"}, seed=7)
    clusters = {(keys[c].root_service, keys[c].fault_label) for c in picked}
    assert len(picked) == len(clusters) == 4 and picked == sorted(picked)
    assert "000000000000" not in picked and "00000000ffff" not in picked
    assert one_per_cluster(dict(reversed(keys.items())), {"000000000000"}, seed=7) == picked  # order-free
    draws = {tuple(one_per_cluster(keys, (), seed=s)) for s in range(20)}
    assert len(draws) > 1  # the seed chooses the repetition


def test_committed_subset_is_one_per_re2_cluster() -> None:
    ids = read_yaml(SUBSET, "case list")
    dev = read_yaml(REPO / "bench" / "dev_cases.yaml", "case list")
    assert isinstance(ids, list) and isinstance(dev, list)
    assert len(ids) == len(set(ids)) == 90 and ids == sorted(ids)  # 04 §6: 90 cases
    assert not set(ids) & set(dev)


@pytest.mark.real_data
def test_committed_subset_is_the_generators_output() -> None:
    if not all((data_root() / "answer_keys" / f"{p}.parquet").is_file() for p in RE2):
        pytest.skip(f"RE2 answer keys not built under {data_root()}")
    if any(len(load_answer_keys(p)) < RE2_CASES_PER_PART for p in RE2):  # e.g. a dev-cases-only root
        pytest.skip(f"RE2 not fully fetched under {data_root()}: the subset is drawn from all 270 cases")
    dev = read_yaml(REPO / "bench" / "dev_cases.yaml", "case list")
    assert isinstance(dev, list)
    assert read_yaml(SUBSET, "case list") == re2_subset({str(c) for c in dev})
