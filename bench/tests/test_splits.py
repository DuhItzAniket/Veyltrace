"""The 04 §5.4 calibration splits: clusters never straddle folds, every case is tested once."""

from __future__ import annotations

from collections import Counter

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_bench import splits
from veyltrace_bench.experiment import SplitSpec
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.errors import ConfigError

SERVICES, FAULTS = ("cart", "ad", "email"), (("cpu", "cpu"), ("mem", "mem"), ("delay", "delay"))


def _row(i: int, system: str, service: str | None, fault: tuple[str, str] | None) -> AnswerKeyRow:
    fields = dict.fromkeys(AnswerKeyRow.model_fields)
    label, fault_class = fault or (None, None)
    return AnswerKeyRow.model_validate(
        fields
        | {"case_id": f"{i:012x}", "dataset": f"re2-{system}", "system": system, "is_no_fault": fault is None}
        | {"root_service": service, "fault_label": label, "fault_class": fault_class}
    )


@st.composite
def answer_keys(draw: st.DrawFn) -> dict[str, AnswerKeyRow]:
    """Cases over 1-3 systems, clusters repeated 1-3 times, a few no-fault cases."""
    rows: list[AnswerKeyRow] = []
    for system in draw(st.lists(st.sampled_from(("ob", "ss", "tt")), min_size=1, max_size=3, unique=True)):
        for _ in range(draw(st.integers(1, 6))):
            service, fault = draw(st.sampled_from(SERVICES)), draw(st.sampled_from(FAULTS))
            rows += [_row(len(rows) + r, system, service, fault) for r in range(draw(st.integers(1, 3)))]
        rows += [_row(len(rows) + r, system, None, None) for r in range(draw(st.integers(0, 2)))]
    return {r.case_id: r for r in rows}


@given(answer_keys(), st.integers(0, 2**32 - 1))
def test_crossfit2_tests_every_case_once_on_the_other_folds_fit(
    keys: dict[str, AnswerKeyRow], seed: int
) -> None:
    plan = splits.crossfit2(keys, seed)
    assert sorted(plan.test_fold) == sorted(keys) and set(plan.test_fold.values()) <= set(splits.FOLDS)
    for case, fold in plan.test_fold.items():
        assert plan.applied[case] != fold and case in plan.fits[fold]  # its file never saw it
        assert case not in plan.fits[plan.applied[case]]
    assert (
        plan.fits["foldA"] | plan.fits["foldB"] == set(keys) and not plan.fits["foldA"] & plan.fits["foldB"]
    )
    folds_of: dict[splits.Cluster, set[str]] = {}
    for case, key in keys.items():
        folds_of.setdefault(splits.cluster_of(key), set()).add(plan.test_fold[case])
    assert all(len(f) == 1 for f in folds_of.values())  # no cluster straddles the folds (item 1)
    dealt: dict[splits.Stratum, Counter[str]] = {}
    for key in {splits.cluster_of(k): k for k in keys.values()}.values():  # one key per cluster
        dealt.setdefault(splits.stratum_of(key), Counter())[plan.test_fold[key.case_id]] += 1
    assert all(abs(n["foldA"] - n["foldB"]) <= 1 for n in dealt.values())  # dealt alternately
    assert splits.crossfit2(dict(reversed(keys.items())), seed) == plan  # order-free


def test_crossfit2_is_seeded_and_alternates_the_starting_fold_between_strata() -> None:
    # Four strata with one cluster each: the starting fold alternates A, B, A, B (sorted strata).
    keys = {r.case_id: r for r in (_row(i, "ob", "cart", FAULTS[i % 3]) for i in range(3))}
    keys |= {r.case_id: r for r in [_row(9, "ob", None, None)]}
    plan = splits.crossfit2(keys, seed=20261108)
    by_stratum = {splits.stratum_of(keys[c]): f for c, f in plan.test_fold.items()}
    assert [by_stratum[s] for s in sorted(by_stratum)] == ["foldA", "foldB", "foldA", "foldB"]
    many = {r.case_id: r for r in (_row(i, "ob", SERVICES[i % 3] + str(i), FAULTS[0]) for i in range(12))}
    assert len({tuple(sorted(splits.crossfit2(many, s).fits["foldA"])) for s in range(10)}) > 1


def test_no_fault_cases_are_their_own_clusters_in_one_stratum_per_system() -> None:
    a, b = _row(1, "ob", None, None), _row(2, "ob", None, None)
    assert splits.cluster_of(a) != splits.cluster_of(b) and splits.stratum_of(a) == splits.stratum_of(b) == (
        "ob",
        "no_fault",
    )
    assert splits.crossfit2({a.case_id: a, b.case_id: b}, 1).fits["foldA"] != frozenset(
        {a.case_id, b.case_id}
    )


@given(answer_keys())
def test_loso_fits_each_system_on_the_others(keys: dict[str, AnswerKeyRow]) -> None:
    systems = sorted({k.system for k in keys.values() if k.system})
    if len(systems) < 2:
        with pytest.raises(ConfigError, match="two systems"):
            splits.loso(keys)
        return
    plan = splits.loso(keys)
    assert sorted(plan.fits) == [f"loso-{s}" for s in systems]
    for case, key in keys.items():
        fold = plan.test_fold[case]
        assert fold == plan.applied[case] == f"loso-{key.system}" and case not in plan.fits[fold]
        assert plan.fits[fold] == {c for c, k in keys.items() if k.system != key.system}


def test_transfer_tests_every_case_on_the_one_external_fit() -> None:
    keys = {r.case_id: r for r in (_row(i, "ob", "cart", FAULTS[0]) for i in range(3))}
    fit = frozenset({"0000000000aa", "0000000000bb"})
    plan = splits.transfer(keys, fit, "rcaeval-re2.transfer-obtt")
    assert set(plan.test_fold.values()) == set(plan.applied.values()) == {"transfer-obtt"}
    assert plan.fits == {"transfer-obtt": fit}
    with pytest.raises(ConfigError, match="also calibration cases"):
        splits.transfer(keys, fit | {next(iter(keys))}, "rcaeval-re2.transfer-obtt")


@pytest.mark.parametrize(
    ("split", "match"),
    [
        ({"scheme": "crossfit2"}, "needs split.family"),
        ({"scheme": "loso", "family": "rcaeval-re2", "cluster": ["system", "service"]}, "split.cluster"),
        ({"scheme": "transfer", "family": "rcaeval-re2", "calibrate_from": "rcaeval-re2.foldA"}, "item 7"),
        ({"scheme": "transfer", "family": "nezha", "calibrate_from": "rcaeval-re2.transfer-obtt"}, "belong"),
    ],
)
def test_only_the_04_split_forms_are_accepted(split: dict[str, object], match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        splits.check_split(SplitSpec.model_validate(split))
    splits.check_split(SplitSpec())  # scheme none needs nothing
    splits.check_split(SplitSpec(family="rcaeval-re2", scheme="crossfit2"))
