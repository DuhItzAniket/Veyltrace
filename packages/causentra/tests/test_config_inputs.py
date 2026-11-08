"""Tests of the Causentra v1 configuration (09 §4) and input view (09 §2.1, §6)."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from veyltrace_causentra.config import Factors, config_from
from veyltrace_causentra.inputs import load_inputs
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import atom_id
from veyltrace_core.testing import make_context


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in cast(Mapping[str, object], value).items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_thaw(v) for v in cast(Sequence[object], value)]
    return value


def _sections() -> tuple[dict[str, Any], dict[str, Any]]:
    return _thaw(load_section_file("causentra")), _thaw(load_section_file("core"))


def test_repo_config_matches_09_4() -> None:
    c = config_from(*_sections())
    assert (c.alpha, c.factors) == (0.10, Factors(1.0, 0.85, 0.25, 1.0, 0.9))
    assert (c.mandatory, c.disabled, c.clip_low, c.clip_high) == (("T1", "T2", "T3", "T4"), (), -0.3, 0.3)
    assert (c.proposals_max, c.c_high, c.c_med, c.likely_max_set) == (5, 0.30, 0.15, 3)
    assert (c.t2_min_fraction, c.t3_min_path_fraction, c.uncalibrated_q_hat) == (1.0, 0.5, 0.0)
    assert (c.default_tau, c.asks_max, c.k_anom) == (round(math.log1p(3.0), 9), 5, 3.0)
    assert len(c.weights) == 10 and c.weight("zscore_above") == 0.10 and c.weight("on_critical_path") == 0.05


@pytest.mark.parametrize(
    ("dotted", "value", "match"),
    [
        ("alpha", 1.5, r"causentra\.alpha"),
        ("factors.fail_mandatory", -0.1, r"causentra\.factors\.fail_mandatory"),
        ("mandatory", ["T1", "T11"], r"causentra\.mandatory"),
        ("trials.disabled", "T1", r"causentra\.trials\.disabled"),
        ("claims.clip_low", 0.1, r"causentra\.claims\.clip_low"),
        ("predicates.silent.weight", "0.1", r"causentra\.predicates\.silent\.weight"),
        ("proposals.max", -1, r"causentra\.proposals\.max"),
        ("trials.T2.min_fraction", 2.0, r"causentra\.trials\.T2\.min_fraction"),
        ("no_fault.detector", "nsigma", r"causentra\.no_fault\.detector"),
        ("asks.max", True, r"causentra\.asks\.max"),
    ],
)
def test_bad_values_name_their_key(dotted: str, value: object, match: str) -> None:
    cfg, core = _sections()
    *parents, leaf = dotted.split(".")
    node = cfg
    for part in parents:
        node = node[part]
    node[leaf] = value
    with pytest.raises(ConfigError, match=match):
        config_from(cfg, core)


def test_trial_lists_are_in_numeric_order_and_weights_are_required() -> None:
    cfg, core = _sections()
    cfg["mandatory"] = ["T10", "T2", "T1"]
    assert config_from(cfg, core).mandatory == ("T1", "T2", "T10")
    del cfg["predicates"]["zscore_above"]
    with pytest.raises(ConfigError, match=r"predicates\.zscore_above"):
        config_from(cfg, core)


def _inputs(run_dir: Path) -> Any:
    ctx = make_context("causentra", run_dir, phase="main")
    return load_inputs(ctx, config_from(ctx.config, ctx.config.core))


def test_synth_inputs_follow_the_fixtures(synth01_dir: Path) -> None:
    got = _inputs(synth01_dir)
    assert list(got.ev.universe) == sorted(s.service for s in got.slate.all_scores)
    assert got.graph.universe == got.ev.universe
    alignment = io.read_model("alignment", synth01_dir, models.Alignment)
    assert got.tol_ms == alignment.tolerance_ns / 1e6
    onsets = io.read_model("onsets", synth01_dir, models.Onsets)
    assert got.entry_services == tuple(sorted(onsets.entry_services))
    assert (got.claims, got.proposals, got.q_hat, got.tau_nf, got.degraded) == (
        (),
        None,
        0.0,
        1.386294361,
        False,
    )
    assert got.causatrix.k == 5  # Causatrix's own config, for classify() (09 §3.9, §3.12)


def test_absent_optional_inputs_read_as_empty(synth01_dir: Path) -> None:
    for name in ("graph.edges", "alignment"):
        io.path_of(name, synth01_dir).unlink()
    got = _inputs(synth01_dir)
    assert (got.graph.edges, got.tol_ms, got.degraded) == ((), 0.0, False)
    assert sorted(n.split(": ")[1].split(" ")[0] for n in got.notes) == ["alignment", "graph.edges"]


def test_schema_invalid_proposals_count_as_none(synth01_dir: Path) -> None:
    io.path_of("proposals", synth01_dir).write_text('{"schema_version": "0.1.0"}\n', encoding="utf-8")
    got = _inputs(synth01_dir)
    assert got.proposals is None and got.degraded and "schema-invalid" in got.notes[0]


def test_claim_check_atoms_are_kept_apart(synth01_dir: Path) -> None:
    args = {"k": 4.0, "signal": "cpu"}
    aid = atom_id("claim_check", "cart", {"args": args, "predicate": "zscore_above"})
    claim = {"atom_id": aid, "candidate": "cart", "component": None, "kind": "claim_check", "unit": None}
    claim |= {
        "predicate": "zscore_above",
        "args_json": json.dumps(args, sort_keys=True, separators=(",", ":")),
    }
    claim |= {"value": 5.0, "window": "incident", "refs": [], "origin": "claim_check", "holds": True}
    claim["producer"] = "faultloom@1"
    io.write("evidence", [claim], synth01_dir)
    got = _inputs(synth01_dir)
    assert [(c.candidate, c.predicate, c.holds) for c in got.claims] == [("cart", "zscore_above", True)]
    assert got.ev.atoms == ()  # engine atoms only
