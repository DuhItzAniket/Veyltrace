"""Seeded case subsets of the 04 §6 matrix: one repetition per cluster, for the costly AI arms.

`veyltrace:investigate` runs on "90 cases (one repetition per cluster, chosen by seed)" (04 §6), and
so do the AI arms marked "subset". The subset is a committed case list (04 §9 `cases`), generated
here once and frozen with the prereg-v1 tag, so it cannot be re-drawn after results are seen.
Clusters are 04 §5.4's (system, root service, fault); the draw uses only labels, never results.
`python -m veyltrace_bench.subsets` prints the RE2 list.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import numpy as np

from veyltrace_bench.answer_keys import load_answer_keys
from veyltrace_contracts.models import AnswerKeyRow

#: The 04 §5.4 split seed (item 2), reused so the subset adds no free choice of its own.
SUBSET_SEED = 20261108
RE2 = ("re2-ob", "re2-ss", "re2-tt")


def one_per_cluster(keys: Mapping[str, AnswerKeyRow], exclude: Collection[str], seed: int) -> list[str]:
    """One case id per (system, root service, fault) cluster, sorted. Excluded and no-fault cases
    are never drawn; clusters are visited in sorted order and each draws an index into its sorted
    case ids from one numpy generator (bench may use numpy's RNG for splits; veyltrace_core.rng)."""
    clusters: dict[tuple[str, str, str], list[str]] = {}
    for case, row in keys.items():
        if case in exclude or row.is_no_fault:
            continue
        cluster = (row.system or "", row.root_service or "", row.fault_label or "")
        clusters.setdefault(cluster, []).append(case)
    gen = np.random.default_rng(seed)
    picked = [ids[int(gen.integers(len(ids)))] for ids in (sorted(clusters[k]) for k in sorted(clusters))]
    return sorted(picked)


def re2_subset(exclude: Collection[str]) -> list[str]:
    """The RE2 subset: one case per cluster of the three RE2 parts, development cases excluded."""
    keys = {case: row for part in RE2 for case, row in load_answer_keys(part).items()}
    return one_per_cluster(keys, exclude, SUBSET_SEED)


if __name__ == "__main__":
    from pathlib import Path

    from veyltrace_bench.experiment import read_yaml

    dev = read_yaml(Path("bench/dev_cases.yaml"), "case list")
    assert isinstance(dev, list)
    for case in re2_subset({str(c) for c in dev}):
        print(f'- "{case}"')  # quoted: an all-digit id would parse as a YAML integer
