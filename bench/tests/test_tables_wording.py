"""What the generated tables and figures say (R-17 #46, adversarial review of the generator): no
private rule label in any output, each note keyed on the field it describes, and captions that say
what a derived column counts. Read from the fixture results and from the committed bench/results.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import generate
from veyltrace_bench.tables.results import REVISION_CUT
from veyltrace_bench.tables.rq1 import NO_AGENT_SLATE
from veyltrace_bench.tables.rq4 import OUTCOME_ROWS

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS, RESULTS = BENCH / "experiments", BENCH / "results"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
#: The orchestration labels of R-17's lead rules: they cite nothing a reader can look up.
RULE_LABEL = re.compile(r"\bR[1-7]\b")


@pytest.fixture(scope="module")
def committed() -> dict[str, str]:
    return {k: v.decode() for k, v in generate.outputs(RESULTS, EXPERIMENTS).items()}


def _note(text: str, cell: str) -> str:
    """The note a cell's `<sup>n</sup>` points to."""
    found = re.search(r"<sup>(\d+)</sup>", cell)
    assert found is not None, cell
    n = found.group(1)
    return next(line.split(". ", 1)[1] for line in text.splitlines() if line.startswith(f"{n}. "))


def _cells(text: str, first: str) -> list[str]:
    row = next(line for line in text.splitlines() if line.startswith(first))
    return [c.strip() for c in row.strip("|").split("|")]


def _column(text: str, name: str) -> int:
    header = next(line for line in text.splitlines() if line.startswith("| ") and f"| {name} |" in line)
    return [c.strip() for c in header.strip("|").split("|")].index(name)


def test_no_output_carries_a_rule_label(tmp_path: Path, committed: dict[str, str]) -> None:
    root = shutil.copytree(FIXTURES / "results", tmp_path / "results")
    fixture = {k: v.decode() for k, v in generate.outputs(root, EXPERIMENTS).items()}
    for source, files in (("fixtures", fixture), ("bench/results", committed)):
        for path, text in files.items():
            hits = [line for line in text.splitlines() if RULE_LABEL.search(line)]
            assert not hits, (source, path, hits[:3])


def test_a0_cites_the_cut_of_a_revised_arm_as_the_tables_do(committed: dict[str, str]) -> None:
    index = committed["tables/a0-results-index.md"]
    for eid in ("re2-oracle-rq3-v1", "re2-oracle-loso-v1"):
        status = _cells(index, f"| {eid} |")[3]
        assert _note(index, status).endswith(f"the revision does not run veyltrace:brief ({REVISION_CUT})")


def test_a0_counts_lift_at_k_without_its_own_interval(committed: dict[str, str]) -> None:
    """Lift@k is a ratio with no interval in any committed file, although AC@k − Chance@k, in the
    same summary entry, has one."""
    stats = _cells(committed["tables/a0-results-index.md"], "| re2-oracle-rq1-v1 |")[5]
    assert "lift: lift_at_1–5" in stats


@pytest.mark.parametrize(("table", "first"), [("t10-rq4-shift", "| 0 s |"), ("t11-rq4-ablation", "| none |")])
def test_the_reference_rows_coverage_gap_note_names_coverage_gap(
    committed: dict[str, str], table: str, first: str
) -> None:
    text = committed[f"tables/{table}.md"]
    rows = [line for line in text.splitlines() if line.startswith(f"{first} all | pooled | veyltrace:off |")]
    ref = next(r for r in rows if "revised<sup>" not in r and "0.910 [0.862, 0.948]" in r)
    gap = [c.strip() for c in ref.strip("|").split("|")][_column(text, "Coverage gap")]
    assert gap.startswith("no value<sup>")
    assert "reports `coverage_gap` per system only" in _note(text, gap)
    assert OUTCOME_ROWS.strip() in text  # Outcomes counts the normal windows too


def test_agent_only_pooled_rerank_is_n_a_as_per_system(committed: dict[str, str]) -> None:
    text = committed["tables/t06-rq2-re2-oracle-rq2-v1.md"]
    col = _column(text, "Rerank@1")
    for first in ("| ob | agent-only:brief |", "| pooled | agent-only:brief |"):
        cell = _cells(text, first)[col]
        assert cell.startswith("n/a<sup>") and _note(text, cell).endswith(NO_AGENT_SLATE), first


def test_table_11_says_how_confirmed_verdicts_is_derived(committed: dict[str, str]) -> None:
    text = committed["tables/t11-rq4-ablation.md"]
    assert "CONFIRMED verdicts is derived, not read: it is answer_rate_confirmed × n_fault" in text
    assert "within 1e-6 of k (a k / n check" in text
