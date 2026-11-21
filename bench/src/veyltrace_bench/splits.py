"""Calibration splits of 04 §5.4 (R-13, #374): which cases calibrate which held-out cases.

Clusters are (system, root service, fault) (item 1): repetitions of a cluster share deployments
and DB state, so a cluster never straddles folds, and a normal window derived from a case follows
its case. Strata are (system, fault class), and no-fault cases form one stratum per system, each
no-fault case its own cluster (item 2). The strata are visited in sorted order; each one's sorted
clusters are shuffled by one numpy generator seeded with `split.seed` (bench may use numpy's RNG
for splits, as `subsets` does) and dealt alternately to fold A and fold B, the first stratum
starting with A, the next with B, and so on, so odd-sized strata do not all favour fold A.

A `FoldPlan` gives every test case its test fold (`bench_result.fold`) and the fold part of the
calibration file it is tested with, and every file the cases that fit it:
- `crossfit2` (item 3): a fold-A case is tested with the file fitted on fold B and vice versa, so
  every case gets exactly one held-out prediction and no calibration shares a cluster with it;
- `loso` (§5.2, item 7): a case of system s is tested with `loso-<s>`, fitted on the other systems;
- `transfer` (item 7): every case is tested with `calibrate_from`, fitted on `TRANSFER_SOURCES`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from veyltrace_bench.experiment import SplitSpec
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.errors import ConfigError

CLUSTER = ("system", "service", "fault")  # 04 §5.4 item 1 (04 §9 split.cluster)
STRATIFY = ("system", "fault")  # 04 §5.4 item 2: (system, fault class) (04 §9 split.stratify)
FOLDS = ("foldA", "foldB")  # 04 §5.4 item 3: the fold is the family id's last part (03 §12.1)
LOSO = "loso-"  # 04 §5.4 item 7, 03 §12.1: the LOSO fold part is loso-<system>
NO_FAULT = "no_fault"  # 04 §5.4 item 2: no-fault cases form one stratum per system
#: Transfer files (04 §5.4 item 7) -> the dataset parts that fit them: "every RE2-OB and RE2-TT
#: case except the development cases"; RE2-SS is left out because Nezha has only OB and TT.
TRANSFER_SOURCES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"rcaeval-re2.transfer-obtt": ("re2-ob", "re2-tt")}
)

type Cluster = tuple[str, str, str]
type Stratum = tuple[str, str]


@dataclass(frozen=True)
class FoldPlan:
    """test_fold: case -> bench_result.fold; applied: case -> fold part of the file it is tested
    with; fits: fold part -> the cases (keys of `keys`, or `fit_keys` for transfer) that fit it."""

    test_fold: Mapping[str, str]
    applied: Mapping[str, str]
    fits: Mapping[str, frozenset[str]]


def cluster_of(key: AnswerKeyRow) -> Cluster:
    """(system, root service, fault label); a no-fault case is a cluster of its own (item 2)."""
    system = key.system or ""
    if key.is_no_fault:
        return (system, NO_FAULT, key.case_id)
    return (system, key.root_service or "", key.fault_label or key.fault_class or "")


def stratum_of(key: AnswerKeyRow) -> Stratum:
    """(system, fault class), (system, no_fault) for no-fault cases; RE3's code faults have no
    fault class, so their fault label stands in (04 §7 scores them by mode)."""
    if key.is_no_fault:
        return (key.system or "", NO_FAULT)
    return (key.system or "", key.fault_class or key.fault_label or "")


def check_split(split: SplitSpec) -> None:
    """The split forms this module implements (04 §5.4); anything else fails before any run."""
    if split.scheme == "none":
        return
    if split.family is None:
        raise ConfigError(f"split.scheme {split.scheme} needs split.family (04 §9)")
    if split.cluster != CLUSTER or split.stratify != STRATIFY:
        raise ConfigError(
            f"split.cluster/stratify must be {list(CLUSTER)}/{list(STRATIFY)} (04 §5.4 items 1-2)"
        )
    if split.scheme == "transfer":
        source = split.calibrate_from or ""
        if source not in TRANSFER_SOURCES:
            raise ConfigError(
                f"split.calibrate_from {source!r} is not a 04 §5.4 item 7 file {list(TRANSFER_SOURCES)}"
            )
        if source.partition(".")[0] != split.family:
            raise ConfigError(f"split.calibrate_from {source} does not belong to split.family {split.family}")


def crossfit2(keys: Mapping[str, AnswerKeyRow], seed: int) -> FoldPlan:
    """Two folds by seeded, stratified, alternate cluster assignment; each tested on the other's fit."""
    strata: dict[Stratum, set[Cluster]] = {}
    for key in keys.values():
        strata.setdefault(stratum_of(key), set()).add(cluster_of(key))
    gen = np.random.default_rng(seed)
    fold_of: dict[Cluster, str] = {}
    for i, stratum in enumerate(sorted(strata)):
        clusters = sorted(strata[stratum])
        for j, pick in enumerate(gen.permutation(len(clusters))):
            fold_of[clusters[int(pick)]] = FOLDS[(i + j) % 2]
    test = {case: fold_of[cluster_of(key)] for case, key in sorted(keys.items())}
    other = {FOLDS[0]: FOLDS[1], FOLDS[1]: FOLDS[0]}
    fits = {f: frozenset(c for c, got in test.items() if got == f) for f in FOLDS}
    return FoldPlan(test, {c: other[f] for c, f in test.items()}, fits)


def loso(keys: Mapping[str, AnswerKeyRow]) -> FoldPlan:
    """One fold per system: its cases are tested with the fit on every other system (§5.2)."""
    systems = sorted({key.system or "" for key in keys.values()})
    if len(systems) < 2:
        raise ConfigError(f"split.scheme loso needs cases of two systems or more, got {systems}")
    test = {case: f"{LOSO}{key.system}" for case, key in sorted(keys.items())}
    fits = {f"{LOSO}{s}": frozenset(c for c, k in keys.items() if k.system != s) for s in systems}
    return FoldPlan(test, test, fits)


def transfer(keys: Mapping[str, AnswerKeyRow], fit_cases: frozenset[str], calibrate_from: str) -> FoldPlan:
    """Every case is a test case of the one `calibrate_from` fit; none of them fits it (item 7)."""
    if shared := sorted(fit_cases & set(keys)):
        raise ConfigError(f"transfer: test cases are also calibration cases of {calibrate_from}: {shared}")
    fold = calibrate_from.partition(".")[2]
    test = dict.fromkeys(sorted(keys), fold)
    return FoldPlan(test, test, {fold: fit_cases})
