from pathlib import Path
from typing import Any

import pytest
from vlab import LAB_DIR
from vlab.plan import DEFAULT_DURATIONS_S, load, parse


def _plan(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"profile": "ob", "seed": 1, "entries": [{"fault": "F01", "target": "frontend"}]}
    data.update(over)
    return data


def test_committed_smoke_plan_is_valid() -> None:
    plan = load(LAB_DIR / "plans" / "x02-smoke.yaml")
    assert [e.fault for e in plan.entries] == ["F01", "F04"]
    assert plan.durations_s == DEFAULT_DURATIONS_S


def test_defaults_and_duration_override() -> None:
    plan = parse(_plan(durations_s={"baseline": 60}))
    assert plan.dataset == "veyllab-ob"
    assert plan.entries[0].severity == "L1"
    assert plan.durations_s["baseline"] == 60
    assert plan.durations_s["fault"] == DEFAULT_DURATIONS_S["fault"]


@pytest.mark.parametrize(
    "bad",
    [
        _plan(profile="otel"),
        _plan(seed="x"),
        _plan(seed=True),
        _plan(entries=[]),
        _plan(extra=1),
        _plan(durations_s={"baseline": 0}),
        _plan(durations_s={"nap": 5}),
        _plan(entries=[{"fault": "F01", "target": "frontend", "decoy": True}]),
        _plan(entries=[{"fault": "F01", "target": "loadgenerator"}]),
        _plan(entries=[{"fault": "F01", "target": "frontend", "colour": "red"}]),
    ],
)
def test_rejects_bad_plans(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse(bad)


def test_load_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text("profile: ob\nseed: 3\nentries:\n  - {fault: F04, target: cartservice, severity: L2}\n",
                    encoding="utf-8")  # fmt: skip
    assert load(path).entries[0].severity == "L2"


def test_load_profile_per_entry() -> None:
    plan = parse(_plan(entries=[{"fault": "F01", "target": "frontend", "users": 30}]))
    assert plan.entries[0].users == 30
    assert parse(_plan()).entries[0].users == 10
    for bad in (20, True, "30"):
        with pytest.raises(ValueError):
            parse(_plan(entries=[{"fault": "F01", "target": "frontend", "users": bad}]))


def test_no_fault_entries_take_no_target() -> None:
    plan = parse(_plan(entries=[{"fault": "F14"}, {"fault": "F14", "users": 30}]))
    assert [(e.fault, e.target, e.users) for e in plan.entries] == [("F14", "", 10), ("F14", "", 30)]
    with pytest.raises(ValueError):
        parse(_plan(entries=[{"fault": "F14", "target": "frontend"}]))
