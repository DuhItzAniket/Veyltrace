"""Golden tests of Anomara's run() on hand-made inputs (03-anomara §3, §7; R-06 pattern).

Synth's signal_cube stays empty until Signalyth (O-02) lands, so the detectors and onsets are pinned
here. `fixtures/handmade/<case>/inputs.json` holds the inputs (contract name -> rows, plus a compact
`series` spec expanded below; "_" keys are comments); every input is written through io.write, so it
is contract-valid on every run. `anomalies.txt` and `onsets.txt` are the expected outputs' canonical
content (what assert_golden compares, D-16). Refresh after review:
`VEYLTRACE_UPDATE_HANDMADE=1 uv run pytest packages/anomara/tests/test_handmade.py`.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from veyltrace_anomara.api import DETECTORS, run
from veyltrace_core import io, textio
from veyltrace_core.testing import content_lines, make_context

HANDMADE = Path(__file__).resolve().parents[1] / "fixtures" / "handmade"
CASES = tuple(sorted(p.name for p in HANDMADE.iterdir() if p.is_dir()))
GOLDEN = {"anomalies": "anomalies.txt", "onsets": "onsets.txt"}
UPDATE_ENV = "VEYLTRACE_UPDATE_HANDMADE"
NS = 1_000_000_000


def _expand(spec: dict[str, Any], start_ns: int) -> list[dict[str, Any]]:
    """signal_cube.series rows of one compact series spec (see inputs.json `_comment`)."""
    service, component, signal, source = str(spec["id"]).split("|")
    rows: list[dict[str, Any]] = []
    offset = 0
    for until, values in spec["segments"]:
        k = 0
        while offset < until:
            value = values[k % len(values)]
            if value is not None:
                rows.append(
                    {"series_id": spec["id"], "service": service, "component": component, "signal": signal,
                     "family": spec["family"], "klass": spec["klass"], "source": source, "unit": spec["unit"],
                     "t_ns": start_ns + offset * NS, "value": float(value)}
                )  # fmt: skip
            offset += int(spec["step_s"])
            k += 1
    return rows


def _run_dir(case: str, tmp_path: Path) -> Path:
    inputs = json.loads((HANDMADE / case / "inputs.json").read_text(encoding="utf-8"))
    start = int(inputs["case_manifest"]["data_start_ns"])
    for name in sorted(n for n in inputs if not n.startswith("_") and n != "series"):
        io.write(name, inputs[name], tmp_path)
    io.write("signal_cube.series", [r for spec in inputs["series"] for r in _expand(spec, start)], tmp_path)
    return tmp_path


@pytest.fixture
def handmade_dir(tmp_path: Path) -> Path:
    return _run_dir("anomara-run", tmp_path)


@pytest.mark.parametrize("case", CASES)
def test_outputs_match_the_handmade_golden(tmp_path: Path, case: str) -> None:
    run_dir = _run_dir(case, tmp_path)
    assert run(make_context("anomara", run_dir, dataset="handmade")).status == "ok"
    for contract, name in GOLDEN.items():
        actual = content_lines(contract, io.path_of(contract, run_dir))
        golden = HANDMADE / case / name
        if os.environ.get(UPDATE_ENV) == "1":
            assert not os.environ.get("CI"), "hand-made goldens are refreshed locally and reviewed"
            textio.write_bytes(golden, "".join(f"{line}\n" for line in actual).encode("utf-8"))
        assert golden.read_text(encoding="utf-8").splitlines() == actual


def _anomalies(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = io.read_table("anomalies", run_dir, validate=True).to_pylist()
    return {(str(r["series_id"]), str(r["detector"])): r for r in rows}


def test_one_row_per_series_and_detector_even_below_threshold(handmade_dir: Path) -> None:
    run(make_context("anomara", handmade_dir, dataset="handmade"))
    rows = _anomalies(handmade_dir)
    series = {sid for sid, _ in rows}
    assert len(series) == 7 and len(rows) == 7 * len(DETECTORS)
    robust = [r for (_, d), r in rows.items() if d == "robust_z"]
    assert all(r["score_norm"] == math.log1p(r["score"]) for r in robust)


def test_the_story_of_the_handmade_case(handmade_dir: Path) -> None:
    run(make_context("anomara", handmade_dir, dataset="handmade"))
    rows = _anomalies(handmade_dir)
    onsets = json.loads(io.path_of("onsets", handmade_dir).read_text(encoding="utf-8"))
    t0 = 1_767_225_600 * NS
    per = {p["service"]: p for p in onsets["per_service"]}
    assert rows["checkout|checkout|cpu|metrics", "robust_z"]["onset_ns"] == t0 + 1320 * NS
    assert rows["payment|payment|error_rate|traces", "robust_z"]["above_threshold"] is False  # one spike
    assert rows["cart|cart|rps|traces", "silence"]["above_threshold"] is True
    assert rows["checkout|checkout|mem|metrics", "silence"]["onset_ns"] == t0 + 1500 * NS
    assert per["cart"]["silent"] and not per["payment"]["silent"]
    assert per["checkout"]["internal_onset_ns"] == t0 + 1320 * NS
    assert per["checkout"]["internal_onset_source"] == "metrics"
    # BOCPD moves the latency onset back to the start of the ramp (03-anomara §3.6).
    assert (
        per["checkout"]["external_onset_ns"]
        < rows["checkout|checkout|latency_p99|traces", "robust_z"]["onset_ns"]
    )
    assert (onsets["method"], onsets["entry_services"]) == ("second_external", ["frontend"])
    externals = sorted(p["external_onset_ns"] for p in per.values() if p["external_onset_ns"] is not None)
    assert onsets["t_onset_ns"] == externals[1]


def test_detected_protocol_copies_the_entry_set_and_records_the_breach(handmade_dir: Path) -> None:
    alert = json.loads(io.path_of("alert", handmade_dir).read_text(encoding="utf-8"))
    shifted = alert["t_alert_ns"] + 60 * NS
    detector = {"entry_services": ["checkout"], "signal": "latency_p99", "threshold": 3.0}
    io.write("alert", alert | {"protocol": "detected", "t_alert_ns": shifted, "shift_ns": 60 * NS,
                               "detector": detector}, handmade_dir)  # fmt: skip
    run(make_context("anomara", handmade_dir, dataset="handmade"))
    onsets = json.loads(io.path_of("onsets", handmade_dir).read_text(encoding="utf-8"))
    # 03-anomara §2: copy alert.detector's entry set (never recompute it); breach = t_alert - shift.
    assert (onsets["entry_services"], onsets["slo_breach_ns"]) == (["checkout"], alert["t_alert_ns"])
