"""Exact binomial (Clopper–Pearson) intervals of the share cells (R-17 #46, 04 §8 "Proportions"):
H2b `decoy_top1_change` over `n_pairs` and H2c `permutation_invariance` over `n_cases`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from veyltrace_bench.tables import cells, generate, results
from veyltrace_core import textio
from veyltrace_core.errors import ConfigError

BENCH = Path(__file__).resolve().parents[1]
EXPERIMENTS = BENCH / "experiments"
FIXTURES = BENCH / "tests" / "fixtures" / "tables"
T6D = "tables/t06d-rq2-proposal-arms.md"
ROW = "| re2-oracle-permute-v1 | ob | veyltrace:brief | permutation_invariance |"


@pytest.mark.parametrize(
    ("share", "n", "text"),
    [
        (0.875, 8, "0.875 [0.473, 0.997]"),
        (0.125, 8, "0.125 [0.003, 0.527]"),
        (0.0, 8, "0.000 [0.000, 0.369]"),  # 0/n: the lower bound is 0
        (1.0, 8, "1.000 [0.631, 1.000]"),  # n/n: the upper bound is 1
        (0.0, 1, "0.000 [0.000, 0.975]"),
        (1.0, 1, "1.000 [0.025, 1.000]"),
    ],
)
def test_a_share_prints_its_exact_interval(share: float, n: int, text: str) -> None:
    assert cells.exact_share(share, n) == cells.Cell(text, cells.PAIRS_NOTE)


def test_no_pairs_print_a_dash_with_its_reason() -> None:
    cell = cells.exact_share(None, 0)
    assert cell.text == cells.DASH and cell.note is not None and "n = 0" in cell.note


@pytest.mark.parametrize(("share", "n"), [(0.3, 8), (None, 8), (0.5, 0), (0.5, -1), (1.5, 2)])
def test_a_share_that_is_not_k_of_n_is_an_error(share: float | None, n: int) -> None:
    with pytest.raises(ConfigError):
        cells.exact_share(share, n)


def test_table_6d_is_golden() -> None:
    files = generate.outputs(FIXTURES / "results", EXPERIMENTS)
    assert files[T6D] == textio.read_bytes(FIXTURES / "expected" / "t06d-rq2-proposal-arms.md")


@pytest.mark.parametrize(
    ("share", "n", "cell"),
    [
        (0.0, 8, "0.000 [0.000, 0.369]<sup>1</sup> | 8 |"),
        (1.0, 8, "1.000 [0.631, 1.000]<sup>1</sup> | 8 |"),
        (None, 0, f"{cells.DASH}<sup>1</sup> | 0 |"),
    ],
)
def test_edge_counts_render_in_table_6d(tmp_path: Path, share: float | None, n: int, cell: str) -> None:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    path = root / "re2-oracle-permute-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    for group in doc["groups"]:
        group["metrics"]["permutation_invariance"] = {"permutation_invariance": share, "n_cases": n}
    textio.write_text(path, json.dumps(doc))
    table = generate.outputs(root, EXPERIMENTS)[T6D].decode()
    assert f"{ROW} {cell}" in table
    assert (cells.PAIRS_NOTE in table) is (n > 0)


def test_the_h2b_share_gets_its_interval_from_n_pairs(tmp_path: Path) -> None:
    root = tmp_path / "results"
    shutil.copytree(FIXTURES / "results", root)
    path = root / "re2-oracle-permute-v1" / "summary.json"
    doc = json.loads(textio.read_text(path))
    for group in doc["groups"]:
        group["metrics"]["decoy_top1_change"] = {"decoy_top1_change": 0.125, "n_pairs": 8}
    textio.write_text(path, json.dumps(doc))
    res = results.load(root, "re2-oracle-permute-v1", results.Register())
    key = "decoy_top1_change"
    assert res.metric("re2-ob", "ob", "veyltrace:brief", key, key) == cells.Cell(
        "0.125 [0.003, 0.527]", cells.PAIRS_NOTE
    )
    assert res.metric("re2-ob", "ob", "veyltrace:brief", key, "n_pairs") == cells.Cell("8")
