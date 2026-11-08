"""Tests of the experiment YAML schema (04 §9): strict keys, cited defaults, v0 feature gate."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import get_args

import pytest

from veyltrace_bench.experiment import (
    METRIC_TASKS,
    Experiment,
    MetricName,
    code_state,
    load_experiment,
    select_cases,
    unsupported,
)
from veyltrace_bench.summary import METRIC_KEYS
from veyltrace_core.errors import ArtifactMissing, ConfigError
from veyltrace_core.ids import case_id

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "synth-smoke.yaml"
BASE = 'experiment_id: t-1\ndescription: "x"\ndataset: {parts: [synth]}\nmetrics: [mrr]\n'
METHOD = 'methods: [{id: "veyltrace:off", kind: veyltrace}]\n'


def _load(tmp_path: Path, text: str) -> Experiment:
    path = tmp_path / "exp.yaml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return load_experiment(path)


def test_smoke_experiment_loads_with_the_cited_defaults() -> None:
    exp = load_experiment(SMOKE)
    assert exp.experiment_id == "synth-smoke" and exp.dataset.parts == ("synth",)
    assert (exp.split.seed, exp.split.cluster) == (20261108, ("system", "service", "fault"))  # 04 §5.4
    assert (exp.protocol.alert, exp.protocol.shift_s, exp.protocol.sources_drop) == ("oracle", 0, ())
    assert (exp.calibration.alpha, exp.calibration.no_fault_beta) == (0.10, 0.10)  # 09 §3.7, 04 §5.4
    assert (exp.statistics.bootstrap.resamples, exp.statistics.permutation.n) == (2000, 10000)  # 04 §8
    assert exp.resources.timeout_s == 600 and exp.methods[0].ai.mode == "off"
    assert unsupported(exp) == []


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (BASE + METHOD + "bogus: 1\n", "bogus"),  # unknown top-level key
        (BASE + METHOD + "protocol: {shift: 3}\n", "shift"),  # unknown nested key
        (BASE + METHOD + "protocol: {alert: live}\n", "alert"),  # live is demo only (04 §5.1)
        (BASE.replace("[mrr]", "[accuracy]") + METHOD, "metrics"),
        (BASE.replace("metrics: [mrr]\n", "") + METHOD, "metrics"),  # required: summary.json = the list
        (BASE + "methods: []\n", "methods"),
        (BASE + METHOD.replace("]", ', {id: "veyltrace:off", kind: veyltrace}]'), "unique"),
        (BASE.replace("[synth]", "[synth, synth]") + METHOD, "dataset parts must be unique"),
        (BASE + "methods: [{id: m, kind: veyltrace, overrides: {core.alert.shift_s: 5}}]\n", "protocol"),
        (BASE.replace("t-1", "T_1") + METHOD, "experiment_id"),
        (BASE + METHOD + "rq: []\nrq: [RQ1]\n", "duplicate"),  # YAML 1.2 loader, as for config/
        ("- not a mapping\n", "dictionary"),
    ],
)
def test_invalid_experiments_are_config_errors(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, text)


def test_missing_experiment_is_a_missing_input(tmp_path: Path) -> None:
    with pytest.raises(ArtifactMissing):
        load_experiment(tmp_path / "nope.yaml")


def test_unsupported_names_every_feature_v0_cannot_run(tmp_path: Path) -> None:
    exp = _load(
        tmp_path,
        BASE.replace("[mrr]", "[mrr, coverage, cost]")
        + "split: {scheme: crossfit2}\nprotocol: {decoys: {pi: 0.5}}\nresources: {workers: 2}\n"
        + "methods: [{id: b, kind: rcaeval}, {id: v, kind: veyltrace, ai: {mode: record, seeds: [1]}}]\n",
    )
    todo = " | ".join(unsupported(exp))
    for task in ("scheme crossfit2 (R-13)", "decoys (O-13)", "workers", "R-05", "AI arms", "coverage (R-13"):
        assert task in todo
    assert len(unsupported(exp)) == 7
    assert sorted([*METRIC_KEYS, *METRIC_TASKS]) == sorted(get_args(MetricName))  # each: computed or a task


def test_case_lists_are_case_ids_that_one_file_shares_across_parts(tmp_path: Path) -> None:
    ids = [case_id(f"synth-0{i}") for i in (1, 2, 3, 5)]
    lists = {"cases": f"{ids}\n", "dev": f"[{ids[2]}, 0123456789ab]\n"}  # + another part's dev case
    exp = _load(tmp_path, BASE.replace("[synth]", "[synth], cases: cases.yaml, exclude: dev.yaml") + METHOD)
    for name, body in lists.items():
        (tmp_path / f"{name}.yaml").write_text(body, encoding="utf-8")
    assert select_cases(exp, tmp_path) == {"synth": (sorted([*ids[:2], ids[3]]), [ids[2]])}
    bad = [("[0123456789ab]", "in no dataset part"), ("[synth-01]", "12-hex"), (f"[{ids[2]}]", "no case")]
    for body, match in bad:
        (tmp_path / "cases.yaml").write_text(body, encoding="utf-8")
        with pytest.raises(ConfigError, match=match):
            select_cases(exp, tmp_path)


def test_bench_dirtiness_comes_from_git(tmp_path: Path) -> None:
    def write(rel: str) -> None:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")

    write("bench/a.py")
    assert code_state(tmp_path)["bench_dirty"] is True  # outside git: unknown counts as dirty
    for args in (("init", "-q"), ("add", "bench"), ("commit", "-q", "-m", "a")):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=tmp_path, check=True)
    assert code_state(tmp_path)["bench_dirty"] is False
    write("bench/results/x/per_case.csv")
    assert code_state(tmp_path)["bench_dirty"] is False  # results are outputs, not code
    write("bench/b.py")
    assert code_state(tmp_path)["bench_dirty"] is True
