"""05 §13: same seed gives the same plan; the grid is balanced per (service, fault)."""

from collections import Counter
from itertools import chain
from pathlib import Path

import make_plan
import pytest
from vlab.faults import CATALOG, NO_FAULT
from vlab.plan import parse
from vlab.plan_gen import ALWAYS_L2, DEFAULT_SERVICES, REPS, grid, night, plan_document, share


def test_same_seed_same_grid_and_different_seed_different_order() -> None:
    assert grid(7) == grid(7)
    assert grid(7) != grid(8)
    assert sorted(map(str, grid(7))) == sorted(map(str, grid(8)))  # same cases, other order


def test_grid_is_balanced_per_service_and_fault() -> None:
    cases = Counter((e["fault"], e.get("target")) for e in grid(1))
    for fault in CATALOG.values():
        targets = fault.targets if fault.fault_id == "F13" else DEFAULT_SERVICES
        for target in targets:
            assert cases[(fault.fault_id, target)] == REPS
    faults = sum(n for (f, _), n in cases.items() if f != NO_FAULT)
    assert 0.09 <= cases[(NO_FAULT, None)] / faults <= 0.11


def test_weak_l1_faults_always_run_at_l2() -> None:
    assert {e["severity"] for e in grid(1) if e["fault"] in ALWAYS_L2} == {"L2"}


def test_laptop_shares_are_disjoint_complete_and_even() -> None:
    full = grid(3)
    shares = [share(full, laptops=3, laptop=i) for i in (1, 2, 3)]
    assert sorted(map(str, chain.from_iterable(shares))) == sorted(map(str, full))
    assert max(map(len, shares)) - min(map(len, shares)) <= 1
    with pytest.raises(ValueError):
        share(full, laptops=3, laptop=4)


def test_nights_cut_a_share_in_order() -> None:
    mine = share(grid(3), laptops=3, laptop=2)
    nights = [night(mine, night=n, per_night=10) for n in range(1, 10)]
    assert list(chain.from_iterable(nights)) == mine


def test_every_night_is_a_valid_plan() -> None:
    mine = share(grid(5), laptops=3, laptop=1)
    for n in (1, 2):  # 46 cases at 24 per night
        plan = parse(plan_document(night(mine, night=n), seed=5))
        assert plan.entries


def test_cli_writes_a_plan(tmp_path: Path) -> None:
    out = tmp_path / "n1.yaml"
    assert make_plan.main(["--seed", "9", "--laptop", "1", "--night", "1", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("profile: ob")
    assert make_plan.main(["--seed", "9", "--laptop", "1", "--night", "99"]) == 1


def test_a_night_past_the_end_is_empty() -> None:
    assert night(share(grid(5), laptops=3, laptop=1), night=3) == []
