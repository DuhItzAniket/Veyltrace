"""Golden tests of the Causatrix step on every committed fixture case (07 §7).

Each case runs the engine on `fixture_run_dir(case, through="faultloom")` with the variant's
overrides and AI mode, as `update_golden` would, and compares the slate with
`packages/causatrix/fixtures/<case>/slate.json`. A case whose upstream fixtures are not committed
yet (e.g. synth-01@detected before Anomara's alert detector exists) is skipped, as update_golden
does; a missing slate fixture for a case whose inputs exist fails in assert_golden. While the synth
evidence is empty (Anomara is a stub), every ranker abstains and every synth slate is empty.

A second test checks the slate against its upstream fixtures alone (U from the golden
case_manifest and graph.nodes), so the wiring is pinned even before the slate fixtures are
regenerated.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from veyltrace_causatrix import api
from veyltrace_causatrix.config import config_from
from veyltrace_causatrix.views import universe
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.testing import (
    SYNTH_CASES,
    VARIANTS,
    assert_golden,
    fixture_run_dir,
    golden,
    make_context,
)

CASES = (*SYNTH_CASES, *sorted(VARIANTS))


def _run(case: str, tmp_path: Path) -> Path:
    try:
        run_dir = fixture_run_dir(case, tmp_path, through="faultloom")
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")
    variant = VARIANTS.get(case)
    ctx = make_context(
        "causatrix",
        run_dir,
        ai_mode=variant.ai_mode if variant is not None else "off",
        overrides=variant.overrides if variant is not None else {},
    )
    result = api.run(ctx)
    assert result.status == "ok", result.notes
    return run_dir


@pytest.mark.parametrize("case", CASES)
def test_slate_matches_golden(case: str, tmp_path: Path) -> None:
    run_dir = _run(case, tmp_path)
    assert_golden(io.read("slate", run_dir), "slate", case)


@pytest.mark.parametrize("case", CASES)
def test_slate_lists_the_universe_of_its_upstream_fixtures(case: str, tmp_path: Path) -> None:
    run_dir = _run(case, tmp_path)
    slate = io.read_model("slate", run_dir, models.Slate, validate=True)
    manifest = golden("case_manifest", case)
    assert isinstance(manifest, models.CaseManifest)
    node_table = golden("graph.nodes", case)
    assert isinstance(node_table, pa.Table)
    nodes = node_table.to_pylist()
    ctx = make_context("causatrix", run_dir)
    settings = config_from(ctx.config, ctx.config.core)
    members = universe(
        manifest.services,
        [(str(n["node"]), str(n["kind"])) for n in nodes],
        include_external=settings.include_external,
    )
    assert slate.case_id == manifest.case_id
    assert sorted(s.service for s in slate.all_scores) == sorted(members)
    picked = [c.service for c in slate.candidates]
    assert len(picked) == len(set(picked)) and set(picked) <= set(members)
    # 07 §3.1: no ranker voted -> empty slate; otherwise the top min(K, |U|) services.
    assert len(picked) == (min(slate.k, len(members)) if slate.rankers_active else 0)
    assert set(slate.rankers_active) <= set(settings.rankers)
