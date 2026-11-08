"""Contract schema checks behind core.io: JSON Schema validation, stated array orders, table rows.

The JSON Schemas in contracts/schemas are the source of truth (03 §1); the generated Pydantic
models and Arrow schemas are derived from them. This module applies the schemas themselves:

- `validate_json_schema`: full JSON Schema 2020-12 validation of one JSON document (or one JSONL
  line, or one table row) with `jsonschema`, resolving `common.schema.json` references through an
  in-memory `referencing` registry, so nothing is ever fetched (03 §1: the `$id` URL is an
  identifier only).
- `check_orders`: the `x-sort` rules (CONVENTIONS §3.4; M0 lead decision 2026-11-06 §2.7). Writers
  *validate* a stated order and never re-sort it, because the producer's tie-break is part of the
  domain (verdict.candidate_set: v desc, ties in ranked order). `order: "enum"` compares by
  position in the field's enum (trial ids T1 < T2 < … < T10). `x-order: "semantic"` arrays are
  kept exactly as produced.
- `check_table_rows`: the same schema applied to every row of an Arrow table, vectorised
  (numpy/pyarrow masks per keyword), because telemetry tables have millions of rows. Keywords the
  vectorised evaluator does not know make it fall back to row-by-row `jsonschema`, so a schema
  that grows a new keyword is still enforced, only slower. When a row fails, the message comes
  from `jsonschema` on that one row.

`jsonschema` and `referencing` are imported lazily: core's engine-facing modules must not import
jsonschema at import time (core_api_spec §0).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Final, Literal, cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_contracts.registry import SCHEMA_NAMES, schema_json
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ContractValidationError

__all__ = [
    "SortRule",
    "check_orders",
    "check_table_rows",
    "contract_schema",
    "enum_values",
    "fill_absent_nullable",
    "parse_sort_rules",
    "validate_json_schema",
]

# pyarrow-stubs declares the compute kernels as overloads with Unknown parts, which pyright strict
# rejects at every call; calls go through this Any alias and results are typed where they are used.
_pc: Any = pc
type Mask = npt.NDArray[np.bool_]
type JSONSchema = Mapping[str, Any]

#: Shown in errors: how many further schema violations exist beyond the first one reported.
MAX_REPORTED_ERRORS: Final = 3
#: Longest value excerpt quoted in an error message (a priori: one readable line).
MAX_VALUE_CHARS: Final = 120

# Keywords that never constrain a value (annotations in JSON Schema 2020-12, including the
# content* vocabulary and `format`, which jsonschema also treats as annotations by default), plus
# the Veyltrace annotations that are checked elsewhere (x-arrow: Arrow schema equality in io).
_ANNOTATIONS: Final = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$id",
        "$schema",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "deprecated",
        "description",
        "examples",
        "format",
        "readOnly",
        "title",
        "writeOnly",
        "x-arrow",
        "x-veyltrace",
    }
)
_SORT_RULE_KEYS: Final = frozenset({"pointer", "order", "round", "nulls"})
_SORT_ORDERS: Final = ("asc", "desc", "enum")
_NULLS: Final = ("first", "last")
#: The only x-order value (CONVENTIONS §3.4).
X_ORDER_SEMANTIC: Final = "semantic"


class _Unsupported(Exception):
    """The vectorised evaluator met a keyword it cannot apply; use row-by-row jsonschema."""


# --------------------------------------------------------------------------------------------
# Schemas, registry, validators


@cache
def contract_schema(name: str) -> JSONSchema:
    """Return the parsed schema of contract `name` (the packaged copy in veyltrace_contracts)."""
    return schema_json(name)


#: The schema document a `$ref` is resolved against (a contract name or "common").
type Doc = str

_SCHEMA_FILE_SUFFIX: Final = ".schema.json"


def _lookup(ref: str, doc: Doc) -> tuple[object, Doc]:
    """Resolve a `$ref` the way the schemas use them (CONVENTIONS §1): `#/<pointer>` inside the
    current document or `<name>.schema.json#/<pointer>` in a sibling. Never fetches anything."""
    target, _, fragment = ref.partition("#")
    if target:
        name = target.removesuffix(_SCHEMA_FILE_SUFFIX)
        if not target.endswith(_SCHEMA_FILE_SUFFIX) or name not in SCHEMA_NAMES:
            raise ContractValidationError(doc, f"unresolvable $ref {ref!r}")
        doc = name
    node: object = contract_schema(doc)
    for raw in fragment.split("/")[1:] if fragment else []:
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = cast("dict[str, object]", node)[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(cast("list[object]", node)):
            node = cast("list[object]", node)[int(part)]
        else:
            raise ContractValidationError(doc, f"unresolvable $ref {ref!r}")
    return node, doc


@cache
def _validator(name: str) -> Any:
    """A jsonschema Draft 2020-12 validator whose registry holds every contract schema, keyed by
    `$id`, so `common.schema.json` references resolve offline. jsonschema ships no type
    information, hence the loose `Any`."""
    from jsonschema import Draft202012Validator  # pyright: ignore[reportMissingTypeStubs]
    from referencing import Registry
    from referencing.jsonschema import DRAFT202012

    resources = [
        (str(contract_schema(n)["$id"]), DRAFT202012.create_resource(dict(contract_schema(n))))
        for n in SCHEMA_NAMES
    ]
    registry_type: Any = Registry  # referencing's Anchor generics stay Unknown under pyright strict
    registry: Any = registry_type().with_resources(resources)
    return Draft202012Validator(dict(contract_schema(name)), registry=registry)


def _excerpt(value: object) -> str:
    text = repr(value)
    return text if len(text) <= MAX_VALUE_CHARS else text[: MAX_VALUE_CHARS - 3] + "..."


def _schema_errors(name: str, instance: object) -> list[str]:
    """All jsonschema violations of `instance`, as sorted "at <path>: <message>" strings."""
    found: list[str] = []
    for err in _validator(name).iter_errors(instance):
        path = "/" + "/".join(str(p) for p in cast("Sequence[object]", err.absolute_path))
        found.append(f"at {path}: {_excerpt_message(str(err.message))}")
    return sorted(found)


def _excerpt_message(message: str) -> str:
    return message if len(message) <= 2 * MAX_VALUE_CHARS else message[: 2 * MAX_VALUE_CHARS - 3] + "..."


def _raise_schema_errors(name: str, errors: Sequence[str], where: str = "") -> None:
    if not errors:
        return
    more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    shown = "; ".join(errors[:MAX_REPORTED_ERRORS])
    raise ContractValidationError(name, f"{where}schema violation {shown}{more}")


def validate_json_schema(name: str, instance: object, *, where: str = "") -> None:
    """Validate one JSON value (document, JSONL line or table row) against contract `name`'s
    JSON Schema; raise ContractValidationError naming the first violations."""
    _raise_schema_errors(name, _schema_errors(name, instance), where)


# --------------------------------------------------------------------------------------------
# x-sort / x-order


@dataclass(frozen=True)
class SortRule:
    """One parsed x-sort entry (CONVENTIONS §3.4): compare items by `pointer`, in `order`, after
    rounding numbers to `round` decimals, with nulls placed `nulls` (independent of `order`)."""

    pointer: str
    order: Literal["asc", "desc", "enum"]
    round: int | None
    nulls: Literal["first", "last"]


def parse_sort_rules(name: str, raw: object, where: str) -> tuple[SortRule, ...]:
    """Parse and check an x-sort value; a malformed one is a schema bug (ContractValidationError)."""
    if not isinstance(raw, list) or not raw:
        raise ContractValidationError(name, f"{where}: x-sort must be a non-empty list")
    rules: list[SortRule] = []
    for entry in cast("list[object]", raw):
        if not isinstance(entry, dict):
            raise ContractValidationError(name, f"{where}: x-sort entry {entry!r} is not an object")
        rule = cast("dict[str, object]", entry)
        unknown = sorted(set(rule) - _SORT_RULE_KEYS)
        pointer, order = rule.get("pointer"), rule.get("order")
        rnd, nulls = rule.get("round"), rule.get("nulls", "first")
        bad_round = rnd is not None and (not isinstance(rnd, int) or isinstance(rnd, bool) or rnd < 0)
        if (
            unknown
            or not isinstance(pointer, str)
            or not pointer
            or order not in _SORT_ORDERS
            or nulls not in _NULLS
            or bad_round
        ):
            raise ContractValidationError(name, f"{where}: malformed x-sort entry {rule!r}")
        rules.append(
            SortRule(
                pointer=pointer,
                order=order,
                round=cast("int | None", rnd),
                nulls=nulls,
            )
        )
    return tuple(rules)


def _deref(node: object, resolver: Doc) -> tuple[JSONSchema, Doc]:
    """Follow a chain of `$ref`s to the node they finally name (siblings of `$ref` are dropped,
    which is right for the structural lookups below: properties, items, enum)."""
    while isinstance(node, dict) and "$ref" in node:
        node, resolver = _lookup(str(cast("dict[str, object]", node)["$ref"]), resolver)
    if not isinstance(node, dict):
        return {}, resolver
    return cast("JSONSchema", node), resolver


def _find_enum(node: object, resolver: Doc) -> list[object] | None:
    schema, resolver = _deref(node, resolver)
    if "enum" in schema:
        return list(cast("list[object]", schema["enum"]))
    for keyword in ("anyOf", "oneOf", "allOf"):
        for branch in cast("list[object]", schema.get(keyword, [])):
            found = _find_enum(branch, resolver)
            if found is not None:
                return found
    return None


def enum_values(name: str, item_schema: object, resolver: Doc, pointer: str) -> list[object]:
    """The enum of the field `pointer` inside `item_schema` (for x-sort `order: "enum"`)."""
    node: object = item_schema
    if pointer != ".":
        for segment in pointer.split("/"):
            schema, resolver = _deref(node, resolver)
            props = cast("Mapping[str, object]", schema.get("properties", {}))
            if segment not in props:
                raise ContractValidationError(name, f"x-sort pointer {pointer!r} names no property")
            node = props[segment]
    found = _find_enum(node, resolver)
    if found is None:
        raise ContractValidationError(name, f"x-sort pointer {pointer!r} has order 'enum' but no enum")
    return found


def _pointer_get(item: object, pointer: str) -> object:
    if pointer == ".":
        return item
    value = item
    for segment in pointer.split("/"):
        if not isinstance(value, dict):
            return None
        value = cast("dict[str, object]", value).get(segment)
    return value


def _order_key(name: str, value: object, rule: SortRule, enum: list[object] | None) -> tuple[str, Any]:
    """A (category, comparable) pair; only values of one category are comparable."""
    if rule.order == "enum":
        if enum is None or value not in enum:
            raise ContractValidationError(name, f"{_excerpt(value)} is not in the enum of {rule.pointer!r}")
        return ("enum", enum.index(value))
    if isinstance(value, bool):
        return ("bool", int(value))
    if isinstance(value, int | float):
        return ("number", round(value, rule.round) if rule.round is not None else value)
    if isinstance(value, str):
        return ("string", value.encode("utf-8"))  # UTF-8 byte order (CONVENTIONS §3.4)
    if isinstance(value, dict | list):
        return ("json", canonical_json(cast("Any", value)))  # canonical bytes for object values
    raise ContractValidationError(name, f"x-sort cannot compare {_excerpt(value)}")


def _compare(
    name: str, a: object, b: object, rules: Sequence[SortRule], enums: Sequence[list[object] | None]
) -> int:
    for rule, enum in zip(rules, enums, strict=True):
        va, vb = _pointer_get(a, rule.pointer), _pointer_get(b, rule.pointer)
        if va is None or vb is None:
            if va is None and vb is None:
                continue
            first = -1 if va is None else 1  # a before b when a is the null one
            return first if rule.nulls == "first" else -first
        ka, kb = _order_key(name, va, rule, enum), _order_key(name, vb, rule, enum)
        if ka[0] != kb[0]:
            raise ContractValidationError(
                name, f"x-sort {rule.pointer!r} compares {_excerpt(va)} with {_excerpt(vb)}"
            )
        if ka[1] == kb[1]:
            continue
        less = cast("bool", ka[1] < kb[1])
        cmp = -1 if less else 1
        return -cmp if rule.order == "desc" else cmp
    return 0


def check_list_order(name: str, node: JSONSchema, resolver: Doc, items: Sequence[object], path: str) -> None:
    """Raise unless `items` follow `node`'s x-sort (ties allowed; never re-sorted)."""
    rules = parse_sort_rules(name, node["x-sort"], path or "/")
    item_schema = node.get("items", {})
    enums = [
        enum_values(name, item_schema, resolver, r.pointer) if r.order == "enum" else None for r in rules
    ]
    for i in range(1, len(items)):
        if _compare(name, items[i - 1], items[i], rules, enums) > 0:
            stated = ", ".join(f"{r.pointer} {r.order}" for r in rules)
            raise ContractValidationError(
                name,
                f"at {path or '/'}: items {i - 1} and {i} break the stated order ({stated}); "
                "writers validate the producer's order and never re-sort it (CONVENTIONS §3.4)",
            )


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _admits(node: object, resolver: Doc, value: object) -> bool:
    """False only if the branch's `type` rules `value` out (enough to pick anyOf branches)."""
    schema, _ = _deref(node, resolver)
    declared = schema.get("type")
    if declared is None:
        return True
    types = [declared] if isinstance(declared, str) else cast("list[str]", declared)
    actual = _json_type(value)
    return actual in types or (actual == "integer" and "number" in types)


def _walk(name: str, node: object, resolver: Doc, value: object, path: str) -> None:
    if not isinstance(node, dict):
        return
    schema = cast("JSONSchema", node)
    if "$ref" in schema:
        target, doc = _lookup(str(schema["$ref"]), resolver)
        _walk(name, target, doc, value, path)
    if "x-order" in schema and schema["x-order"] != X_ORDER_SEMANTIC:
        raise ContractValidationError(name, f"at {path or '/'}: unknown x-order {schema['x-order']!r}")
    if isinstance(value, list):
        seq = cast("list[object]", value)
        if "x-sort" in schema:
            check_list_order(name, schema, resolver, seq, path)
        items: object = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(seq):
                _walk(name, cast("object", items), resolver, item, f"{path}/{i}")
    elif isinstance(value, dict):
        obj = cast("dict[str, object]", value)
        props = cast("Mapping[str, object]", schema.get("properties", {}))
        extra: object = schema.get("additionalProperties")
        for key in sorted(obj):
            if key in props:
                _walk(name, props[key], resolver, obj[key], f"{path}/{key}")
            elif isinstance(extra, dict):
                _walk(name, cast("object", extra), resolver, obj[key], f"{path}/{key}")
    instance = cast("object", value)
    for keyword in ("anyOf", "oneOf", "allOf"):
        for branch in cast("list[object]", schema.get(keyword, [])):
            if _admits(branch, resolver, instance):
                _walk(name, branch, resolver, instance, path)


def check_orders(name: str, instance: object) -> None:
    """Raise ContractValidationError unless every x-sort array in `instance` is in its stated
    order and every x-order is "semantic". `instance` is a JSON document, line or table row that
    already passed validate_json_schema. x-sort under if/then/else/not is not visited (no schema
    has one; a test pins that)."""
    _walk(name, contract_schema(name), name, instance, "")


def _fill(node: object, resolver: Doc, instance: object) -> object:
    schema, resolver = _deref(node, resolver)
    out: object = instance
    if isinstance(instance, list):
        items: object = schema.get("items")
        if isinstance(items, dict):
            sub = cast("object", items)
            out = [_fill(sub, resolver, v) for v in cast("list[object]", instance)]
    elif isinstance(instance, dict):
        obj: dict[str, object] = dict(cast("dict[str, object]", instance))
        props = cast("Mapping[str, object]", schema.get("properties", {}))
        for key in sorted(props):
            if key in obj:
                obj[key] = _fill(props[key], resolver, obj[key])
            elif _admits_null(props[key], resolver):
                obj[key] = None
        out = obj
    for keyword in ("anyOf", "oneOf", "allOf"):
        for branch in cast("list[object]", schema.get(keyword, [])):
            if out is not None and _admits(branch, resolver, out):
                out = _fill(branch, resolver, out)
    return out


def _admits_null(node: object, resolver: Doc) -> bool:
    """True if the property schema allows null (`type` includes it, or an anyOf/oneOf branch is
    null): an additive field of a newer minor, read as null from an older file."""
    schema, resolver = _deref(node, resolver)
    declared = schema.get("type")
    if declared is not None:
        types = [declared] if isinstance(declared, str) else cast("list[str]", declared)
        return "null" in types
    return any(
        _admits_null(branch, resolver)
        for keyword in ("anyOf", "oneOf")
        for branch in cast("list[object]", schema.get(keyword, []))
    )


def fill_absent_nullable(name: str, instance: object) -> object:
    """A copy of `instance` with every absent property whose schema admits null set to null, at
    any depth. Used for documents written under an older minor of the contract (critic gap
    "version rule": additive fields absent from older files read as null)."""
    return _fill(contract_schema(name), name, instance)


# --------------------------------------------------------------------------------------------
# Vectorised evaluation over Arrow tables


def _np_bool(arr: pa.Array[Any] | pa.ChunkedArray[Any], null_as: bool) -> Mask:
    filled = _pc.fill_null(arr, null_as)
    return np.asarray(filled.to_numpy(zero_copy_only=False), dtype=np.bool_)


def _valid(arr: pa.Array[Any]) -> Mask:
    return _np_bool(_pc.is_valid(arr), False)


def _scalar_matches(value: object, dtype: pa.DataType) -> bool:
    if pa.types.is_boolean(dtype):
        return isinstance(value, bool)
    if pa.types.is_integer(dtype):
        return isinstance(value, int) and not isinstance(value, bool)
    if pa.types.is_floating(dtype):
        return isinstance(value, int | float) and not isinstance(value, bool)
    if pa.types.is_string(dtype):
        return isinstance(value, str)
    return False


def _in_set(arr: pa.Array[Any], values: Sequence[object]) -> Mask:
    if not values:
        return np.zeros(len(arr), dtype=np.bool_)
    value_set = cast("pa.Array[Any]", pa.array(list(values), type=arr.type))
    return _np_bool(_pc.is_in(arr, value_set=value_set), False)


def _type_mask(declared: object, arr: pa.Array[Any], valid: Mask) -> Mask:
    types = [declared] if isinstance(declared, str) else cast("list[object]", declared)
    dtype = arr.type
    out = np.zeros(len(arr), dtype=np.bool_)
    for t in types:
        if t == "null":
            out |= ~valid
        elif t == "boolean":
            out |= valid & pa.types.is_boolean(dtype)
        elif t == "integer":
            out |= valid & pa.types.is_integer(dtype)
        elif t == "number":
            if pa.types.is_integer(dtype):
                out |= valid
            elif pa.types.is_floating(dtype):
                out |= valid & _np_bool(_pc.is_finite(arr), False)  # NaN/±inf are not JSON numbers
        elif t == "string":
            out |= valid & pa.types.is_string(dtype)
        elif t == "array":
            out |= valid & pa.types.is_list(dtype)
        else:
            raise _Unsupported(f"type {t!r}")
    return out


def _enum_mask(values: Sequence[object], arr: pa.Array[Any], valid: Mask) -> Mask:
    if pa.types.is_list(arr.type):
        raise _Unsupported("enum on an array column")
    typed = [v for v in values if v is not None and _scalar_matches(v, arr.type)]
    out = _in_set(arr, typed) & valid
    if any(v is None for v in values):
        out |= ~valid
    return out


def _pattern_mask(pattern: str, arr: pa.Array[Any], valid: Mask) -> Mask:
    if not pa.types.is_string(arr.type):
        return np.ones(len(arr), dtype=np.bool_)
    # Python `re.search` on the distinct values: the exact semantics jsonschema uses for "pattern".
    regex = re.compile(pattern)
    distinct = cast("list[str | None]", _pc.unique(arr).to_pylist())
    good = [s for s in distinct if s is not None and regex.search(s) is not None]
    return _in_set(arr, good) | ~valid


_BOUNDS: Final[Mapping[str, str]] = {
    "minimum": "greater_equal",
    "maximum": "less_equal",
    "exclusiveMinimum": "greater",
    "exclusiveMaximum": "less",
}


def _bound_mask(keyword: str, bound: object, arr: pa.Array[Any]) -> Mask:
    dtype = arr.type
    if not (pa.types.is_integer(dtype) or pa.types.is_floating(dtype)):
        return np.ones(len(arr), dtype=np.bool_)
    if not isinstance(bound, int | float) or isinstance(bound, bool):
        raise _Unsupported(f"{keyword} {bound!r}")
    compare = getattr(pc, _BOUNDS[keyword])
    return _np_bool(compare(arr, pa.scalar(bound)), True)


def _length_mask(keyword: str, bound: object, lengths: pa.Array[Any]) -> Mask:
    if not isinstance(bound, int) or isinstance(bound, bool):
        raise _Unsupported(f"{keyword} {bound!r}")
    compare = _pc.greater_equal if keyword.startswith("min") else _pc.less_equal
    return _np_bool(compare(lengths, pa.scalar(bound)), True)


def _list_rows(arr: pa.Array[Any]) -> list[list[object] | None]:
    return cast("list[list[object] | None]", arr.to_pylist())


def _items_mask(sub: object, resolver: Doc, arr: pa.Array[Any], name: str) -> Mask:
    lists = cast("pa.ListArray[Any]", arr)
    lengths = np.asarray(
        _pc.fill_null(_pc.list_value_length(lists), 0).to_numpy(zero_copy_only=False), dtype=np.int64
    )
    values = cast(
        "pa.Array[Any]", _pc.list_flatten(lists)
    )  # values of the non-null lists, in order (matches `lengths`)
    item_ok = _array_mask(sub, resolver, values, name)
    parents = np.repeat(np.arange(len(arr), dtype=np.int64), lengths)
    out = np.ones(len(arr), dtype=np.bool_)
    out[np.unique(parents[~item_ok])] = False
    return out


def _unique_items_mask(arr: pa.Array[Any]) -> Mask:
    rows = _list_rows(arr)
    return np.array(
        [row is None or len({canonical_json(cast("Any", v)) for v in row}) == len(row) for row in rows],
        dtype=np.bool_,
    )


def _sorted_items_mask(name: str, node: JSONSchema, resolver: Doc, arr: pa.Array[Any]) -> Mask:
    rows = _list_rows(arr)
    out = np.ones(len(rows), dtype=np.bool_)
    for i, row in enumerate(rows):
        if row is None:
            continue
        try:
            check_list_order(name, node, resolver, row, "")
        except ContractValidationError:
            out[i] = False
    return out


def _combine(keyword: str, value: object, evaluate: Callable[[object], Mask], n: int) -> Mask:
    masks = [evaluate(b) for b in cast("list[object]", value)]
    if keyword == "allOf":
        return np.logical_and.reduce(masks) if masks else np.ones(n, dtype=np.bool_)
    if keyword == "anyOf":
        return np.logical_or.reduce(masks) if masks else np.zeros(n, dtype=np.bool_)
    counts = np.sum(np.stack(masks), axis=0) if masks else np.zeros(n, dtype=np.int64)
    return np.asarray(counts == 1, dtype=np.bool_)  # oneOf


def _conditional(node: JSONSchema, evaluate: Callable[[object], Mask], n: int) -> Mask:
    cond = evaluate(node["if"])
    then = evaluate(node["then"]) if "then" in node else np.ones(n, dtype=np.bool_)
    other = evaluate(node["else"]) if "else" in node else np.ones(n, dtype=np.bool_)
    return np.where(cond, then, other)


def _array_mask(node: object, resolver: Doc, arr: pa.Array[Any], name: str = "") -> Mask:
    """True where the value satisfies `node` (JSON Schema semantics; nulls are JSON null)."""
    n = len(arr)
    if node is True:
        return np.ones(n, dtype=np.bool_)
    if node is False:
        return np.zeros(n, dtype=np.bool_)
    if not isinstance(node, dict):
        raise _Unsupported(f"schema {node!r}")
    schema = cast("JSONSchema", node)
    valid = _valid(arr)
    is_list = pa.types.is_list(arr.type)
    out = np.ones(n, dtype=np.bool_)

    def evaluate(sub: object) -> Mask:
        return _array_mask(sub, resolver, arr, name)

    for keyword, value in schema.items():
        if keyword in _ANNOTATIONS or keyword in ("then", "else"):
            continue
        if keyword == "$ref":
            target, doc = _lookup(str(value), resolver)
            out &= _array_mask(target, doc, arr, name)
        elif keyword == "type":
            out &= _type_mask(value, arr, valid)
        elif keyword == "enum":
            out &= _enum_mask(cast("list[object]", value), arr, valid)
        elif keyword == "const":
            out &= _enum_mask([value], arr, valid)
        elif keyword == "pattern":
            out &= _pattern_mask(str(value), arr, valid)
        elif keyword in ("minLength", "maxLength"):
            if pa.types.is_string(arr.type):
                out &= _length_mask(keyword, value, _pc.utf8_length(arr))
        elif keyword in _BOUNDS:
            out &= _bound_mask(keyword, value, arr)
        elif keyword in ("minItems", "maxItems"):
            if is_list:
                out &= _length_mask(keyword, value, _pc.list_value_length(cast("pa.ListArray[Any]", arr)))
        elif keyword == "items":
            if is_list:
                out &= _items_mask(value, resolver, arr, name)
        elif keyword == "uniqueItems":
            if is_list and value is True:
                out &= _unique_items_mask(arr)
        elif keyword == "x-sort":
            if is_list:
                out &= _sorted_items_mask(name, schema, resolver, arr)
        elif keyword == "x-order":
            if value != X_ORDER_SEMANTIC:
                raise _Unsupported(f"x-order {value!r}")
        elif keyword in ("allOf", "anyOf", "oneOf"):
            out &= _combine(keyword, value, evaluate, n)
        elif keyword == "not":
            out &= ~evaluate(value)
        elif keyword == "if":
            out &= _conditional(schema, evaluate, n)
        else:
            raise _Unsupported(keyword)
    return out


def _column(batch: pa.RecordBatch, index: int) -> pa.Array[Any]:
    return cast("pa.Array[Any]", batch.column(index))


def _row_mask(node: object, resolver: Doc, batch: pa.RecordBatch, name: str) -> Mask:
    """True where the row (an object whose properties are the batch columns) satisfies `node`."""
    n = batch.num_rows
    if node is True:
        return np.ones(n, dtype=np.bool_)
    if not isinstance(node, dict):
        raise _Unsupported(f"row schema {node!r}")
    schema = cast("JSONSchema", node)
    columns = list(batch.schema.names)
    props = cast("Mapping[str, object]", schema.get("properties", {}))
    out = np.ones(n, dtype=np.bool_)

    def evaluate(sub: object) -> Mask:
        return _row_mask(sub, resolver, batch, name)

    for keyword, value in schema.items():
        if keyword in _ANNOTATIONS or keyword in ("then", "else"):
            continue
        if keyword == "$ref":
            target, doc = _lookup(str(value), resolver)
            out &= _row_mask(target, doc, batch, name)
        elif keyword == "type":
            if value not in ("object", ["object"]):
                raise _Unsupported(f"row type {value!r}")
        elif keyword == "properties":
            for prop in sorted(props):
                if prop in columns:
                    out &= _array_mask(props[prop], resolver, _column(batch, columns.index(prop)), name)
        elif keyword == "required":
            if not set(cast("list[str]", value)) <= set(columns):
                out[:] = False
        elif keyword == "additionalProperties":
            extra = [c for c in columns if c not in props]
            if value is False and extra:
                out[:] = False
            elif isinstance(value, dict):
                for col in extra:
                    out &= _array_mask(
                        cast("object", value), resolver, _column(batch, columns.index(col)), name
                    )
        elif keyword in ("allOf", "anyOf", "oneOf"):
            out &= _combine(keyword, value, evaluate, n)
        elif keyword == "not":
            out &= ~evaluate(value)
        elif keyword == "if":
            out &= _conditional(schema, evaluate, n)
        else:
            raise _Unsupported(keyword)
    return out


def _row(table: pa.Table, index: int) -> dict[str, object]:
    return cast("dict[str, object]", table.slice(index, 1).to_pylist()[0])


def _explain_row(name: str, table: pa.Table, index: int) -> None:
    row = _row(table, index)
    where = f"row {index}: "
    validate_json_schema(name, row, where=where)
    try:
        check_orders(name, row)
    except ContractValidationError as exc:
        raise ContractValidationError(name, f"{where}{exc.detail}") from None
    raise ContractValidationError(name, f"{where}violates the schema: {_excerpt(row)}")


def check_table_rows(name: str, table: pa.Table) -> None:
    """Raise ContractValidationError unless every row of `table` satisfies contract `name`'s row
    schema (including x-sort on list columns). Vectorised; row-by-row only as a fallback."""
    schema = contract_schema(name)
    resolver: Doc = name
    offset = 0
    try:
        for batch in table.to_batches():
            ok = _row_mask(schema, resolver, batch, name)
            if not bool(ok.all()):
                _explain_row(name, table, offset + int(np.argmin(ok)))
            offset += batch.num_rows
    except _Unsupported:
        for index, row in enumerate(cast("list[dict[str, object]]", table.to_pylist())):
            validate_json_schema(name, row, where=f"row {index}: ")
            check_orders(name, row)
