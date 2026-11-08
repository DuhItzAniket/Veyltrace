"""A strict YAML loader for config files: YAML 1.2 core-schema scalars, no duplicate keys.

PyYAML implements YAML 1.1, whose implicit typing silently changes config values (core_api_spec
D-23): `off`, `on`, `yes` and `no` become bools (an `ai_arm: off` would turn into False),
`1e-6` stays a string (1.1 floats need a dot), `010` is octal 8, `1_000` is 1000 and `2026-11-06`
becomes a date. A duplicated key silently keeps the last value. Each of these changes what a run
computes without any error, so this loader:

- resolves plain scalars with the YAML 1.2 core schema only: null (`~`, `null`, empty), bool
  (`true`/`false` in three casings), int (decimal, `0o` octal, `0x` hex) and float (decimal with
  optional exponent, `.inf`, `.nan`); everything else, regexes included, stays a verbatim string;
- raises ConfigError on a duplicate or non-string mapping key, and on tags with no JSON form
  (`!!binary`, `!!timestamp`, `!!set`, `!!omap`, `!!pairs`);
- parses from bytes as strict UTF-8, so the result never depends on the OS locale
  (M0 lead decision 2026-11-06, "text I/O").

Line breaks inside scalars are normalised to LF by YAML itself, so a CRLF checkout loads the same
values as an LF one.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Hashable
from typing import Any, ClassVar, cast

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode

from veyltrace_core.errors import ConfigError

__all__ = ["load_yaml_bytes", "load_yaml_text"]

# YAML 1.2.2 core schema, §10.3.2 "Tag Resolution" (https://yaml.org/spec/1.2.2/#1032-tag-resolution).
_NULL_RE = re.compile(r"~|null|Null|NULL|")
_BOOL_RE = re.compile(r"true|True|TRUE|false|False|FALSE")
_INT_DEC_RE = re.compile(r"[-+]?[0-9]+")
_INT_OCT_RE = re.compile(r"0o[0-7]+")
_INT_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_FLOAT_RE = re.compile(r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?")
_INF_RE = re.compile(r"[-+]?\.(?:inf|Inf|INF)")
_NAN_RE = re.compile(r"\.(?:nan|NaN|NAN)")
_INT_RE = re.compile(f"{_INT_DEC_RE.pattern}|{_INT_OCT_RE.pattern}|{_INT_HEX_RE.pattern}")
_ANY_FLOAT_RE = re.compile(f"{_FLOAT_RE.pattern}|{_INF_RE.pattern}|{_NAN_RE.pattern}")

_TAG_NULL = "tag:yaml.org,2002:null"
_TAG_BOOL = "tag:yaml.org,2002:bool"
_TAG_INT = "tag:yaml.org,2002:int"
_TAG_FLOAT = "tag:yaml.org,2002:float"
# Standard tags SafeLoader would construct into values that have no JSON form.
_NON_JSON_TAGS = (
    "tag:yaml.org,2002:binary",
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:set",
    "tag:yaml.org,2002:omap",
    "tag:yaml.org,2002:pairs",
)
# Base for octal and hex ints; the prefix is two characters ("0o", "0x").
_OCT_BASE = 8
_HEX_BASE = 16
_PREFIX_LEN = 2

_DIGITS = list("0123456789")
_SIGNS = ["-", "+"]


def _where(node: Node) -> str:
    mark = node.start_mark
    return f"line {mark.line + 1}, column {mark.column + 1}"


class _Loader(yaml.SafeLoader):
    """SafeLoader with the YAML 1.2 core schema and strict mappings (see module docstring)."""

    # Start from no implicit resolvers at all: the YAML 1.1 ones inherited from SafeLoader are
    # exactly what this loader exists to avoid. add_implicit_resolver copies this dict per class.
    yaml_implicit_resolvers: ClassVar[dict[Any, Any]] = {}  # pyright: ignore[reportIncompatibleVariableOverride]  # stubs type it as an instance attribute

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        """Construct a mapping, rejecting duplicate and non-string keys (D-23)."""
        seen: set[str] = set()
        for key_node, _ in node.value:
            key: object = _construct_object(self, key_node)
            if not isinstance(key, str):
                msg = f"mapping keys must be strings, got {key!r} at {_where(key_node)}"
                raise ConfigError(msg)
            if key in seen:
                msg = f"duplicate key {key!r} at {_where(key_node)}"
                raise ConfigError(msg)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _construct_object(loader: _Loader, node: Node) -> object:
    construct = cast(
        Callable[[Node, bool], object],
        loader.construct_object,  # pyright: ignore[reportUnknownMemberType]  # pyyaml stubs leave `node` untyped
    )
    return construct(node, True)


def _scalar(loader: _Loader, node: Node) -> str:
    if not isinstance(node, ScalarNode):
        msg = f"expected a scalar at {_where(node)}"
        raise ConfigError(msg)
    return loader.construct_scalar(node)


def _construct_null(loader: _Loader, node: Node) -> None:
    text = _scalar(loader, node)
    if _NULL_RE.fullmatch(text) is None:
        msg = f"not a YAML 1.2 null: {text!r} at {_where(node)}"
        raise ConfigError(msg)


def _construct_bool(loader: _Loader, node: Node) -> bool:
    text = _scalar(loader, node)
    if _BOOL_RE.fullmatch(text) is None:
        msg = f"not a YAML 1.2 bool: {text!r} at {_where(node)}"
        raise ConfigError(msg)
    return text.lower() == "true"


def _construct_int(loader: _Loader, node: Node) -> int:
    text = _scalar(loader, node)
    if _INT_OCT_RE.fullmatch(text):
        return int(text[_PREFIX_LEN:], _OCT_BASE)
    if _INT_HEX_RE.fullmatch(text):
        return int(text[_PREFIX_LEN:], _HEX_BASE)
    if _INT_DEC_RE.fullmatch(text):
        return int(text, 10)  # "010" is ten in YAML 1.2, not octal eight
    msg = f"not a YAML 1.2 int: {text!r} at {_where(node)}"
    raise ConfigError(msg)


def _construct_float(loader: _Loader, node: Node) -> float:
    text = _scalar(loader, node)
    if _INF_RE.fullmatch(text):
        return -math.inf if text.startswith("-") else math.inf
    if _NAN_RE.fullmatch(text):
        return math.nan
    if _FLOAT_RE.fullmatch(text):
        return float(text)
    msg = f"not a YAML 1.2 float: {text!r} at {_where(node)}"
    raise ConfigError(msg)


def _reject_tag(loader: _Loader, node: Node) -> None:
    msg = f"tag {node.tag} has no JSON form and is not allowed in config ({_where(node)})"
    raise ConfigError(msg)


_add_resolver = cast(
    Callable[[str, re.Pattern[str], list[str]], None],
    _Loader.add_implicit_resolver,  # pyright: ignore[reportUnknownMemberType]  # pyyaml stubs leave the params untyped
)


def _whole(pattern: re.Pattern[str]) -> re.Pattern[str]:
    r"""Anchor a pattern at both ends: PyYAML resolvers call regexp.match (start only), and "\Z",
    unlike "$", does not match before a trailing newline."""
    return re.compile(rf"(?:{pattern.pattern})\Z")


_add_resolver(_TAG_NULL, _whole(_NULL_RE), ["~", "n", "N", ""])
_add_resolver(_TAG_BOOL, _whole(_BOOL_RE), list("tTfF"))
# Ints are registered before floats: resolvers are tried in order and the float pattern also
# matches plain digit strings.
_add_resolver(_TAG_INT, _whole(_INT_RE), [*_DIGITS, *_SIGNS])
_add_resolver(_TAG_FLOAT, _whole(_ANY_FLOAT_RE), [*_DIGITS, *_SIGNS, "."])
_Loader.add_constructor(_TAG_NULL, _construct_null)
_Loader.add_constructor(_TAG_BOOL, _construct_bool)
_Loader.add_constructor(_TAG_INT, _construct_int)
_Loader.add_constructor(_TAG_FLOAT, _construct_float)
for _tag in _NON_JSON_TAGS:
    _Loader.add_constructor(_tag, _reject_tag)


def load_yaml_text(text: str, *, source: str) -> object:
    """Parse one YAML document under the rules above; `source` names it in error messages.

    An empty document gives None. Raises ConfigError for any syntax error, duplicate key,
    non-string key or disallowed tag.
    """
    try:
        return yaml.load(text, Loader=_Loader)  # _Loader is a SafeLoader subclass
    except ConfigError as exc:
        msg = f"{source}: {exc}"
        raise ConfigError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"{source}: invalid YAML: {exc}"
        raise ConfigError(msg) from exc


def load_yaml_bytes(data: bytes, *, source: str) -> object:
    """Decode `data` as strict UTF-8 (a leading BOM is skipped) and parse it with load_yaml_text."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{source}: not valid UTF-8: {exc}"
        raise ConfigError(msg) from exc
    return load_yaml_text(text, source=source)
