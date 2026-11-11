"""Unit tests of the input view's alignment and refs, `silence` atoms and `atoms.disabled` (06 §2.1,
§3.3, §3.4, §9), on hand-built views."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import make_context
from veyltrace_faultloom.api import run
from veyltrace_faultloom.atoms import KINDS, drop_disabled
from veyltrace_faultloom.inputs import align, row_ref
from veyltrace_faultloom.onset import silence_atoms

WINDOW = '{"window":"incident"}'


# --- inputs: alignment and refs ---------------------------------------------------------------
def test_align_prefers_the_service_offset_then_the_source_offset() -> None:
    offsets = {("metrics", "a"): 5, ("metrics", None): 2, ("logs", None): -1}
    assert align(100, "metrics", "a", offsets) == 105
    assert align(100, "metrics", "b", offsets) == 102
    assert align(100, "traces", "a", offsets) == 100  # no row: + 0 (06 §2.1)
    assert align(None, None, "a", offsets) is None


def test_row_ref_hashes_the_whole_row() -> None:
    # 06 §3.3: <table>#<first 12 hex of sha256(canonical_json(row))>; key order does not matter.
    ref = row_ref("graph.edges", {"src": "a", "dst": "b", "weight": 1.0})
    assert ref == row_ref("graph.edges", {"weight": 1.0, "dst": "b", "src": "a"})
    assert ref.startswith("graph.edges#") and len(ref.split("#")[1]) == 12
    assert ref != row_ref("graph.edges", {"src": "a", "dst": "b", "weight": 0.5})


# --- silence ----------------------------------------------------------------------------------
def test_silence_is_one_for_a_silent_onset_entry(hm: Any) -> None:
    v = hm.view(onsets=(hm.onset("a", silent=True), hm.onset("b"), hm.onset("zz", silent=True)))
    atoms = {a["candidate"]: a for a in silence_atoms(v)}  # zz is outside U: no atom
    assert (atoms["a"]["value"], atoms["a"]["refs"], atoms["a"]["args_json"]) == (1.0, ["onsets#a"], WINDOW)
    assert (atoms["b"]["value"], atoms["b"]["refs"]) == (0.0, ["onsets#b"])
    assert set(atoms) == {"a", "b"}  # c is neither in onsets nor in anomalies: no atom (06 §6)


def test_silence_detector_above_threshold_makes_it_one(hm: Any) -> None:
    rows = (
        hm.anomaly("c|c-2|errors|logs", "internal", "silence", score=1.0, above=True),
        hm.anomaly("c|c-1|errors|logs", "internal", "silence", score=0.0),
        hm.anomaly("b|b|errors|logs", "internal", "silence", score=0.0),
        hm.anomaly("a|a|cpu|metrics", "internal", "robust_z", score=9.0),
    )
    atoms = {a["candidate"]: a for a in silence_atoms(hm.view(anomalies=rows))}
    c = atoms["c"]
    assert (c["value"], c["refs"], c["component"]) == (1.0, ["c|c-2|errors|logs"], "c-2")
    assert (atoms["b"]["value"], atoms["b"]["refs"]) == (0.0, ["b|b|errors|logs"])
    # a appears in anomalies (another detector): an atom with value 0 and no silence refs.
    assert (atoms["a"]["value"], atoms["a"]["refs"]) == (0.0, [])


def test_a_silent_entry_cites_the_entry_and_the_silent_series(hm: Any) -> None:
    rows = (hm.anomaly("a|a-1|errors|logs", "internal", "silence", score=1.0, above=True),)
    (atom,) = silence_atoms(hm.view(onsets=(hm.onset("a", silent=True),), anomalies=rows))
    assert (atom["value"], atom["refs"], atom["component"]) == (1.0, ["a|a-1|errors|logs", "onsets#a"], None)


# --- atoms.disabled ---------------------------------------------------------------------------
def test_disabled_kinds_are_dropped_and_unknown_kinds_rejected(hm: Any) -> None:
    atoms = silence_atoms(hm.view(onsets=(hm.onset("a", silent=True),)))
    assert drop_disabled(atoms, ["silence"]) == []
    assert drop_disabled(atoms, ["spectrum"]) == atoms == drop_disabled(atoms, [])
    with pytest.raises(ConfigError, match="not atom kinds"):
        drop_disabled(atoms, ["silense"])
    assert len(KINDS) == 15


def test_engine_pass_applies_atoms_disabled(main_dir: Path) -> None:
    off = run(make_context("faultloom", main_dir, overrides={"faultloom.atoms.disabled": ["silence"]}))
    on = run(make_context("faultloom", main_dir))
    assert on.metrics["atoms.silence"] > 0 and off.metrics["atoms.silence"] == 0
    with pytest.raises(ConfigError):
        run(make_context("faultloom", main_dir, overrides={"faultloom.atoms.disabled": ["nope"]}))
