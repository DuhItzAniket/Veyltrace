"""RCAEval-C in the runner (#326; 04 §5.2): per-case overlays, decoy columns and `naive-change`.

The generator itself is Observe's (bench/decoys/tests). These tests check what bench does with
it: one overlay per case under the data root, named in every method's run of that case, the
answer-key row that records which change is true, and the scored decoy columns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pytest

from veyltrace_bench import answer_keys, decoy_runs, naive_change, runner
from veyltrace_bench.experiment import OVERLAY_KEY, load_experiment, unsupported
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core import cli, io, textio
from veyltrace_core.config import data_root, resolve_config
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import case_id
from veyltrace_core.pipeline import RunSummary
from veyltrace_decoys.rcaevalc import DecoySpec, overlay_path

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "synth-smoke.yaml"
NO_FAULT = case_id("synth-05")  # RCAEval-C plants changes around an injection: fault cases only
DECOYS = "  sources_drop: []\n  decoys: {pi: 1.0, rate_per_h: 60, window_s: [-1800, 300]}\n"
NAIVE = '  - {id: "naive-change", kind: internal_baseline}\n'
OFF = '  - {id: "veyltrace:off", kind: veyltrace, ai: {mode: "off"}, overrides: {}}\n'


def _events(rows: list[tuple[int, str]]) -> pa.Table:
    columns = {
        "t_ns": [t for t, _ in rows],
        "entity": [e for _, e in rows],
        "kind": ["deploy"] * len(rows),
        "source_system": ["synthetic"] * len(rows),
        "detail_json": ["{}"] * len(rows),
        "actor": [None] * len(rows),
    }
    return pa.table(columns, schema=io.arrow_schema("telemetry.events"))


def test_naive_change_blames_the_latest_change_before_the_alert() -> None:
    events = _events([(10, "b"), (30, "carts-db"), (30, "a"), (20, "b"), (40, "cluster"), (50, "z")])
    # carts-db counts for carts; cluster is no service; z changed at t_alert = 50 (strictly before)
    assert naive_change.rank(events, 50, ["a", "b", "carts", "z"]) == ("a", "carts", "b")
    assert naive_change.rank(_events([]), 50, ["a"]) == ()  # no change: an unranked miss


def _key(decoys: list[dict[str, Any]] | None) -> AnswerKeyRow:
    return AnswerKeyRow(
        case_id="0" * 12, dataset="re2-ob", system="ob", is_no_fault=False, root_service="cart",
        root_component=None, fault_class="cpu", fault_label="cpu", indicator="cpu", mode="resource",
        t_inject_ns=10**18, t_end_ns=None, injection_json=None, extra_roots_json=None,
        decoy_changes_json=None if decoys is None else json.dumps(decoys), validated=None,
        sli_impact_json=None,
    )  # fmt: skip


def _change(entity: str, is_true: bool) -> dict[str, Any]:
    return {"t_ns": 1, "entity": entity, "kind": "deploy", "is_true": is_true}


def test_decoy_columns_follow_04_7() -> None:
    def cols(decoys: list[dict[str, Any]] | None, ranks: tuple[str, ...]) -> tuple[bool | None, ...]:
        got = decoy_runs.decoy_columns(_key(decoys), ranks)
        return got["decoy_present"], got["decoy_ranked_first"]

    assert cols(None, ("cart",)) == (None, None)  # no planted changes: not evaluated
    assert cols([_change("cart", True)], ("cart",)) == (False, None)  # the true change is no decoy
    decoy = [_change("cart", True), _change("ads-db", False)]
    assert cols(decoy, ("ads_cpu", "cart")) == (True, True)  # ads-db counts for ads
    assert cols(decoy, ("cart_cpu", "ads")) == (True, False)
    assert cols(decoy, ()) == (True, False)  # a miss never ranks the decoy first


def test_prepare_case_writes_the_overlay_and_records_which_change_is_true() -> None:
    spec = DecoySpec(pi=1.0, rate_per_h=60)
    got = decoy_runs.prepare_case("rcaevalc-x", _key(None), spec, ["ads", "cart", "pay"], data_root())
    assert got.overlay == f"overlays/rcaevalc-x/{'0' * 12}/events.parquet"
    written = io.read_path("telemetry.events", overlay_path("rcaevalc-x", "0" * 12), validate=True)
    assert isinstance(written, pa.Table) and written.num_rows > 1
    truth = json.loads(got.key.decoy_changes_json or "[]")
    assert len(truth) == written.num_rows and [r["entity"] for r in truth if r["is_true"]] == ["cart"]
    no_root = _key(None).model_copy(update={"root_service": None})
    with pytest.raises(ConfigError, match="no root_service"):
        decoy_runs.prepare_case("rcaevalc-x", no_root, spec, ["cart"], data_root())


def test_the_protocol_block_owns_the_overlay_key(tmp_path: Path) -> None:
    assert decoy_runs.decoy_spec(None) is None
    with pytest.raises(ConfigError, match=r"decoys\.pi must be in"):
        decoy_runs.decoy_spec({"pi": 2.0, "rate_per_h": 1})
    path = tmp_path / "exp.yaml"
    over = '  - {id: "veyltrace:off", kind: veyltrace, overrides: {' + OVERLAY_KEY + ": x}}\n"
    path.write_text(textio.read_text(SMOKE).replace(OFF, over), encoding="utf-8")
    with pytest.raises(ConfigError, match="set them in `protocol`"):
        load_experiment(path)


def _decoy_experiment(tmp_path: Path, *, naive: bool = False) -> Path:
    exclude, path = tmp_path / "no_fault.yaml", tmp_path / "exp.yaml"
    exclude.write_text(f"[{NO_FAULT}]\n", encoding="utf-8")
    text = textio.read_text(SMOKE).replace("  sources_drop: []\n", DECOYS)
    text = text.replace("exclude: null", f"exclude: {json.dumps(exclude.as_posix())}")
    path.write_text(text.replace(OFF, OFF + (NAIVE if naive else "")), encoding="utf-8")
    assert unsupported(load_experiment(path)) == []
    return path


def test_every_run_of_a_case_names_that_cases_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    named: list[str | None] = []
    real = resolve_config

    def resolve(overrides: dict[str, object], **kw: Any) -> Any:  # records each run's overlay
        named.append(cast("str | None", overrides.get(OVERLAY_KEY)))
        return real(overrides, **kw)

    def fake_run_case(dataset: str, case: str, ai_mode: str, **_: object) -> RunSummary:
        return RunSummary(dataset, case, "0" * 16, tmp_path, "failed", "x", None, (), (), {})

    monkeypatch.setattr(runner, "IN_PROCESS", True)  # the fake run_case lives in this process
    monkeypatch.setattr(runner, "run_case", fake_run_case)
    monkeypatch.setattr(runner, "resolve_config", resolve)
    monkeypatch.setattr(runner, "case_services", lambda key, cfg, root: [key.root_service, "x", "y"])
    exp = _decoy_experiment(tmp_path)
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "r", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    rows = {str(r["case_id"]): r for r in table.to_pylist()}
    want = {c: f"overlays/{out.name}/{c}/events.parquet" for c in rows}
    assert sorted(rows) == sorted(case_id(f"synth-0{i}") for i in range(1, 5))
    assert sorted(n for n in named if n is not None) == sorted(want.values())  # one per case's run
    assert all((data_root() / p).is_file() for p in want.values())
    assert all((r["decoy_present"], r["decoy_ranked_first"]) == (True, False) for r in rows.values())


def test_rcaeval_c_runs_end_to_end_on_synth(tmp_path: Path) -> None:
    assert cli.main(["data", "fetch", "synth"]) == 0
    exp = _decoy_experiment(tmp_path, naive=True)
    out, _ = runner.run_experiment(exp, out_root=tmp_path / "r", runs_root=tmp_path / "runs")
    table = io.read_path("bench_result", out / "per_case.csv", validate=True)
    assert isinstance(table, pa.Table)
    keys = answer_keys.load_answer_keys("synth")
    for row in table.to_pylist():
        assert row["run_outcome"] == "ok" and row["decoy_present"] is True, row
        cid = str(row["case_id"])
        overlay = io.read_path("telemetry.events", overlay_path(out.name, cid), validate=True)
        assert isinstance(overlay, pa.Table)
        entities = set(overlay.column("entity").to_pylist())
        assert keys[cid].root_service in entities  # pi = 1: the true change on the root
        if row["method"] == naive_change.METHOD:  # it ranks changed services only, from the overlay
            assert row["ranks"] and set(row["ranks"]) <= entities
