"""The committed R-16 cut list, bench/results/not_run.yaml (#421; lead decision on #45, 21 Nov):
every cut experiment and the Cloud-OpsBench cell print "not run" with the reason the paper prints.
The two VeylLab experiments joined on 22 Nov (Observe and Explain on #45; ADR addendum). On 25 Nov
the lead cut the remaining LLM-heavy AI arms, and rq3 and LOSO became AI-off revisions (04 §12,
#532; ADR addendum).
"""

from __future__ import annotations

from pathlib import Path

from veyltrace_bench.experiment import load_experiment
from veyltrace_bench.tables import generate
from veyltrace_bench.tables.context import CELLS
from veyltrace_bench.tables.results import read_register

BENCH = Path(__file__).resolve().parents[1]
RESULTS, EXPERIMENTS = BENCH / "results", BENCH / "experiments"
LLM_BUDGET = (
    "LLM budget; v1.0 runs the AI arm only on RE2 with the oracle alert, no shift and no decoy "
    "changes; candidate for v1.2 (ADR 20261121-ak-r16-cut-list)"
)
SHIFT_30 = "±30 s is exploratory in 04 §2; LLM budget (ADR 20261121-ak-r16-cut-list)"
VEYLLAB = (
    "VeylLab: 8 of 120 captures, no adapter yet (X-11, O-07); "
    "X-14 moves to v1.1 (ADR 20261121-ak-r16-cut-list)"
)
CUTS = {
    "fse26-oracle-rq1-v1": "stretch dataset; size, format and licence not verified (07 §1.1 cut item 2)",
    "re2-oracle-investigate-v1": "`investigate` mode is cut (07 §1.1 cut item 3)",
    "re2-oracle-rq3-investigate-v1": "`investigate` mode is cut (07 §1.1 cut item 3)",
    **dict.fromkeys(
        (  # the RCAEval-C AI grid: mid-grid cut on 21 Nov, the 4 corners on 25 Nov
            *(f"rcaevalc-pi{p}-l{r}-ai-v1" for p in ("0", "05", "1") for r in ("0", "2", "6")),
            "nezha-oracle-brief-v1",
            "re2-detected-rq2-v1",
            "re3-oracle-rq2-v1",
            *(f"re2-shift-{s}-brief-v1" for s in ("m60", "p60", "m120", "p120")),
        ),
        LLM_BUDGET,
    ),
    "re2-shift-m30-brief-v1": SHIFT_30,
    "re2-shift-p30-brief-v1": SHIFT_30,
    **dict.fromkeys(("veyllab-oracle-rq1-v1", "veyllab-oracle-rq2-v1"), VEYLLAB),
    "cloud-opsbench/agent-only": "optional in 04 §3; no experiment YAML",
}
#: 04 §12 revisions (#532): the AI-off arm of a pre-registered experiment whose brief arm is cut.
REVISES = {"re2-oracle-rq3-off-v1": "re2-oracle-rq3-v1", "re2-oracle-loso-off-v1": "re2-oracle-loso-v1"}


def test_the_register_holds_exactly_the_approved_cuts() -> None:
    register = read_register(RESULTS)
    assert register.reasons == dict(sorted(CUTS.items()))
    assert register.revises == dict(sorted(REVISES.items()))
    yamls = {p.stem for p in EXPERIMENTS.glob("*.yaml")}
    assert set(CUTS) - yamls == {"cloud-opsbench/agent-only"} <= CELLS  # every other key is an experiment
    assert set(REVISES) | set(REVISES.values()) <= yamls


def test_a_revision_is_its_pre_registered_experiment_minus_the_brief_arm() -> None:
    """04 §12: nothing but the id, description, prereg flag and the cut brief arm differs."""
    for new, old in REVISES.items():
        a, b = (load_experiment(EXPERIMENTS / f"{x}.yaml") for x in (old, new))
        assert (a.prereg, b.prereg) == (True, False)
        assert [m.id for m in a.methods] == ["veyltrace:off", "veyltrace:brief"]
        assert b.methods == a.methods[:1]
        same = {"experiment_id", "description", "prereg", "methods"}
        assert b.model_dump(exclude=same) == a.model_dump(exclude=same)


def test_bench_tables_prints_each_cut_as_not_run_with_its_reason() -> None:
    index = generate.outputs(RESULTS, EXPERIMENTS)["tables/a0-results-index.md"].decode()
    lines = index.splitlines()
    notes = {line.split(". ", 1)[1] for line in lines if line[:1].isdigit() and ". not run: " in line}
    for key, reason in CUTS.items():
        label = key if "/" not in key else f"04 §6 cell {key}"
        row = next(line for line in lines if line.startswith(f"| {label} |"))
        assert "| not run<sup>" in row, key
        assert f"not run: {reason}" in notes, key
