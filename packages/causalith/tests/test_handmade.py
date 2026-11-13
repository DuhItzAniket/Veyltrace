"""Golden tests of Causalith's run() on hand-made inputs (05-causalith §3, §7; R-06 pattern).

Synth's signal_cube.edges stays empty until Signalyth (O-02) lands, so the O-05 acceptance "graph
matches synth topology exactly" is pinned here on the synth toy topology written as Signalyth would.
`fixtures/handmade/<case>/inputs.json` holds the inputs ("_" keys are comments), all written through
io.write; `graph.nodes.txt` and `graph.edges.txt` are the expected canonical content. Refresh after
review: `VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/causalith/tests/test_handmade.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from veyltrace_causalith.api import run
from veyltrace_core import io, textio
from veyltrace_core.synth.layout import EXPECTED_EDGES, EXTERNAL_HOST, SERVICES
from veyltrace_core.testing import content_lines, make_context

HANDMADE = Path(__file__).resolve().parents[1] / "fixtures" / "handmade"
CASES = tuple(sorted(p.name for p in HANDMADE.iterdir() if p.is_dir()))
GOLDEN = {
    "graph.nodes": "graph.nodes.txt",
    "graph.edges": "graph.edges.txt",
    "graph.paths": "graph.paths.txt",
}
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"


def _run_dir(case: str, tmp_path: Path) -> Path:
    inputs = json.loads((HANDMADE / case / "inputs.json").read_text(encoding="utf-8"))
    for name in sorted(n for n in inputs if not n.startswith("_")):
        io.write(name, inputs[name], tmp_path)
    return tmp_path


@pytest.mark.parametrize("case", CASES)
def test_graph_matches_the_handmade_golden(tmp_path: Path, case: str) -> None:
    run_dir = _run_dir(case, tmp_path)
    assert run(make_context("causalith", run_dir, dataset="handmade")).status == "ok"
    for contract, name in GOLDEN.items():
        actual = content_lines(contract, io.path_of(contract, run_dir))
        golden = HANDMADE / case / name
        if os.environ.get(UPDATE_ENV) == "1":
            assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
            textio.write_bytes(golden, "".join(f"{line}\n" for line in actual).encode("utf-8"))
        assert golden.read_text(encoding="utf-8").splitlines() == actual


def test_the_graph_equals_the_synth_topology_exactly(tmp_path: Path) -> None:
    # O-05 acceptance: nodes and edges equal the synthetic topology (veyltrace_core.synth.layout).
    run_dir = _run_dir("synth-topology", tmp_path)
    run(make_context("causalith", run_dir, dataset="handmade"))
    nodes = {r["node"]: r for r in io.read_table("graph.nodes", run_dir, validate=True).to_pylist()}
    edges = {
        (r["src"], r["dst"]): r for r in io.read_table("graph.edges", run_dir, validate=True).to_pylist()
    }
    assert sorted(nodes) == sorted([*SERVICES, EXTERNAL_HOST])
    assert sorted(edges) == sorted(EXPECTED_EDGES)
    assert [n for n, r in nodes.items() if r["is_entry"]] == ["frontend"] and nodes["frontend"][
        "kind"
    ] == "entry"
    assert nodes[EXTERNAL_HOST]["kind"] == "external" and nodes[EXTERNAL_HOST]["provenance"] == ["traces"]
    assert nodes["checkout"]["provenance"] == ["logs", "metrics", "traces"]
    assert [k for k, r in edges.items() if r["anomalous"]] == [("checkout", "payment")]
    assert edges["checkout", "cart"]["weight"] == 0.75 and edges["checkout", "payment"]["weight"] == 0.25
    # Logs and the config event add provenance to edges traces already found (05 §3.4 merge).
    assert edges["frontend", "checkout"]["provenance"] == ["logs", "traces"]
    assert edges["recommend", "catalog"]["provenance"] == ["topology", "traces"]
    # A node's provenance includes the source and target of a counted mention or hint (05 §3.1).
    assert nodes["frontend"]["provenance"] == ["logs", "traces"]
    assert nodes["recommend"]["provenance"] == nodes["catalog"]["provenance"] == ["topology", "traces"]


def test_paths_run_from_every_node_to_the_entry(tmp_path: Path) -> None:
    # 05 §3.6: payment's best path climbs the anomalous checkout -> payment edge to the entry;
    # catalog has two routes; an entry is its own path; the external host reaches no entry.
    run_dir = _run_dir("synth-topology", tmp_path)
    run(make_context("causalith", run_dir, dataset="handmade"))
    rows = io.read_table("graph.paths", run_dir, validate=True).to_pylist()
    paths = {(r["candidate"], r["path_rank"]): (r["nodes"], r["anomalous_fraction"]) for r in rows}
    assert paths["payment", 1] == (["payment", "checkout", "frontend"], 2 / 3)
    assert [paths["catalog", k][0] for k in (1, 2)] == [
        ["catalog", "frontend"],
        ["catalog", "recommend", "frontend"],
    ]
    assert paths["frontend", 1] == (["frontend"], 0.0)
    assert EXTERNAL_HOST not in {c for c, _ in paths}
