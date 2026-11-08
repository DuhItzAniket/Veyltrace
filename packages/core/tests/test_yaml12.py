"""Tests for veyltrace_core.yaml12: YAML 1.2 core-schema scalars and strict mappings (D-23)."""

from __future__ import annotations

import math

import pytest

from veyltrace_core.errors import ConfigError
from veyltrace_core.yaml12 import load_yaml_bytes, load_yaml_text


def _value(text: str) -> object:
    doc = load_yaml_text(f"v: {text}\n", source="test")
    assert isinstance(doc, dict)
    return doc["v"]  # pyright: ignore[reportUnknownVariableType]  # test helper over a parsed dict


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("off", "off"),
        ("on", "on"),
        ("yes", "yes"),
        ("no", "no"),
        ("y", "y"),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("false", False),
        ("FALSE", False),
        ("~", None),
        ("null", None),
        ("Null", None),
        ("", None),
        ("0", 0),
        ("-3", -3),
        ("+7", 7),
        ("010", 10),
        ("0o10", 8),
        ("0x1f", 31),
        ("1_000", "1_000"),
        ("3.0", 3.0),
        ("1e-6", 1e-6),
        ("1E3", 1000.0),
        ("1.", 1.0),
        (".5", 0.5),
        ("-.5", -0.5),
        ("2026-11-06", "2026-11-06"),
        ("'3'", "3"),
        ('"off"', "off"),
        ("_total$", "_total$"),
        (r"'\d+ms$'", r"\d+ms$"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("12:30", "12:30"),
        ("0b101", "0b101"),
    ],
)
def test_core_schema_scalars(text: str, expected: object) -> None:
    value = _value(text)
    assert value == expected
    assert type(value) is type(expected)


def test_special_floats() -> None:
    assert _value(".inf") == math.inf
    assert _value("-.Inf") == -math.inf
    nan = _value(".nan")
    assert isinstance(nan, float)
    assert math.isnan(nan)


def test_duplicate_key_is_an_error() -> None:
    with pytest.raises(ConfigError, match="duplicate key 'a' at line 3"):
        load_yaml_text("a: 1\nb: 2\na: 3\n", source="dup.yaml")


def test_nested_duplicate_key_is_an_error() -> None:
    with pytest.raises(ConfigError, match="duplicate key 'x'"):
        load_yaml_text("a:\n  x: 1\n  x: 2\n", source="dup.yaml")


@pytest.mark.parametrize("text", ["1: a\n", "true: a\n", "null: a\n", "[1, 2]: a\n"])
def test_non_string_key_is_an_error(text: str) -> None:
    with pytest.raises(ConfigError, match="keys must be strings"):
        load_yaml_text(text, source="keys.yaml")


@pytest.mark.parametrize(
    "text", ["v: !!binary aGVsbG8=\n", "v: !!timestamp 2026-11-06\n", "v: !!set {a: null}\n"]
)
def test_non_json_tags_are_rejected(text: str) -> None:
    with pytest.raises(ConfigError, match="no JSON form"):
        load_yaml_text(text, source="tags.yaml")


def test_explicit_tags_follow_the_core_schema() -> None:
    doc = load_yaml_text("a: !!int '010'\nb: !!float '1'\nc: !!str 3\n", source="t")
    assert doc == {"a": 10, "b": 1.0, "c": "3"}
    with pytest.raises(ConfigError, match=r"not a YAML 1\.2 bool"):
        load_yaml_text("a: !!bool yes\n", source="t")


def test_syntax_error_names_the_source() -> None:
    with pytest.raises(ConfigError, match=r"bad\.yaml: invalid YAML"):
        load_yaml_text("a: [1, 2\n", source="bad.yaml")


def test_bytes_are_strict_utf8_and_crlf_is_normalised() -> None:
    lf = load_yaml_bytes('a: "→ §"\nb:\n  - x\n'.encode(), source="lf")
    crlf = load_yaml_bytes('a: "→ §"\r\nb:\r\n  - x\r\n'.encode(), source="crlf")
    bom = load_yaml_bytes(b"\xef\xbb\xbf" + 'a: "→ §"\nb:\n  - x\n'.encode(), source="bom")
    assert lf == crlf == bom == {"a": "→ §", "b": ["x"]}
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_yaml_bytes("a: é\n".encode("cp1252"), source="cp1252.yaml")


def test_empty_document_is_none() -> None:
    assert load_yaml_text("# only a comment\n", source="empty") is None


def test_flow_collections() -> None:
    assert load_yaml_text("v: [-1200, -120]\nm: {a: off, b: 1.5}\n", source="t") == {
        "v": [-1200, -120],
        "m": {"a": "off", "b": 1.5},
    }
