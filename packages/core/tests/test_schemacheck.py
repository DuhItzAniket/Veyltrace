"""schemacheck: JSON Schema validation, x-sort/x-order orders, vectorised table rows.

The vectorised evaluator is pinned against jsonschema itself (differential property test), so
"vectorised" never means "weaker".
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts.registry import CONTRACTS, SCHEMA_NAMES
from veyltrace_core import schemacheck
from veyltrace_core.errors import ContractValidationError

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples"
TABLES = sorted(n for n, i in CONTRACTS.items() if i.kind in ("parquet", "csv"))


def _example(name: str) -> Any:
    return json.loads((EXAMPLES / f"{name}.example.json").read_bytes().decode("utf-8"))


def _example_table(name: str) -> pa.Table:
    schema = CONTRACTS[name].arrow_schema
    assert schema is not None
    return pa.Table.from_pylist(_example(name), schema=schema)


def _nodes(node: object, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    if isinstance(node, dict):
        typed = cast("dict[str, Any]", node)
        yield path, typed
        for key, value in typed.items():
            yield from _nodes(value, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(cast("list[object]", node)):
            yield from _nodes(value, (*path, str(i)))


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_schema_is_a_valid_2020_12_schema(name: str) -> None:
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(dict(schemacheck.contract_schema(name)))


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_x_sort_rules_parse_and_sit_where_the_walker_looks(name: str) -> None:
    for path, node in _nodes(schemacheck.contract_schema(name)):
        if "x-sort" in node:
            # check_orders does not descend into conditional or negated subschemas.
            assert not {"if", "then", "else", "not"} & set(path), path
            rules = schemacheck.parse_sort_rules(name, node["x-sort"], "/".join(path))
            for rule in rules:
                if rule.order == "enum":
                    assert schemacheck.enum_values(name, node.get("items", {}), name, rule.pointer)
        if "x-order" in node:
            assert node["x-order"] == schemacheck.X_ORDER_SEMANTIC


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [{"pointer": "a", "order": "up"}],
        [{"pointer": "a", "order": "asc", "nulls": "middle"}],
        [{"pointer": "a", "order": "asc", "round": -1}],
        [{"pointer": "a", "order": "asc", "extra": 1}],
        [{"order": "asc"}],
    ],
)
def test_malformed_x_sort_is_a_schema_error(raw: object) -> None:
    with pytest.raises(ContractValidationError, match="x-sort"):
        schemacheck.parse_sort_rules("slate", raw, "/x")


def test_examples_satisfy_schema_and_orders() -> None:
    for name, info in sorted(CONTRACTS.items()):
        path = EXAMPLES / f"{name}.example.json"
        if not path.exists():
            continue
        data = _example(name)
        for item in data if info.kind != "json" else [data]:
            schemacheck.validate_json_schema(name, item)
            schemacheck.check_orders(name, item)


def test_schema_violation_names_the_path() -> None:
    alert = _example("alert")
    alert["protocol"] = "psychic"
    with pytest.raises(ContractValidationError, match="at /protocol"):
        schemacheck.validate_json_schema("alert", alert)


def test_trials_use_enum_order_not_byte_order() -> None:
    verdict = _example("verdict")
    trials = verdict["ranked"][0]["trials"]
    ids = [t["id"] for t in trials]
    assert ids == sorted(ids, key=lambda t: int(t[1:]))  # example is in numeric order
    schemacheck.check_orders("verdict", verdict)
    swapped = copy.deepcopy(verdict)
    swapped["ranked"][0]["trials"] = list(reversed(trials))
    if len(trials) > 1:
        with pytest.raises(ContractValidationError, match="break the stated order"):
            schemacheck.check_orders("verdict", swapped)


def test_enum_order_puts_t2_before_t10() -> None:
    node = {"type": "array", "items": {"$ref": "common.schema.json#/$defs/trial_id"}}
    node["x-sort"] = [{"pointer": ".", "order": "enum"}]
    schemacheck.check_list_order("proposals", node, "proposals", ["T1", "T2", "T10"], "/t")
    with pytest.raises(ContractValidationError):
        schemacheck.check_list_order("proposals", node, "proposals", ["T1", "T10", "T2"], "/t")


def test_desc_with_round_allows_near_ties_in_producer_order() -> None:
    slate = _example("slate")
    scores = slate["all_scores"]
    tie = [
        {"service": "a", "fused_score": 0.5000000001},
        {"service": "b", "fused_score": 0.5000000002},  # equal after round(·, 9): service decides
    ]
    slate["all_scores"] = tie + [s for s in scores if s["fused_score"] < 0.5]
    schemacheck.check_orders("slate", slate)
    slate["all_scores"] = list(reversed(tie))
    with pytest.raises(ContractValidationError, match="all_scores"):
        schemacheck.check_orders("slate", slate)


def test_nulls_first_by_default() -> None:
    node: dict[str, Any] = {"x-sort": [{"pointer": "service", "order": "asc"}], "items": {}}
    schemacheck.check_list_order("alignment", node, "alignment", [{"service": None}, {"service": "a"}], "")
    with pytest.raises(ContractValidationError):
        schemacheck.check_list_order(
            "alignment", node, "alignment", [{"service": "a"}, {"service": None}], ""
        )
    node["x-sort"] = [{"pointer": "service", "order": "desc", "nulls": "last"}]
    schemacheck.check_list_order("alignment", node, "alignment", [{"service": "b"}, {"service": None}], "")


def test_strings_compare_by_utf8_bytes() -> None:
    node: dict[str, Any] = {"x-sort": [{"pointer": ".", "order": "asc"}], "items": {}}
    schemacheck.check_list_order("slate", node, "slate", ["Z", "a", "é"], "")
    with pytest.raises(ContractValidationError):
        schemacheck.check_list_order("slate", node, "slate", ["é", "z"], "")


def test_unresolvable_ref_is_an_error() -> None:
    lookup = schemacheck._lookup  # pyright: ignore[reportPrivateUsage]
    assert lookup("common.schema.json#/$defs/case_id", "slate")[1] == "common"
    for ref in ("nowhere.schema.json#/a", "#/$defs/missing", "common.schema.json#/$defs/nope"):
        with pytest.raises(ContractValidationError, match="unresolvable"):
            lookup(ref, "slate")


@pytest.mark.parametrize("name", TABLES)
def test_vectorised_evaluator_covers_every_table_schema(name: str) -> None:
    table = _example_table(name)
    for batch in table.to_batches():
        mask = schemacheck._row_mask(  # pyright: ignore[reportPrivateUsage]
            schemacheck.contract_schema(name), name, batch, name
        )
        assert mask.all()


def _candidates(field: pa.Field) -> st.SearchStrategy[object]:
    """Values of the column's Arrow type: valid-looking ones and boundary breakers."""
    dtype = field.type
    words = st.sampled_from(
        [
            "checkout",
            "cart",
            "Bad_Name",
            "",
            "a|b|c|d",
            "a|b",
            "E0123456789",
            "C0123456789",
            "T01234567",
            "faultloom@0.1.0",
            "faultloom@",
            "{}",
            '{"a":1}',
            "x\n",
            "metrics",
            "traces",
            "incident",
            "deploy",
            "ok",
            "error",
            "cpu",
            "engine",
            "claim_check",
            "zscore_above",
            "service",
            "k8s",
            "prom",
            "INFO",
            "é",
        ]
    )
    if pa.types.is_string(dtype):
        base: st.SearchStrategy[object] = words
    elif pa.types.is_integer(dtype):
        base = st.integers(min_value=-3, max_value=2**31 - 1)
    elif pa.types.is_floating(dtype):
        base = st.floats(allow_nan=False, allow_infinity=False, min_value=-2.0, max_value=2.0)
    elif pa.types.is_boolean(dtype):
        base = st.booleans()
    else:
        base = st.lists(words, max_size=3)
    return st.one_of(st.none(), base)


@pytest.mark.parametrize("name", TABLES)
@given(data=st.data())
def test_vectorised_rows_agree_with_jsonschema(name: str, data: st.DataObject) -> None:
    """Mutate one or two cells of example rows; the vectorised mask equals jsonschema's verdict."""
    schema = CONTRACTS[name].arrow_schema
    assert schema is not None
    rows = [dict(r) for r in _example(name)]
    for row in rows:
        for column in data.draw(st.lists(st.sampled_from(schema.names), max_size=2)):
            row[column] = data.draw(_candidates(schema.field(column)))
    table = pa.Table.from_pylist(rows, schema=schema)
    mask = schemacheck._row_mask(  # pyright: ignore[reportPrivateUsage]
        schemacheck.contract_schema(name), name, table.to_batches()[0], name
    )
    validator = schemacheck._validator(name)  # pyright: ignore[reportPrivateUsage]
    for i, row in enumerate(table.to_pylist()):
        ok = bool(validator.is_valid(row))
        if ok:
            try:
                schemacheck.check_orders(name, row)
            except ContractValidationError:
                ok = False
        assert bool(mask[i]) == ok, (i, row)


def test_check_table_rows_reports_the_failing_row_via_jsonschema() -> None:
    rows = _example("graph.nodes")
    rows[1]["kind"] = "spaceship"
    table = pa.Table.from_pylist(rows, schema=CONTRACTS["graph.nodes"].arrow_schema)
    with pytest.raises(ContractValidationError, match=r"row 1: .*at /kind"):
        schemacheck.check_table_rows("graph.nodes", table)


def test_list_column_order_is_validated_not_resorted() -> None:
    rows = _example("graph.edges")
    rows[0]["provenance"] = ["traces", "logs"]  # not ascending
    table = pa.Table.from_pylist(rows, schema=CONTRACTS["graph.edges"].arrow_schema)
    with pytest.raises(ContractValidationError, match="row 0"):
        schemacheck.check_table_rows("graph.edges", table)


def test_nan_is_not_a_json_number_in_the_vectorised_check() -> None:
    rows = _example("anomalies")
    rows[0]["score_norm"] = math.nan
    table = pa.Table.from_pylist(rows, schema=CONTRACTS["anomalies"].arrow_schema)
    batch = table.to_batches()[0]
    mask = schemacheck._row_mask(  # pyright: ignore[reportPrivateUsage]
        schemacheck.contract_schema("anomalies"), "anomalies", batch, "anomalies"
    )
    assert not mask[0] and bool(np.all(mask[1:]))


def test_unknown_keyword_falls_back_to_row_by_row(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = dict(schemacheck.contract_schema("graph.nodes"))
    schema["propertyNames"] = {"pattern": "^[a-z_]+$"}  # not vectorised
    original = schemacheck.contract_schema
    monkeypatch.setattr(
        schemacheck, "contract_schema", lambda n: schema if n == "graph.nodes" else original(n)
    )
    with pytest.raises(schemacheck._Unsupported):  # pyright: ignore[reportPrivateUsage]
        schemacheck._row_mask(
            schema, "graph.nodes", _example_table("graph.nodes").to_batches()[0], "graph.nodes"
        )  # pyright: ignore[reportPrivateUsage]
    schemacheck.check_table_rows("graph.nodes", _example_table("graph.nodes"))  # fallback passes
