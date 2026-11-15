"""The CI test on the synth golden fixtures (05-causalith §7 "Golden": results recorded per service).

Until Signalyth (O-02) fills `signal_cube.series` on synth, every service is untestable
(`no_target`); the record then changes, and synth-01's CPU-hog service must come out independent
of its callees. Refresh after review: `VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest <this file>`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pytest

from veyltrace_causalith.ci import CIConfig, intervention_test
from veyltrace_contracts.models import Alert
from veyltrace_core import io, textio
from veyltrace_core.config import load_section_file
from veyltrace_core.testing import SYNTH_CASES, fixture_dir

RECORD = Path(__file__).resolve().parents[1] / "fixtures" / "handmade" / "ci-synth.json"
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"
CFG = CIConfig.from_sections(load_section_file("causalith"), load_section_file("anomara"))


def _results(case: str) -> dict[str, Any]:
    series = io.read_table("signal_cube.series", fixture_dir("signalyth", case))
    edges = io.read_table("graph.edges", fixture_dir("causalith", case))
    alert = cast("Alert", io.read("alert", fixture_dir("core", case)))
    services = sorted(cast("Any", io.read("case_manifest", fixture_dir("infralume", case))).services)
    out: dict[str, Any] = {}
    for service in services:
        result = asdict(intervention_test(series, edges, alert, service, CFG))
        out[service] = {
            k: result[k] for k in ("independent_of_parents", "reason", "parents", "target_series_id")
        }
    return out


def test_ci_results_are_recorded_for_every_synth_service() -> None:
    actual = {case: _results(case) for case in SYNTH_CASES}
    if os.environ.get(UPDATE_ENV) == "1":
        assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
        textio.write_bytes(RECORD, (json.dumps(actual, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    assert json.loads(RECORD.read_text(encoding="utf-8")) == json.loads(json.dumps(actual))


def test_synth_01_cpu_hog_latency_is_not_explained_by_its_callees() -> None:
    if io.read_table("signal_cube.series", fixture_dir("signalyth", "synth-01")).num_rows == 0:
        pytest.skip("synth signal_cube.series is empty until Signalyth (O-02) lands")
    results = _results("synth-01")
    assert any(r["independent_of_parents"] is True for r in results.values())
