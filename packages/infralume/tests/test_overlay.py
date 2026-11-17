"""The events overlay hook (01 §3.10, O-09): merged at materialise, never trusted, never under bench/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.config import data_root
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.testing import make_context
from veyltrace_infralume.api import run

EVENTS = "telemetry.events"
KEY = "infralume.events.overlay_path"
REL = "overlays/exp-1/case/events.parquet"
RE2 = "re2ob_cartservice_cpu_1"  # the Hugging Face tree of conftest.py: no events of its own
Row = tuple[int, str, str, str, str, str | None]  # t_ns, entity, kind, source_system, detail_json, actor


def _write(rows: list[Row], rel: str = REL) -> Path:
    cols = list(zip(*rows, strict=True)) if rows else [[]] * 6
    table = pa.table(
        dict(zip(io.arrow_schema(EVENTS).names, cols, strict=True)), schema=io.arrow_schema(EVENTS)
    )
    path = data_root() / rel
    io.write_path(EVENTS, table, path)
    return path


def _run(
    run_dir: Path, case: str = "synth-04", dataset: str = "synth", **overrides: Any
) -> models.CaseManifest:
    ctx = make_context("infralume", run_dir, case_id=make_case_id(case), dataset=dataset, overrides=overrides)
    assert run(ctx).status == "ok"
    manifest = io.read_unredacted("case_manifest", run_dir)
    assert isinstance(manifest, models.CaseManifest)
    return manifest


def _events(run_dir: Path) -> list[dict[str, Any]]:
    return io.read_table(EVENTS, run_dir).to_pylist()


def test_overlay_rows_join_the_case_events_as_synthetic(tmp_path: Path) -> None:
    base = _run(tmp_path / "base")
    own = _events(tmp_path / "base")
    late = base.data_end_ns + 5
    path = _write(
        [
            (late, "cart", "deploy", "k8s", "{}", "ci"),
            (base.data_start_ns, "catalog", "flag", "git", "{}", None),
        ]
    )
    manifest = _run(tmp_path / "with", **{KEY: REL})
    merged = _events(tmp_path / "with")
    extra = [r for r in merged if r not in own]
    assert len(merged) == len(own) + 2 and all(r in merged for r in own)  # the case's rows are untouched
    assert [(r["t_ns"], r["entity"], r["kind"]) for r in extra] == [
        (base.data_start_ns, "catalog", "flag"),
        (late, "cart", "deploy"),
    ]
    assert {(r["source_system"], r["actor"]) for r in extra} == {("synthetic", None)}
    assert manifest.data_end_ns == late  # 03 §2.1: the span includes overlay events
    assert manifest.services == base.services  # event entities are not telemetry services
    entry = next(i for i in manifest.inputs if i.name == "overlay/events.parquet")
    assert (entry.sha256, entry.bytes) == (sha256_file(path), path.stat().st_size)
    assert [i.name for i in manifest.inputs] == sorted(i.name for i in manifest.inputs)
    assert [i for i in manifest.inputs if i != entry] == list(base.inputs)


def test_same_overlay_gives_the_same_bytes(tmp_path: Path) -> None:
    _write([(1_700_000_000_000_000_000, "cart", "deploy", "synthetic", "{}", None)])
    written = []
    for name in ("a", "b"):
        _run(tmp_path / name, **{KEY: REL})
        written.append([io.path_of(c, tmp_path / name).read_bytes() for c in ("case_manifest", EVENTS)])
    assert written[0] == written[1]


def test_overlay_gives_events_to_a_case_without_any(tmp_path: Path, hf_case: Path) -> None:
    assert not _run(tmp_path / "base", RE2, "re2-ob").sources.events
    t = _run(tmp_path / "base", RE2, "re2-ob").data_start_ns
    _write(
        [
            (t, "frontendservice", "deploy", "synthetic", "{}", None),  # the ob alias
            (t, "cartservice", "config", "synthetic", json.dumps({"fault.id": "x", "key": "A"}), None),
            (t, "frontend", "flag", "synthetic", json.dumps({"flag": "cartFailure"}), None),
            (t, "flagd", "flag", "synthetic", "{}", None),  # fault-tool service: dropped
            (t, "istio-proxy", "deploy", "synthetic", "{}", None),  # sidecar: dropped
            (t, "frontend", "deploy", "synthetic", json.dumps({"kind": "PodChaos"}), None),  # chaos: dropped
        ]
    )
    base = _run(tmp_path / "plain", RE2, "re2-ob")
    manifest = _run(tmp_path / "with", RE2, "re2-ob", **{KEY: REL})
    rows = _events(tmp_path / "with")
    assert manifest.sources.events and manifest.services == base.services
    assert sorted((r["entity"], r["kind"]) for r in rows) == [
        ("cartservice", "config"),
        ("frontend", "deploy"),
        ("frontend", "flag"),
    ]
    details = {r["kind"]: json.loads(r["detail_json"]) for r in rows}
    assert details["config"] == {"key": "A"}  # the deny-listed key is gone
    assert details["flag"]["flag"] != "cartFailure" and len(details["flag"]["flag"]) == 8  # hashed
    assert manifest.scrub.dropped_attributes == base.scrub.dropped_attributes + 1
    assert manifest.scrub.dropped_rows == base.scrub.dropped_rows + 3


def test_dropping_events_drops_the_overlay_too(tmp_path: Path) -> None:
    _write([(1_700_000_000_000_000_000, "cart", "deploy", "synthetic", "{}", None)])
    manifest = _run(tmp_path, **{KEY: REL, "infralume.sources.drop": ["events"]})
    assert not manifest.sources.events and _events(tmp_path) == []
    assert all(not i.name.startswith(("overlay/", "events/")) for i in manifest.inputs)


def test_an_empty_overlay_changes_only_the_inputs(tmp_path: Path) -> None:
    base = _run(tmp_path / "base")
    _write([])
    manifest = _run(tmp_path / "with", **{KEY: REL})
    assert _events(tmp_path / "with") == _events(tmp_path / "base")
    assert [i.name for i in manifest.inputs if i not in base.inputs] == ["overlay/events.parquet"]
    assert manifest.model_copy(update={"inputs": base.inputs}) == base


def test_bad_overlays_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no file"):
        _run(tmp_path / "missing", **{KEY: REL})
    (data_root() / "overlays").mkdir(parents=True, exist_ok=True)
    (data_root() / "overlays" / "junk.parquet").write_bytes(b"not parquet")
    with pytest.raises(ConfigError, match="not a telemetry\\.events file"):
        _run(tmp_path / "junk", **{KEY: "overlays/junk.parquet"})
    logs = make_context("infralume", tmp_path / "logs", case_id=make_case_id("synth-04"))
    assert run(logs).status == "ok"  # a valid Parquet file of another contract
    (data_root() / "overlays" / "logs.parquet").write_bytes(
        io.path_of("telemetry.logs", tmp_path / "logs").read_bytes()
    )
    with pytest.raises(ConfigError, match="not a telemetry\\.events file"):
        _run(tmp_path / "wrong", **{KEY: "overlays/logs.parquet"})
    for outside in ("/tmp/events.parquet", "../events.parquet", "~/events.parquet"):
        with pytest.raises(ConfigError):
            _run(tmp_path / "outside", **{KEY: outside})
