"""Tests of the T9 re-rankings (09 §3.4): which atoms and edges each dropped source removes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from veyltrace_causatrix.views import Atom, graph_view
from veyltrace_causentra.config import config_from
from veyltrace_causentra.inputs import load_inputs
from veyltrace_causentra.loso import ablations, present, without
from veyltrace_causentra.trials import run_trials, trial_inputs
from veyltrace_contracts.models import Sources
from veyltrace_core.testing import make_context


def _a(n: int, cand: str, kind: str, refs: tuple[str, ...] = (), **args: Any) -> Atom:
    return Atom(f"E{n:010x}", cand, None, kind, args, 1.0, refs)


def _graph(edges: list[tuple[str, str, list[str]]]) -> Any:
    rows = [{"src": s, "dst": d, "weight": 1.0, "provenance": p} for s, d, p in edges]
    return graph_view(["a", "b", "c"], [("ext", "external")], rows, include_external=True)


def test_without_drops_the_source_s_atoms_and_its_only_edges() -> None:
    atoms = [
        _a(1, "a", "internal_anomaly", ("a|a|cpu|metrics",), detector="robust_z"),
        _a(2, "a", "spectrum", (), window="incident"),  # traces by kind (06 §3.4)
        _a(3, "b", "log_error_rate", ("b|b|error|logs",), window="incident"),
        _a(4, "b", "onset_precedence", (), scope="self", window="onset"),  # no source: always kept
        _a(5, "c", "intervention", ("c|c|cpu|metrics",), window="incident"),  # claim pass: never kept
    ]
    graph = _graph([("a", "b", ["traces"]), ("b", "c", ["logs", "traces"]), ("a", "c", ["topology"])])
    ev, g = without("traces", atoms, graph)
    assert [a.atom_id for a in ev.atoms] == ["E0000000001", "E0000000003", "E0000000004"]
    assert [(e.src, e.dst) for e in g.edges] == [("a", "c"), ("b", "c")]  # traces-only edge gone
    assert g.universe == graph.universe == ev.universe  # U unchanged, external node included
    ev, g = without("metrics", atoms, graph)
    assert [a.atom_id for a in ev.atoms] == ["E0000000002", "E0000000003", "E0000000004"]
    assert len(g.edges) == 3


def test_fewer_than_two_sources_give_no_re_ranking(synth01_dir: Path) -> None:
    ctx = make_context("causentra", synth01_dir)
    inp = load_inputs(ctx, config_from(ctx.config, ctx.config.core))
    alone = Sources(metrics=True, logs=False, traces=False, events=False)
    assert present(alone) == ("metrics",)
    assert ablations(inp.ev, inp.graph, alone, inp.causatrix) == ()


def test_synth01_cpu_hog_survives_every_dropped_source(synth01_dir: Path) -> None:
    ctx = make_context("causentra", synth01_dir)
    cfg = config_from(ctx.config, ctx.config.core)
    inp = load_inputs(ctx, cfg)
    t = trial_inputs(inp, cfg)
    assert [s for s, _ in t.ablations] == list(present(inp.manifest.sources))  # one rank() per source
    assert all(sorted(order) == list(inp.graph.universe) for _, order in t.ablations)
    t9 = [r for r in run_trials("checkout", t) if r.id == "T9"]
    assert [(r.result, r.reason) for r in t9] == [("pass", None)]
