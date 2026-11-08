"""core.io: contract reads and writes (validation, orders, canonical bytes, atomicity)."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io, textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ArtifactMissing, ChainBroken, ContractValidationError
from veyltrace_core.hashing import GENESIS_HASH, self_hash, sha256_file, verify_chain

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples"
RUN_DIR_JSON = sorted(n for n, i in CONTRACTS.items() if i.kind == "json" and io.is_run_dir_contract(n))
PARQUET = sorted(n for n, i in CONTRACTS.items() if i.kind == "parquet" and io.is_run_dir_contract(n))


def _example(name: str) -> Any:
    return json.loads((EXAMPLES / f"{name}.example.json").read_bytes().decode("utf-8"))


def _table(name: str, rows: list[dict[str, Any]] | None = None) -> pa.Table:
    return pa.Table.from_pylist(_example(name) if rows is None else rows, schema=io.arrow_schema(name))


def _trace_lines() -> list[dict[str, Any]]:
    """The agent_trace example's lines without chain fields (the example is a fragment at seq 2)."""
    return [
        {k: v for k, v in line.items() if k not in ("seq", "prev_hash", "line_hash")}
        for line in _example("agent_trace")
    ]


def _leftovers(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if textio.TMP_INFIX in p.name)


# --------------------------------------------------------------------------------------------
# paths and registry


def test_path_of_follows_the_registry(tmp_path: Path) -> None:
    assert io.path_of("graph.edges", tmp_path) == tmp_path / "graph" / "edges.parquet"
    assert io.path_of("config_lock", tmp_path) == tmp_path / "config.lock.json"
    assert io.path_of("agent_trace", tmp_path) == tmp_path / "agent_trace.jsonl"
    for name in ("calibration", "answer_key", "bench_result", "predicates"):
        assert not io.is_run_dir_contract(name)
        with pytest.raises(ContractValidationError, match="not a run-directory path"):
            io.path_of(name, tmp_path)
    with pytest.raises(ContractValidationError, match="unknown contract"):
        io.path_of("nope", tmp_path)


def test_empty_table_and_arrow_schema() -> None:
    table = io.empty_table("telemetry.spans")
    assert table.num_rows == 0
    assert table.schema.metadata == {b"veyltrace.schema": b"telemetry.spans/0.1.0"}
    with pytest.raises(ContractValidationError, match="not a table contract"):
        io.arrow_schema("verdict")


def test_version_rule_before_m1() -> None:
    assert io.version_compatible("0.1.0", "0.1.0")
    assert io.version_compatible("0.1.7", "0.1.0")  # patch may differ
    assert not io.version_compatible("0.2.0", "0.1.0")
    assert not io.version_compatible("0.0.9", "0.1.0")  # older minor: only after M1
    assert not io.version_compatible("1.1.0", "0.1.0")
    assert not io.version_compatible("0.1", "0.1.0")


# --------------------------------------------------------------------------------------------
# JSON


@pytest.mark.parametrize("name", RUN_DIR_JSON)
def test_json_round_trip_is_canonical(name: str, tmp_path: Path) -> None:
    sha = io.write(name, _example(name), tmp_path)
    path = io.path_of(name, tmp_path)
    raw = path.read_bytes()
    assert sha == sha256_file(path)
    model = io.read_unredacted(name, tmp_path, validate=True)  # byte round trip: hint included
    assert isinstance(model, CONTRACTS[name].model)
    assert raw == canonical_json(model) + b"\n"
    assert io.write(name, model, tmp_path) == sha  # a model round-trips to the same bytes
    assert io.encode(name, _example(name)) == raw
    assert not _leftovers(tmp_path)


def test_schema_version_is_stamped_or_checked() -> None:
    alert = _example("alert")
    del alert["schema_version"]
    assert io.prepare("alert", alert).model_dump()["schema_version"] == CONTRACTS["alert"].version
    alert["schema_version"] = "0.1.9"
    with pytest.raises(ContractValidationError, match="schema_version"):
        io.prepare("alert", alert)


def test_json_writer_rejects_schema_and_model_violations() -> None:
    alert = _example("alert")
    with pytest.raises(ContractValidationError, match="schema violation"):
        io.prepare("alert", {**alert, "surprise": 1})
    with pytest.raises(ContractValidationError, match="expected a mapping"):
        io.prepare("alert", [alert])  # type: ignore[arg-type]  # deliberately wrong type
    with pytest.raises(ContractValidationError, match="Slate"):
        io.prepare("slate", models.Alert.model_validate(alert))


def test_int_for_a_float_field_is_rejected_not_coerced() -> None:
    slate = _example("slate")
    slate["all_scores"][-1]["fused_score"] = 0  # pydantic would turn it into 0.0
    with pytest.raises(ContractValidationError, match="model changes a value"):
        io.prepare("slate", slate)


def test_json_orders_are_validated_never_resorted() -> None:
    slate = _example("slate")
    slate["all_scores"] = list(reversed(slate["all_scores"]))
    with pytest.raises(ContractValidationError, match="break the stated order"):
        io.prepare("slate", slate)


def test_semantic_arrays_keep_producer_order(tmp_path: Path) -> None:
    verdict = _example("verdict")
    if len(verdict["ranked"]) > 1:
        # `ranked` is x-order semantic: any order is written as given (self-hash recomputed).
        verdict["ranked"] = list(reversed(verdict["ranked"]))
        verdict["verdict_hash"] = self_hash("verdict", verdict)
        io.write("verdict", verdict, tmp_path)
        back = json.loads(io.path_of("verdict", tmp_path).read_bytes())
        assert back["ranked"] == verdict["ranked"]


def test_self_hash_is_verified() -> None:
    verdict = _example("verdict")
    verdict["status"] = "INCONCLUSIVE" if verdict["status"] != "INCONCLUSIVE" else "LIKELY"
    with pytest.raises(ContractValidationError):
        io.prepare("verdict", verdict)
    card = _example("card")
    card["card_hash"] = "0" * 64
    with pytest.raises(ContractValidationError):
        io.prepare("card", card)


def test_json_reader_checks_version_and_strict_json(tmp_path: Path) -> None:
    path = io.path_of("alert", tmp_path)
    alert = _example("alert")
    textio.write_bytes(path, canonical_json({**alert, "schema_version": "0.2.0"}))
    with pytest.raises(ContractValidationError, match="schema version"):
        io.read("alert", tmp_path)
    textio.write_bytes(path, b'{"schema_version": "0.1.0", "schema_version": "0.1.0"}')
    with pytest.raises(ContractValidationError, match="duplicate key"):
        io.read("alert", tmp_path)
    textio.write_bytes(path, b'{"x": NaN}')
    with pytest.raises(ContractValidationError, match="invalid JSON"):
        io.read("alert", tmp_path)
    textio.write_bytes(path, b"\xff")
    with pytest.raises(ContractValidationError, match="not UTF-8"):
        io.read("alert", tmp_path)


def test_validate_on_read_catches_what_plain_read_accepts(tmp_path: Path) -> None:
    slate = _example("slate")
    slate["all_scores"] = list(reversed(slate["all_scores"]))
    textio.write_bytes(io.path_of("slate", tmp_path), canonical_json(slate) + b"\n")
    assert isinstance(io.read("slate", tmp_path), models.Slate)
    with pytest.raises(ContractValidationError, match="stated order"):
        io.read("slate", tmp_path, validate=True)


def test_missing_artifact(tmp_path: Path) -> None:
    assert not io.exists("slate", tmp_path)
    with pytest.raises(ArtifactMissing) as info:
        io.read("slate", tmp_path)
    assert isinstance(info.value, FileNotFoundError)


def test_typed_readers(tmp_path: Path) -> None:
    io.write("slate", _example("slate"), tmp_path)
    assert isinstance(io.read_model("slate", tmp_path, models.Slate), models.Slate)
    with pytest.raises(ContractValidationError):
        io.read_model("slate", tmp_path, models.Alert)
    io.write("graph.nodes", _table("graph.nodes"), tmp_path)
    assert io.read_table("graph.nodes", tmp_path).num_rows == len(_example("graph.nodes"))
    with pytest.raises(ContractValidationError, match="columns="):
        io.read("slate", tmp_path, columns=["x"])


def test_failed_write_leaves_the_previous_file(tmp_path: Path) -> None:
    sha = io.write("alert", _example("alert"), tmp_path)
    with pytest.raises(ContractValidationError):
        io.write("alert", {**_example("alert"), "protocol": "psychic"}, tmp_path)
    assert sha256_file(io.path_of("alert", tmp_path)) == sha
    assert not _leftovers(tmp_path)


# --------------------------------------------------------------------------------------------
# Parquet


@pytest.mark.parametrize("name", PARQUET)
def test_parquet_round_trip(name: str, tmp_path: Path) -> None:
    sha = io.write(name, _table(name), tmp_path)
    path = io.path_of(name, tmp_path)
    assert sha == sha256_file(path)
    back = io.read(name, tmp_path, validate=True)
    assert isinstance(back, pa.Table)
    assert back.schema.equals(io.arrow_schema(name), check_metadata=True)
    assert (pq.read_metadata(path).metadata or {})[b"veyltrace.schema"] == f"{name}/0.1.0".encode()
    assert sorted(map(canonical_json, back.to_pylist())) == sorted(
        map(canonical_json, _table(name).to_pylist())
    )
    assert io.write(name, _example(name), tmp_path) == sha  # rows (dicts) give the same bytes


@pytest.mark.parametrize("name", PARQUET)
@settings(max_examples=25)
@given(data=st.data())
def test_parquet_bytes_ignore_row_order_chunking_and_destination(
    name: str, data: st.DataObject, tmp_path_factory: pytest.TempPathFactory
) -> None:
    rows = _example(name)
    shuffled = data.draw(st.permutations(rows))
    table = _table(name, list(shuffled))
    chunked = (
        pa.concat_tables([table.slice(i, 1) for i in range(table.num_rows)]) if table.num_rows else table
    )
    a = io.write_path(name, _table(name), tmp_path_factory.mktemp("a") / "x.parquet")
    b = io.write_path(name, chunked, tmp_path_factory.mktemp("b") / "deep" / "other-name.parquet")
    assert a == b


def test_parquet_sort_is_total_nulls_first_utf8_bytes(tmp_path: Path) -> None:
    base = _example("telemetry.logs")[0]
    bodies = ["é", "Z", "a", "b"]
    rows = [{**base, "body": body, "trace_id": None if i == 3 else "t"} for i, body in enumerate(bodies)]
    io.write("telemetry.logs", rows, tmp_path)
    back = io.read_table("telemetry.logs", tmp_path)
    assert back.column("body").to_pylist() == ["Z", "a", "b", "é"]  # key (service, t_ns, body): bytes
    dup = [dict(base), dict(base), {**base, "trace_id": None}]
    io.write("telemetry.logs", dup, tmp_path)  # logs may repeat a key
    assert io.read_table("telemetry.logs", tmp_path).column("trace_id").to_pylist()[0] is None


def test_unique_key_duplicates_are_rejected() -> None:
    rows = _example("graph.nodes")
    with pytest.raises(ContractValidationError, match="duplicate key"):
        io.encode("graph.nodes", [rows[0], {**rows[0], "is_entry": not rows[0]["is_entry"]}])


@pytest.mark.parametrize("bad", [float("nan"), float("-inf"), float("inf")])
def test_json_non_finite_floats_are_rejected_not_nulled(bad: float) -> None:
    """NaN/inf in a nullable float (q_hat: null means +inf) or a required one (slate weights) is
    an error naming the pointer, never silently written as null."""
    verdict = _example("verdict")
    verdict["confidence"]["q_hat"] = bad
    with pytest.raises(ContractValidationError, match=r"/confidence/q_hat"):
        io.encode("verdict", verdict)
    slate = _example("slate")
    weights = slate["fusion"]["weights"]
    weights[sorted(weights)[0]] = bad
    with pytest.raises(ContractValidationError, match="NaN/inf"):
        io.prepare("slate", slate)


def test_nan_and_nulls_are_rejected() -> None:
    rows = _example("anomalies")
    with pytest.raises(ContractValidationError, match="NaN"):
        io.encode("anomalies", [{**rows[0], "score_norm": math.inf}])
    with pytest.raises(ContractValidationError, match="required"):
        io.encode("anomalies", _table("anomalies", [{**rows[0], "score": None}]))


def test_negative_zero_is_written_as_zero(tmp_path: Path) -> None:
    rows = _example("anomalies")
    io.write("anomalies", [{**rows[0], "score_norm": -0.0}], tmp_path)
    value = io.read_table("anomalies", tmp_path).column("score_norm")[0].as_py()
    assert value == 0.0 and math.copysign(1.0, value) == 1.0


def test_arrow_schema_must_match_exactly() -> None:
    table = _table("graph.nodes")
    loose = pa.Table.from_pylist(table.to_pylist())  # inferred: nullable fields, other order
    with pytest.raises(ContractValidationError, match="conform_table"):
        io.encode("graph.nodes", loose)
    assert io.encode("graph.nodes", io.conform_table("graph.nodes", loose)) == io.encode("graph.nodes", table)
    large = table.set_column(0, "node", table.column("node").cast(pa.large_string()))
    with pytest.raises(ContractValidationError, match="large_string"):
        io.encode("graph.nodes", large)
    with pytest.raises(ContractValidationError, match="keys"):
        io.encode("graph.nodes", [{**_example("graph.nodes")[0], "extra": 1}])


def test_list_columns_sort_by_canonical_json_and_validate_their_order() -> None:
    rows = _example("graph.edges")
    with pytest.raises(ContractValidationError, match="row 0"):
        io.encode("graph.edges", [{**rows[0], "provenance": ["traces", "logs"]}])


def test_parquet_reader_checks_stamp_schema_and_order(tmp_path: Path) -> None:
    path = io.path_of("graph.nodes", tmp_path)
    path.parent.mkdir(parents=True)
    table = _table("graph.nodes")
    pq.write_table(table.replace_schema_metadata({b"veyltrace.schema": b"graph.nodes/0.2.0"}), path)
    with pytest.raises(ContractValidationError, match="schema version"):
        io.read("graph.nodes", tmp_path)
    pq.write_table(table.replace_schema_metadata({b"veyltrace.schema": b"graph.edges/0.1.0"}), path)
    with pytest.raises(ContractValidationError, match=r"veyltrace\.schema"):
        io.read("graph.nodes", tmp_path)
    unsorted = table.take(list(reversed(range(table.num_rows))))
    pq.write_table(unsorted, path)
    io.read("graph.nodes", tmp_path)  # plain read trusts the writer
    if table.num_rows > 1:
        with pytest.raises(ContractValidationError, match="canonical order"):
            io.read("graph.nodes", tmp_path, validate=True)
    path.write_bytes(b"not parquet")
    with pytest.raises(ContractValidationError, match="not a readable Parquet"):
        io.read("graph.nodes", tmp_path)


def test_column_projection(tmp_path: Path) -> None:
    io.write("telemetry.metrics", _table("telemetry.metrics"), tmp_path)
    table = io.read_table("telemetry.metrics", tmp_path, columns=["t_ns", "value"])
    assert table.column_names == ["t_ns", "value"]
    with pytest.raises(ContractValidationError, match="column selection"):
        io.read("telemetry.metrics", tmp_path, columns=["nope"])


def test_empty_table_writes_and_reads(tmp_path: Path) -> None:
    sha = io.write("evidence", io.empty_table("evidence"), tmp_path)
    assert io.read_table("evidence", tmp_path, validate=True).num_rows == 0
    assert io.write("evidence", [], tmp_path) == sha


# --------------------------------------------------------------------------------------------
# CSV (bench_result)


def test_csv_round_trip_and_encoding(tmp_path: Path) -> None:
    path = tmp_path / "per_case.csv"
    sha = io.write_path("bench_result", _example("bench_result"), path)
    assert sha == sha256_file(path)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text and text.endswith("\n")
    header, first = text.split("\n")[:2]
    assert header.split(",") == io.arrow_schema("bench_result").names
    assert ",1," in first or first.endswith(",1") or ",0," in first  # booleans as 0/1
    assert "payment_latency;checkout_latency" in text  # lists ;-joined
    back = io.read_path("bench_result", path, validate=True)
    assert isinstance(back, pa.Table)
    assert sorted(map(canonical_json, back.to_pylist())) == sorted(
        map(canonical_json, _table("bench_result").to_pylist())
    )
    assert io.write_path("bench_result", back, path) == sha


def test_csv_reader_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "per_case.csv"
    io.write_path("bench_result", _example("bench_result"), path)
    lines = path.read_bytes().decode("utf-8").split("\n")
    names = io.arrow_schema("bench_result").names
    cells = lines[1].split(",")
    cells[names.index("shift_s")] = " 1"
    path.write_bytes("\n".join([lines[0], ",".join(cells), ""]).encode("utf-8"))
    with pytest.raises(ContractValidationError, match="not an integer"):
        io.read_path("bench_result", path)
    path.write_bytes(b"wrong,header\n")
    with pytest.raises(ContractValidationError, match="header"):
        io.read_path("bench_result", path)


def test_csv_refuses_ambiguous_cells() -> None:
    row = _example("bench_result")[0]
    with pytest.raises(ContractValidationError):
        io.encode("bench_result", [{**row, "ranks": ["a;b"]}])
    with pytest.raises(ContractValidationError):  # the schema forbids "" in every nullable column
        io.encode("bench_result", [{**row, "variant": ""}])


# --------------------------------------------------------------------------------------------
# JSONL (agent_trace)


def test_jsonl_writer_builds_the_hash_chain(tmp_path: Path) -> None:
    with io.JsonlWriter("agent_trace", tmp_path) as writer:
        for line in _trace_lines():
            writer.append(line)
        head = writer.head
    sha = writer.close()
    path = io.path_of("agent_trace", tmp_path)
    assert sha == sha256_file(path)
    lines = io.read_lines("agent_trace", tmp_path, models.AgentTraceLine, validate=True)
    assert [line.seq for line in lines] == list(range(len(_trace_lines())))
    assert lines[0].prev_hash == GENESIS_HASH
    assert verify_chain(lines) == head
    raw = path.read_bytes()
    assert raw == b"".join(canonical_json(line) + b"\n" for line in lines)
    assert io.write("agent_trace", [line.model_dump(mode="json") for line in lines], tmp_path) == sha
    assert not _leftovers(tmp_path)


def test_jsonl_writer_rejects_a_wrong_chain_and_aborts(tmp_path: Path) -> None:
    first, second = _trace_lines()[:2]
    with (
        pytest.raises(ContractValidationError, match="prev_hash"),
        io.JsonlWriter("agent_trace", tmp_path) as writer,
    ):
        writer.append(first)
        writer.append({**second, "prev_hash": "f" * 64})
    assert not io.exists("agent_trace", tmp_path)
    assert not _leftovers(tmp_path)
    with pytest.raises(ContractValidationError, match="seq"):
        io.write("agent_trace", [{**first, "seq": 5}], tmp_path)
    with pytest.raises(ContractValidationError, match="line_hash"):
        io.write("agent_trace", [{**first, "line_hash": "a" * 64}], tmp_path)
    with pytest.raises(ContractValidationError, match="schema violation"):
        io.write("agent_trace", [{**first, "type": "dance"}], tmp_path)


def test_empty_trace(tmp_path: Path) -> None:
    writer = io.JsonlWriter("agent_trace", tmp_path)
    assert writer.head is None
    sha = writer.close()
    assert writer.close() == sha  # idempotent
    assert io.path_of("agent_trace", tmp_path).read_bytes() == b""
    assert io.read("agent_trace", tmp_path, validate=True) == []


def test_jsonl_reader_detects_tampering_and_crlf(tmp_path: Path) -> None:
    io.write("agent_trace", _trace_lines(), tmp_path)
    path = io.path_of("agent_trace", tmp_path)
    lines = path.read_bytes().decode("utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["summary" if tampered["type"] == "tool_call" else "detail"] = None
    tampered["seq"] = 99
    path.write_bytes(("\n".join([lines[0], json.dumps(tampered), *lines[2:]]) + "\n").encode("utf-8"))
    with pytest.raises(ChainBroken):
        io.read("agent_trace", tmp_path, validate=True)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    with pytest.raises(ContractValidationError, match="LF"):
        io.read("agent_trace", tmp_path)


# --------------------------------------------------------------------------------------------
# write_text and TelemetryTables


def test_write_text_normalises_line_ends_and_guards_paths(tmp_path: Path) -> None:
    sha = io.write_text("card.md", "# Card\r\nline → two\rend\n", tmp_path)
    assert (tmp_path / "card.md").read_bytes() == "# Card\nline → two\nend\n".encode()
    assert sha == sha256_file(tmp_path / "card.md")
    for bad in ("", "../x.md", "/abs.md", "a\\b.md", "C:/x.md", "a//b.md", "./x.md"):
        with pytest.raises(ValueError, match="relative POSIX path"):
            io.write_text(bad, "x", tmp_path)
    with pytest.raises(ValueError, match=r"use io\.write"):
        io.write_text("verdict.json", "{}", tmp_path)


def test_telemetry_tables_from_run_dir(tmp_path: Path) -> None:
    io.write("telemetry.metrics", _table("telemetry.metrics"), tmp_path)
    tables = io.TelemetryTables.from_run_dir(
        tmp_path, columns={"metrics": ["t_ns", "value"], "spans": ["trace_id"]}
    )
    assert tables.metrics.column_names == ["t_ns", "value"]
    assert tables.spans.num_rows == 0 and tables.spans.column_names == ["trace_id"]
    assert tables.logs.schema.equals(io.arrow_schema("telemetry.logs"))
    with pytest.raises(ValueError, match="unknown telemetry sources"):
        io.TelemetryTables.from_run_dir(tmp_path, columns={"traces": ["x"]})


def test_telemetry_tables_from_tables() -> None:
    tables = io.TelemetryTables.from_tables(events=_table("telemetry.events"))
    assert tables.events.num_rows == len(_example("telemetry.events"))
    assert tables.metrics.num_rows == 0
    with pytest.raises(ValueError, match="unknown telemetry sources"):
        io.TelemetryTables.from_tables(traces=_table("telemetry.spans"))
    with pytest.raises(ContractValidationError, match="projection"):
        io.TelemetryTables.from_tables(metrics=_table("telemetry.spans"))
    wrong = _table("telemetry.events").select(["entity", "t_ns"])  # wrong column order
    with pytest.raises(ContractValidationError, match="projection"):
        io.TelemetryTables.from_tables(events=wrong)


def test_writer_options_are_frozen() -> None:
    with pytest.raises(TypeError):
        io.PARQUET_OPTIONS["compression"] = "snappy"  # type: ignore[index]  # read-only on purpose
    assert io.PARQUET_OPTIONS["row_group_size"] == io.ROW_GROUP_ROWS
    copy.deepcopy(dict(io.PARQUET_OPTIONS))


# --------------------------------------------------------------------------------------------
# older-minor files (the post-M1 version rule, critic gap "version rule")


def _restamp_parquet(path: Path, version: str, drop: str) -> None:
    """Rewrite a contract Parquet file as an older minor that lacks column `drop`."""
    table = pq.read_table(path).drop_columns([drop])
    meta = dict(table.schema.metadata or {})
    meta[io.SCHEMA_METADATA_KEY] = f"changes/{version}".encode()
    pq.write_table(table.replace_schema_metadata(meta), path)


def test_older_minor_parquet_reads_absent_nullable_columns_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    io.write("changes", _table("changes"), tmp_path)
    path = io.path_of("changes", tmp_path)
    _restamp_parquet(path, "0.0.0", "delta_to_onset_ms")
    with pytest.raises(ContractValidationError, match="schema version"):
        io.read("changes", tmp_path)  # before M1: exact minor only
    monkeypatch.setattr(io, "ALLOW_OLDER_MINOR", True)
    table = io.read_table("changes", tmp_path)
    assert table.schema.equals(io.arrow_schema("changes"), check_metadata=False)
    assert table.column("delta_to_onset_ms").null_count == table.num_rows
    projected = io.read_table("changes", tmp_path, columns=["delta_to_onset_ms", "entity"])
    assert projected.column_names == ["delta_to_onset_ms", "entity"]


def test_older_minor_parquet_still_rejects_missing_required_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(io, "ALLOW_OLDER_MINOR", True)
    io.write("changes", _table("changes"), tmp_path)
    path = io.path_of("changes", tmp_path)
    _restamp_parquet(path, "0.0.0", "entity")
    with pytest.raises(ContractValidationError, match="non-null columns"):
        io.read("changes", tmp_path)
    io.write("changes", _table("changes"), tmp_path)
    _restamp_parquet(path, "0.1.0", "delta_to_onset_ms")  # same minor: the schema must match exactly
    with pytest.raises(ContractValidationError, match="columns"):
        io.read("changes", tmp_path)


def test_older_minor_json_reads_absent_nullable_fields_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = _example("proposals")
    doc["mode"], doc["model"] = "external", None
    io.write("proposals", doc, tmp_path)
    older = {k: v for k, v in doc.items() if k != "model"}
    older["schema_version"] = "0.0.0"
    textio.write_bytes(io.path_of("proposals", tmp_path), canonical_json(older) + b"\n")
    with pytest.raises(ContractValidationError, match="schema version"):
        io.read("proposals", tmp_path)
    monkeypatch.setattr(io, "ALLOW_OLDER_MINOR", True)
    for validate in (False, True):
        model = io.read_model("proposals", tmp_path, models.Proposals, validate=validate)
        assert model.model is None
