"""Tests for veyltrace_core.calibration: family ids, selection, strict files, sentinel (03 §12.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts.models import Calibration
from veyltrace_core.calibration import (
    UNCALIBRATED,
    UNCALIBRATED_SHA256,
    CalibrationRef,
    ai_arm_for,
    calibration_bytes,
    find_calibration,
    is_family_id,
    load_calibration,
    make_family_id,
    parse_json_strict,
    ref_from_lock,
    select_family,
    write_calibration,
)
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_bytes, sha256_json

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "contracts" / "examples" / "calibration.example.json"


def example_content(**changes: Any) -> dict[str, Any]:
    """The contracts example calibration, with top-level fields replaced."""
    content: dict[str, Any] = json.loads(EXAMPLE.read_bytes())
    content.update(changes)
    return content


def test_uncalibrated_sentinel() -> None:
    assert UNCALIBRATED == "uncalibrated"
    assert sha256_json({"family": "uncalibrated"}) == UNCALIBRATED_SHA256
    assert sha256_bytes(b'{"family":"uncalibrated"}') == UNCALIBRATED_SHA256


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("rcaeval-re2", "brief", "oracle", "foldA"), "rcaeval-re2.brief.oracle.foldA"),
        (("rcaeval-re2-ob", "brief", "oracle", "foldA"), "rcaeval-re2-ob.brief.oracle.foldA"),
        (("rcaeval-re2", "brief", "oracle", "loso-ob"), "rcaeval-re2.brief.oracle.loso-ob"),
        (("synth", "off", "detected", "foldB"), "synth.off.detected.foldB"),
    ],
)
def test_make_family_id(parts: tuple[str, str, str, str], expected: str) -> None:
    assert make_family_id(*parts) == expected
    assert is_family_id(expected)


@pytest.mark.parametrize(
    "parts",
    [
        ("RCAEval", "brief", "oracle", "foldA"),
        ("re2.ob", "brief", "oracle", "foldA"),
        ("re2", "agent_only", "oracle", "foldA"),
        ("re2", "brief", "manual", "foldA"),
        ("re2", "brief", "oracle", "fold.A"),
        ("re2", "brief", "oracle", ""),
    ],
)
def test_make_family_id_rejects_bad_parts(parts: tuple[str, str, str, str]) -> None:
    with pytest.raises(ConfigError):
        make_family_id(*parts)


def test_is_family_id() -> None:
    assert not is_family_id("synth")
    assert not is_family_id("synth.off.oracle.foldA\n")
    assert not is_family_id(None)


FAMILY_MAP = {
    "re2-*": "rcaeval-re2",
    "re2-ob": "rcaeval-re2-ob",
    "re*": "other",
    "synth": "synth",
}


@pytest.mark.parametrize(
    ("dataset", "expected"),
    [
        ("re2-ob", "rcaeval-re2-ob"),  # exact key before any glob
        ("re2-tt", "rcaeval-re2"),  # glob
        ("synth", "synth"),
        ("nezha-ob", None),
        ("RE2-OB", None),  # fnmatchcase: case-sensitive on every OS
    ],
)
def test_select_family_from_map(dataset: str, expected: str | None) -> None:
    family_map = {k: v for k, v in FAMILY_MAP.items() if k != "re*"}
    assert select_family(dataset, None, family_map) == expected


def test_select_family_globs_are_tried_in_sorted_order() -> None:
    # "re*" sorts before "re2-*", so it wins for re2-tt whatever the insertion order.
    assert select_family("re2-tt", None, FAMILY_MAP) == "other"
    assert select_family("re2-tt", None, dict(reversed(list(FAMILY_MAP.items())))) == "other"


def test_select_family_explicit_wins() -> None:
    assert select_family("re2-ob", "veyllab", FAMILY_MAP) == "veyllab"
    with pytest.raises(ConfigError):
        select_family("re2-ob", 3, FAMILY_MAP)
    with pytest.raises(ConfigError):
        select_family("x", None, {"x": 1})


def test_ai_arm_for() -> None:
    assert ai_arm_for("off", {"enabled": True, "mode": "brief"}) == "off"
    assert ai_arm_for("record", {"enabled": True, "mode": "brief"}) == "brief"
    assert ai_arm_for("replay", {"enabled": True, "mode": "investigate"}) == "investigate"
    assert ai_arm_for("record", {"enabled": False, "mode": "brief"}) == "off"
    assert ai_arm_for("record", {"enabled": True, "mode": "agent_only"}) is None
    with pytest.raises(ConfigError):
        ai_arm_for("record", {"enabled": True})


def test_write_then_load_is_canonical(tmp_path: Path) -> None:
    content = example_content()
    path = write_calibration(tmp_path, content)
    assert path == tmp_path / "veyllab.brief.oracle.foldA.json"
    data = path.read_bytes()
    assert data == canonical_json(content) + b"\n"
    ref = load_calibration(path)
    assert ref.family_id == "veyllab.brief.oracle.foldA"
    assert ref.sha256 == sha256_bytes(data)
    assert ref.content == Calibration.model_validate(content)
    assert calibration_bytes(ref.content) == data


def test_example_file_is_not_canonical_bytes(tmp_path: Path) -> None:
    # The pretty-printed contracts example is valid content but not the one valid byte form.
    path = tmp_path / "veyllab.brief.oracle.foldA.json"
    path.write_bytes(EXAMPLE.read_bytes())
    with pytest.raises(ConfigError, match="not canonical"):
        load_calibration(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.replace(b"\n", b"\r\n"),
        lambda b: b.rstrip(b"\n"),
        lambda b: b.replace(b'"alpha":0.1', b'"alpha":0.10'),
        lambda b: b.replace(b'"q_hat":0.291666667', b'"q_hat":1'),
    ],
)
def test_non_canonical_bytes_are_rejected(tmp_path: Path, mutate: Any) -> None:
    path = write_calibration(tmp_path, example_content())
    path.write_bytes(mutate(path.read_bytes()))
    with pytest.raises(ConfigError):
        load_calibration(path)


def test_invalid_content_and_wrong_stem(tmp_path: Path) -> None:
    bad = tmp_path / "veyllab.brief.oracle.foldA.json"
    bad.write_bytes(canonical_json({"family": "veyllab.brief.oracle.foldA"}) + b"\n")
    with pytest.raises(ConfigError, match="not a valid calibration"):
        load_calibration(bad)
    other = tmp_path / "synth.brief.oracle.foldA.json"
    other.write_bytes(calibration_bytes(Calibration.model_validate(example_content())))
    with pytest.raises(ConfigError, match=r"content\.family"):
        load_calibration(other)


def test_find_calibration(tmp_path: Path) -> None:
    write_calibration(tmp_path, example_content())
    fid = "veyllab.brief.oracle.foldA"
    found = find_calibration(tmp_path, fid, ai_arm="brief", alert_protocol="oracle")
    assert found is not None
    assert found.family_id == fid
    assert (
        find_calibration(tmp_path, "veyllab.off.oracle.foldA", ai_arm="off", alert_protocol="oracle") is None
    )


def test_find_calibration_is_case_sensitive_on_every_os(tmp_path: Path) -> None:
    """NTFS is case-insensitive; the lookup must not be (Linux would find no file)."""
    write_calibration(tmp_path, example_content())
    found = find_calibration(tmp_path, "veyllab.brief.oracle.FOLDa", ai_arm="brief", alert_protocol="oracle")
    assert found is None


def test_find_calibration_arm_or_protocol_mismatch_is_an_error(tmp_path: Path) -> None:
    # A file named for one arm whose content says another (bench bug): hard error, 03 §12.1.
    fid = "veyllab.off.oracle.foldA"
    content = Calibration.model_validate(example_content(family=fid))  # ai_arm stays "brief"
    (tmp_path / f"{fid}.json").write_bytes(calibration_bytes(content))
    with pytest.raises(ConfigError, match="ai_arm=brief"):
        find_calibration(tmp_path, fid, ai_arm="off", alert_protocol="oracle")


def test_ref_round_trips_through_the_lock_object(tmp_path: Path) -> None:
    ref = load_calibration(write_calibration(tmp_path, example_content()))
    lock_obj = json.loads(canonical_json(ref.lock_object()))
    assert ref_from_lock(lock_obj) == ref


def test_ref_checks_the_hash_against_the_content(tmp_path: Path) -> None:
    ref = load_calibration(write_calibration(tmp_path, example_content()))
    lock_obj = json.loads(canonical_json(ref.lock_object()))
    lock_obj["content"]["q_hat"] = 0.5
    with pytest.raises(ConfigError, match="does not match its content"):
        ref_from_lock(lock_obj)
    with pytest.raises(ConfigError):
        CalibrationRef(family_id="synth.off.oracle.foldA", sha256=ref.sha256, content=ref.content)
    with pytest.raises(ConfigError, match="invalid calibration entry"):
        ref_from_lock({"family_id": ref.family_id})


def test_parse_json_strict() -> None:
    assert parse_json_strict(b'{"a":1}', where="t") == {"a": 1}
    with pytest.raises(ConfigError, match="duplicate key 'a'"):
        parse_json_strict(b'{"a":1,"a":2}', where="t")
    with pytest.raises(ConfigError, match="NaN"):
        parse_json_strict(b'{"a":NaN}', where="t")
    with pytest.raises(ConfigError, match="not valid JSON"):
        parse_json_strict(b"{", where="t")
