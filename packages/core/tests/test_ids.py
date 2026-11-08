"""ids: the 03 §1 identifier definitions, pinned by the spec's test vectors."""

from __future__ import annotations

import hashlib
from typing import Any, get_args

import pytest

from veyltrace_contracts.models import AiMode
from veyltrace_core.hashing import sha256_json
from veyltrace_core.ids import (
    AI_MODES,
    atom_id,
    case_id,
    derived_run_id,
    dirty_commit,
    is_atom_id,
    is_case_id,
    is_code_commit,
    is_run_id,
    run_id,
    short_id,
    snapshot_id,
)

SHA = "0" * 64
COMMIT = "150aecd" + "0" * 33


# FaultLoom atom vectors (06 §3.8; core_api_spec §1). int k=4 and float k=4.0 must differ.
@pytest.mark.parametrize(
    ("kind", "candidate", "args", "expected"),
    [
        (
            "internal_anomaly",
            "checkoutservice",
            {"detector": "robust_z", "family": "cpu", "source": "metrics", "window": "incident"},
            "Eff7aaef775",
        ),
        (
            "claim_check",
            "checkoutservice",
            {"args": {"k": 4.0, "signal": "cpu"}, "predicate": "zscore_above"},
            "E7d69a580cc",
        ),
        (
            "claim_check",
            "checkoutservice",
            {"args": {"k": 4, "signal": "cpu"}, "predicate": "zscore_above"},
            "E46c52be355",
        ),
    ],
)
def test_atom_id_vectors(kind: str, candidate: str, args: dict[str, Any], expected: str) -> None:
    assert atom_id(kind, candidate, args) == expected
    assert is_atom_id(expected)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("synth-01", "59e0d31bcc42"),
        ("synth-02", "0ad66f75c9ac"),
        ("synth-03", "067c1ba0c360"),
        ("synth-04", "c27d3af40954"),
        ("synth-05", "3263e227fcbe"),
    ],
)
def test_synth_case_ids(name: str, expected: str) -> None:
    assert case_id(name) == expected
    assert is_case_id(expected)


def test_case_id_is_verbatim_utf8() -> None:
    key = "RE2-OB/checkoutservice_cpu/1 → é"
    assert case_id(key) == hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    assert case_id("Synth-01") != case_id("synth-01")  # no case folding or other normalisation
    with pytest.raises(ValueError):
        case_id("")


def test_ai_modes_are_the_contract_vocabulary() -> None:
    assert AI_MODES == get_args(AiMode) == ("off", "record", "replay")


def test_run_id_definition_and_pin() -> None:
    cid = case_id("synth-01")
    expected = hashlib.sha256(f'["{cid}","{SHA}","fixture","off"]'.encode()).hexdigest()[:16]
    assert run_id(cid, SHA, "fixture", "off") == expected == "7f2482208e21079b"
    assert is_run_id(expected)


def test_run_id_changes_with_every_input() -> None:
    cid = case_id("synth-01")
    base = run_id(cid, SHA, COMMIT, "off")
    variants = {
        run_id(case_id("synth-02"), SHA, COMMIT, "off"),
        run_id(cid, "1" * 64, COMMIT, "off"),
        run_id(cid, SHA, dirty_commit(COMMIT, "a" * 64), "off"),
        run_id(cid, SHA, COMMIT, "record"),
    }
    assert base not in variants
    assert len(variants) == len(["case", "config", "commit", "mode"])


@pytest.mark.parametrize(
    "args",
    [
        ("59E0D31BCC42", SHA, "fixture", "off"),
        ("59e0d31bcc42", "abc", "fixture", "off"),
        ("59e0d31bcc42", SHA, "HEAD", "off"),
        ("59e0d31bcc42", SHA, "fixture", "on"),
    ],
)
def test_run_id_validates_inputs(args: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError):
        run_id(*args)


def test_dirty_commit() -> None:
    dirty = dirty_commit(COMMIT, "abcdef0123456789" + "0" * 48)
    assert dirty == f"{COMMIT}+dirty.abcdef012345"
    assert is_code_commit(dirty)
    for good in (COMMIT, "f" * 64, "fixture", "unknown"):
        assert is_code_commit(good)
    for bad in ("HEAD", COMMIT[:39], f"{COMMIT}+dirty.xyz", f"{COMMIT}\n", ""):
        assert not is_code_commit(bad)
    with pytest.raises(ValueError):
        dirty_commit(dirty, "a" * 64)  # already dirty
    with pytest.raises(ValueError):
        dirty_commit(COMMIT, "short")


def test_derived_run_id() -> None:
    base = run_id(case_id("synth-01"), SHA, "fixture", "off")
    proposal = {"hypothesis": {"service": "cart"}, "claims": []}
    derived = derived_run_id(base, proposal)
    assert derived == f"{base}-x{sha256_json(proposal)[:12]}"
    assert is_run_id(derived)
    with pytest.raises(ValueError):
        derived_run_id(derived, proposal)  # derived ids are not derived again


@pytest.mark.parametrize(
    ("value", "case_ok", "run_ok"),
    [
        ("59e0d31bcc42", True, False),
        ("59e0d31bcc42\n", False, False),  # `$` would accept a trailing newline; fullmatch does not
        ("7f2482208e21079b", False, True),
        ("7f2482208e21079b-x0123456789ab", False, True),
        ("7f2482208e21079b-x0123", False, False),
        ("7F2482208E21079B", False, False),
        (None, False, False),
        (12, False, False),
    ],
)
def test_id_predicates(value: object, case_ok: bool, run_ok: bool) -> None:
    assert is_case_id(value) is case_ok
    assert is_run_id(value) is run_ok


def test_short_id() -> None:
    assert short_id("T", 8, ["cart", "GET /cart <*>"]) == "T" + sha256_json(["cart", "GET /cart <*>"])[:8]
    assert short_id("C", 10, {"t_ns": 1}) == "C" + sha256_json({"t_ns": 1})[:10]
    for n in (0, 65, True):
        with pytest.raises(ValueError):
            short_id("X", n, [])


def test_snapshot_id_sorts_hashes() -> None:
    hashes = ["b" * 64, "a" * 64]
    expected = sha256_json([sorted(hashes), 1_700_000_000_000_000_000])[:32]
    assert snapshot_id(hashes, 1_700_000_000_000_000_000) == expected
    assert snapshot_id(list(reversed(hashes)), 1_700_000_000_000_000_000) == expected
    with pytest.raises(TypeError):
        snapshot_id(hashes, 1.0)  # pyright: ignore[reportArgumentType]  # deliberate: tests the runtime guard
    with pytest.raises(ValueError):
        snapshot_id(["nope"], 1)
    with pytest.raises(TypeError):
        snapshot_id("a" * 64, 1)
