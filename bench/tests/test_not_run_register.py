"""The committed R-16 cut list, bench/results/not_run.yaml (#421; lead decision on #45, 21 Nov):
every cut experiment and the Cloud-OpsBench cell print "not run" with the reason the paper prints.
The two VeylLab experiments joined on 22 Nov (Observe and Explain on #45; ADR addendum).
"""

from __future__ import annotations

from pathlib import Path

from veyltrace_bench.tables import generate
from veyltrace_bench.tables.context import CELLS
from veyltrace_bench.tables.results import read_register

BENCH = Path(__file__).resolve().parents[1]
RESULTS, EXPERIMENTS = BENCH / "results", BENCH / "experiments"
CORNERS = "LLM budget; the 4 corner cells bracket the effect (ADR 20261121-ak-r16-cut-list)"
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
        (
            "rcaevalc-pi0-l2-ai-v1",
            "rcaevalc-pi1-l2-ai-v1",
            "rcaevalc-pi05-l0-ai-v1",
            "rcaevalc-pi05-l2-ai-v1",
            "rcaevalc-pi05-l6-ai-v1",
        ),
        CORNERS,
    ),
    "re2-shift-m30-brief-v1": SHIFT_30,
    "re2-shift-p30-brief-v1": SHIFT_30,
    **dict.fromkeys(("veyllab-oracle-rq1-v1", "veyllab-oracle-rq2-v1"), VEYLLAB),
    "cloud-opsbench/agent-only": "optional in 04 §3; no experiment YAML",
}


def test_the_register_holds_exactly_the_approved_cuts() -> None:
    register = read_register(RESULTS)
    assert register.reasons == dict(sorted(CUTS.items())) and register.revises == {}
    yamls = {p.stem for p in EXPERIMENTS.glob("*.yaml")}
    assert set(CUTS) - yamls == {"cloud-opsbench/agent-only"} <= CELLS  # every other key is an experiment


def test_bench_tables_prints_each_cut_as_not_run_with_its_reason() -> None:
    index = generate.outputs(RESULTS, EXPERIMENTS)["tables/a0-results-index.md"].decode()
    lines = index.splitlines()
    notes = {line.split(". ", 1)[1] for line in lines if line[:1].isdigit() and ". not run: " in line}
    for key, reason in CUTS.items():
        label = key if "/" not in key else f"04 §6 cell {key}"
        row = next(line for line in lines if line.startswith(f"| {label} |"))
        assert "| not run<sup>" in row, key
        assert f"not run: {reason}" in notes, key
