"""Every committed experiment YAML validates, and the pre-registered ones follow 04 §1 and §9."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from veyltrace_bench.experiment import Experiment, load_experiment
from veyltrace_bench.runner import check_rankers
from veyltrace_core.config import resolve_config

REPO = Path(__file__).resolve().parents[2]
EXPERIMENTS = sorted((REPO / "bench" / "experiments").glob("*.yaml"))
DEV_CASES = "bench/dev_cases.yaml"
#: 04 §3: synth is a smoke set and RE1 the tuning set; neither is a test split.
NOT_TEST = ("synth", "re1-ob", "re1-ss", "re1-tt")


def _prereg() -> list[Experiment]:
    return [e for e in map(load_experiment, EXPERIMENTS) if e.prereg]


@pytest.mark.parametrize("path", EXPERIMENTS, ids=[p.stem for p in EXPERIMENTS])
def test_every_experiment_validates(path: Path) -> None:
    exp = load_experiment(path)  # strict schema: an unknown key is a ConfigError
    assert exp.experiment_id == path.stem  # the results directory is named after the file
    check_rankers(exp)  # each causatrix:<ranker> is a ranker of config/causatrix.yaml


def test_prereg_experiments_exclude_the_development_cases_on_test_splits() -> None:
    prereg = _prereg()
    assert prereg
    for exp in prereg:
        assert exp.dataset.exclude == DEV_CASES, exp.experiment_id  # 04 §1
        assert not set(exp.dataset.parts) & set(NOT_TEST), exp.experiment_id
        assert "cost" in exp.metrics, exp.experiment_id  # 04 §9 lists cost; RQ5 is cross-cutting (04 §6)
        assert exp.resources.max_rss_mb is None, exp.experiment_id  # measured, not enforced (04 §9)


def test_prereg_ranker_methods_cover_every_configured_ranker() -> None:
    enabled = resolve_config({}, dataset="re2-ob", ai_mode="off").engine("causatrix")["rankers"]["enabled"]
    configured = sorted(cast("list[str]", enabled))
    for exp in _prereg():
        rankers = sorted(m.ranker for m in exp.methods if m.ranker is not None)
        if rankers or any(m.id == "causatrix:rrf" for m in exp.methods):  # 04 §6 "rankers alone + rrf"
            assert rankers == configured, exp.experiment_id
            assert any(m.id == "causatrix:rrf" for m in exp.methods), exp.experiment_id
