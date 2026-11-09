"""Tests for veyltrace_core.config: resolution, overrides, the lock, engine views, calibration
selection, config_dir discovery and the data root (core_api_spec §5; critic gaps on config)."""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts.models import ConfigLock
from veyltrace_core.calibration import UNCALIBRATED_SHA256, write_calibration
from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import (
    CONFIG_DIR_ENV,
    DATA_ENV,
    ENGINES,
    LOCK_SECTIONS,
    ResolvedConfig,
    check_relative_path,
    config_sha256,
    data_path,
    data_root,
    find_config_dir,
    load_config,
    load_section_file,
    parse_assignment,
    parse_assignments,
    resolve_config,
    section_sha256,
)
from veyltrace_core.errors import ArtifactMissing, ConfigError, UsageError
from veyltrace_core.hashing import sha256_bytes, sha256_json

REPO = Path(__file__).resolve().parents[3]
REPO_CONFIG = REPO / "config"
CAL_EXAMPLE = REPO / "contracts" / "examples" / "calibration.example.json"


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    """A copy of the repo's config/*.yaml (no calibration files) in a temp dir."""
    target = tmp_path / "config"
    target.mkdir()
    for path in sorted(REPO_CONFIG.glob("*.yaml")):
        shutil.copyfile(path, target / path.name)
    return target


def append_yaml(cfg_dir: Path, section: str, text: str) -> None:
    path = cfg_dir / f"{section}.yaml"
    body = path.read_text(encoding="utf-8")
    if body.rstrip().endswith("{}"):
        body = body.rstrip()[:-2] + "\n"
    path.write_text(body + text, encoding="utf-8", newline="\n")


def resolve(cfg_dir: Path, overrides: Mapping[str, object] | None = None, **kw: Any) -> ResolvedConfig:
    kw.setdefault("ai_mode", "off")
    return resolve_config(overrides or {}, config_dir=cfg_dir, **kw)


def calibration_content(family_id: str, ai_arm: str, protocol: str = "oracle") -> dict[str, Any]:
    content: dict[str, Any] = json.loads(CAL_EXAMPLE.read_bytes())
    content.update(family=family_id, ai_arm=ai_arm, alert_protocol=protocol)
    return content


# ---------------------------------------------------------------------------------------------
# Resolution and the lock


def test_repo_config_resolves() -> None:
    resolved = resolve_config(config_dir=REPO_CONFIG, ai_mode="off", dataset="synth")
    assert sorted(resolved.sections) == sorted(LOCK_SECTIONS)
    assert len(ENGINES) == 10
    assert "gateway" not in resolved.sections
    assert resolved.calibration is None  # the repo commits no calibration files yet


def test_lock_shape_and_bytes(cfg_dir: Path) -> None:
    resolved = resolve(cfg_dir)
    data = resolved.lock_bytes()
    assert data.endswith(b"}\n")
    obj = json.loads(data)
    ConfigLock.model_validate(obj)
    assert canonical_json(obj) + b"\n" == data
    assert obj["schema_version"] == "0.1.0"
    assert obj["calibration"] is None
    assert config_sha256(resolved) == sha256_bytes(data)
    assert section_sha256(resolved, "core") == sha256_json(obj["sections"]["core"])
    with pytest.raises(ConfigError):
        section_sha256(resolved, "gateway")


def _top_keys(cfg_dir: Path, section: str) -> set[str]:
    """The top-level keys a lane's real config file (copied into cfg_dir) already defines."""
    loaded = yaml.safe_load((cfg_dir / f"{section}.yaml").read_text(encoding="utf-8"))
    return set(loaded or {})


def test_environment_keys_stay_out_of_the_lock(cfg_dir: Path) -> None:
    # Append the probes only where the lane's file lacks them (05 §4 gives Causalith its own paths.*).
    probe_fetch = "fetch" not in _top_keys(cfg_dir, "infralume")
    probe_paths = "paths" not in _top_keys(cfg_dir, "causalith")
    if probe_fetch:
        append_yaml(cfg_dir, "infralume", "fetch:\n  mirror: https://example.invalid/x\n")
    if probe_paths:
        append_yaml(cfg_dir, "causalith", "paths:\n  k: 3\n")
    resolved = resolve(cfg_dir)
    lock = json.loads(resolved.lock_bytes())
    assert "paths" not in lock["sections"]["core"]
    assert "fetch" not in lock["sections"]["infralume"]
    assert b"VEYLTRACE_DATA" not in resolved.lock_bytes()
    # `paths` is environment only in core: causalith.paths.* are analysis keys kept in the lock.
    paths = lock["sections"]["causalith"]["paths"]
    assert paths == {"k": 3} if probe_paths else paths
    assert resolved.environment["core.paths"]["runs"] == "runs"
    fetch = resolved.environment["infralume.fetch"]
    assert fetch["mirror"] == "https://example.invalid/x" if probe_fetch else fetch


def test_config_dir_location_never_enters_the_lock(cfg_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere" / "config"
    shutil.copytree(cfg_dir, other)
    assert resolve(cfg_dir).lock_bytes() == resolve(other).lock_bytes()


def test_crlf_files_give_the_same_lock(cfg_dir: Path, tmp_path: Path) -> None:
    crlf = tmp_path / "crlf"
    shutil.copytree(cfg_dir, crlf)
    for path in sorted(crlf.glob("*.yaml")):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert resolve(cfg_dir).lock_bytes() == resolve(crlf).lock_bytes()


def test_record_and_replay_share_one_lock(cfg_dir: Path) -> None:
    record = resolve(cfg_dir, ai_mode="record", dataset="synth")
    replay = resolve(cfg_dir, ai_mode="replay", dataset="synth")
    assert config_sha256(record) == config_sha256(replay)


def test_ai_mode_is_not_a_config_key(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="unknown key"):
        resolve(cfg_dir, {"core.ai.mode": "record"})
    with pytest.raises(ConfigError, match="ai_mode"):
        resolve(cfg_dir, ai_mode="on")


def test_invalid_dataset(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="dataset"):
        resolve(cfg_dir, dataset="RE2_OB")


def test_off_stays_a_string_in_the_lock(cfg_dir: Path) -> None:
    # A new top-level key, so the test does not collide with the keys config/causatrix.yaml
    # declares (R-00 added fusion.method there; a duplicate key is a ConfigError).
    append_yaml(cfg_dir, "causatrix", "yaml12_probe:\n  method: off\n")
    assert resolve(cfg_dir).sections["causatrix"]["yaml12_probe"]["method"] == "off"


def test_duplicate_yaml_key_is_a_config_error(cfg_dir: Path) -> None:
    append_yaml(cfg_dir, "relentra", "zz_dup_probe: 1\nzz_dup_probe: 2\n")  # whatever keys the lane has
    with pytest.raises(ConfigError, match=r"relentra\.yaml: duplicate key 'zz_dup_probe'"):
        resolve(cfg_dir)


def test_missing_section_file_is_a_config_error(cfg_dir: Path) -> None:
    (cfg_dir / "llm.yaml").unlink()
    with pytest.raises(ConfigError, match=r"llm\.yaml"):
        resolve(cfg_dir)


def test_top_level_must_be_a_mapping(cfg_dir: Path) -> None:
    (cfg_dir / "causatrix.yaml").write_text("- a\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        resolve(cfg_dir)


def test_empty_file_is_an_empty_section(cfg_dir: Path) -> None:
    (cfg_dir / "causatrix.yaml").write_text("# nothing yet\n", encoding="utf-8")
    assert dict(resolve(cfg_dir).sections["causatrix"]) == {}


@pytest.mark.parametrize("value", [".nan", ".inf", "-.inf", "1.0e-10", "0.1234567891"])
def test_lossy_floats_are_rejected(cfg_dir: Path, value: str) -> None:
    append_yaml(cfg_dir, "causatrix", f"zz_float_probe: {value}\n")  # a key no lane defines
    with pytest.raises(ConfigError, match=r"causatrix\.zz_float_probe"):
        resolve(cfg_dir)


def test_floats_with_nine_decimals_are_kept_exactly(cfg_dir: Path) -> None:
    append_yaml(cfg_dir, "causatrix", "zz_float_probe:\n  eps: 1.0e-9\n  big: 1.0e+20\n  neg: -0.123456789\n")
    probe = resolve(cfg_dir).sections["causatrix"]["zz_float_probe"]
    assert (probe["eps"], probe["big"], probe["neg"]) == (1e-9, 1e20, -0.123456789)


# ---------------------------------------------------------------------------------------------
# Path-valued keys


@pytest.mark.parametrize(
    "value",
    [
        "/home/alice/overlay.parquet",
        "C:/Users/alice/overlay.parquet",
        "'C:\\Users\\alice\\overlay.parquet'",
        "overlays\\x\\events.parquet",
        "~/overlay.parquet",
        "../outside/events.parquet",
        "overlays//events.parquet",
        "${HOME}/events.parquet",
        "''",
        "3",
    ],
)
def test_bad_path_values_are_rejected(cfg_dir: Path, value: str) -> None:
    # Path keys are found by suffix at any depth, so a probe section no lane defines tests them.
    append_yaml(cfg_dir, "infralume", f"zz_path_probe:\n  overlay_path: {value}\n")
    with pytest.raises(ConfigError, match="overlay_path"):
        resolve(cfg_dir)


def test_relative_path_values_and_lists_are_accepted(cfg_dir: Path) -> None:
    append_yaml(
        cfg_dir,
        "infralume",
        "zz_path_probe:\n  overlay_path: overlays/exp-1/abc/events.parquet\n"
        "  extra_paths: [a/b.parquet, c.parquet]\n",
    )
    append_yaml(cfg_dir, "anomara", "zz_path_probe:\n  weights_path: null\n")
    section = resolve(cfg_dir).sections["infralume"]
    assert section["zz_path_probe"]["overlay_path"] == "overlays/exp-1/abc/events.parquet"
    append_yaml(cfg_dir, "causalith", "zz_path_probe:\n  static_dirs: [ok, /abs]\n")
    with pytest.raises(ConfigError, match=r"static_dirs\[1\]"):
        resolve(cfg_dir)


def test_backslashes_in_regex_strings_are_fine(cfg_dir: Path) -> None:
    # A key no lane defines, so the copy of the lane's real signalyth.yaml never gets a duplicate key.
    append_yaml(cfg_dir, "signalyth", "zz_regex_probe:\n  patterns: ['_total$', '\\d+_count$']\n")
    patterns = resolve(cfg_dir).sections["signalyth"]["zz_regex_probe"]["patterns"]
    assert patterns == ("_total$", "\\d+_count$")


def test_check_relative_path() -> None:
    assert check_relative_path("a/b.c", "k") == "a/b.c"
    for bad in ("", "/a", "a\\b", "D:x", "a/../b", "~a", "$X/a", "a//b"):
        with pytest.raises(ConfigError):
            check_relative_path(bad, "k")


# ---------------------------------------------------------------------------------------------
# Overrides


def test_overrides_replace_values(cfg_dir: Path) -> None:
    resolved = resolve(
        cfg_dir,
        {
            "core.alert.shift_s": -120,
            "core.alert.protocol": "detected",
            "infralume.sources.drop": ["events"],
            "core.windows.baseline_s": [-600, -60],
        },
    )
    core = resolved.sections["core"]
    assert core["alert"]["shift_s"] == -120
    assert core["alert"]["protocol"] == "detected"
    assert core["windows"]["baseline_s"] == (-600, -60)
    assert resolved.sections["infralume"]["sources"]["drop"] == ("events",)


def test_int_override_of_a_float_widens_and_hashes_the_same(cfg_dir: Path) -> None:
    as_int = resolve(cfg_dir, {"core.thresholds.anomaly_z": 4})
    as_float = resolve(cfg_dir, {"core.thresholds.anomaly_z": 4.0})
    value = as_int.sections["core"]["thresholds"]["anomaly_z"]
    assert value == 4.0
    assert isinstance(value, float)
    assert config_sha256(as_int) == config_sha256(as_float)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("core.alert.shift_s", 1.5),  # int key, float value
        ("core.alert.shift_s", 2.0),  # still a type change
        ("core.alert.shift_s", True),  # bool is not an int here
        ("core.alert.reject_hint_outside_span", 1),
        ("core.alert.protocol", 3),
        ("core.thresholds.anomaly_z", "3"),
        ("core.thresholds.anomaly_z", None),
        ("core.windows.baseline_s", "-600,-60"),
        ("core.windows.baseline_s", [-600.5, -60]),  # elements follow the int template
        ("core.alert", "oracle"),
    ],
)
def test_type_changing_overrides_are_rejected(cfg_dir: Path, key: str, value: object) -> None:
    with pytest.raises(ConfigError, match=r"expected|cannot"):
        resolve(cfg_dir, {key: value})


def test_null_base_accepts_any_type(cfg_dir: Path) -> None:
    resolved = resolve(
        cfg_dir, {"causentra.calibration.family": "veyllab", "llm.model.gguf_sha256": "a" * 64}
    )
    assert resolved.sections["causentra"]["calibration"]["family"] == "veyllab"


def test_map_override_replaces_whole(cfg_dir: Path) -> None:
    resolved = resolve(cfg_dir, {"causentra.calibration.family_map": {"re2.ob": "x"}})
    assert dict(resolved.sections["causentra"]["calibration"]["family_map"]) == {"re2.ob": "x"}
    resolved = resolve(cfg_dir, {"infralume.duckdb": {"threads": 1}})
    assert dict(resolved.sections["infralume"]["duckdb"]) == {"threads": 1}
    with pytest.raises(ConfigError, match=r"duckdb\.threads"):
        resolve(cfg_dir, {"infralume.duckdb": {"threads": "1"}})


@pytest.mark.parametrize(
    ("key", "match"),
    [
        ("core.alert.nope", "unknown key"),
        ("core.nope.x", "unknown key"),
        ("core.alert.protocol.x", "unknown key"),
        ("nosuch.x", "unknown section"),
        ("gateway.x", "unknown section"),
        ("core", "expected <section>.<key>"),
        ("core..alert", "expected <section>.<key>"),
    ],
)
def test_unknown_override_keys(cfg_dir: Path, key: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        resolve(cfg_dir, {key: 1})


def test_overlapping_overrides_are_rejected(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="overlap"):
        resolve(cfg_dir, {"core.alert": {"protocol": "oracle"}, "core.alert.shift_s": 5})


def test_overrides_are_validated_like_files(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="decimals"):
        resolve(cfg_dir, {"core.thresholds.anomaly_z": 3.0000000001})
    with pytest.raises(ConfigError, match="overlay_path"):
        append_yaml(cfg_dir, "infralume", "zz_path_probe:\n  overlay_path: null\n")
        resolve(cfg_dir, {"infralume.zz_path_probe.overlay_path": "C:\\data\\x.parquet"})
    with pytest.raises(ConfigError, match="not a JSON value"):
        resolve(cfg_dir, {"core.alert.protocol": b"oracle"})


def test_environment_keys_can_be_overridden(cfg_dir: Path) -> None:
    resolved = resolve(cfg_dir, {"core.paths.runs": "other-runs"})
    assert resolved.environment["core.paths"]["runs"] == "other-runs"
    assert resolved.lock_bytes() == resolve(cfg_dir).lock_bytes()


def test_with_overrides_matches_resolve(cfg_dir: Path) -> None:
    base = resolve(cfg_dir, dataset="synth")
    assert base.with_overrides({}) is base
    direct = resolve(cfg_dir, {"core.alert.shift_s": 60}, dataset="synth")
    assert base.with_overrides({"core.alert.shift_s": 60}) == direct


def test_parse_assignment() -> None:
    assert parse_assignment("core.alert.shift_s=-120") == ("core.alert.shift_s", -120)
    assert parse_assignment("causatrix.fusion.method=off") == ("causatrix.fusion.method", "off")
    assert parse_assignment("infralume.sources.drop=[events, logs]") == (
        "infralume.sources.drop",
        ("events", "logs"),
    )
    assert parse_assignment("x.y=1e-6") == ("x.y", 1e-6)
    assert parse_assignment("x.y=a=b") == ("x.y", "a=b")
    assert parse_assignment("x.y=") == ("x.y", None)
    for bad in ("novalue", "=3", "x.y=[1,"):
        with pytest.raises(UsageError):
            parse_assignment(bad)
    assert parse_assignments(["a.b=1", "a.c=x"]) == {"a.b": 1, "a.c": "x"}
    with pytest.raises(UsageError, match="twice"):
        parse_assignments(["a.b=1", "a.b=2"])


# ---------------------------------------------------------------------------------------------
# Engine views


def test_engine_config_is_a_read_only_view_from_the_lock(cfg_dir: Path) -> None:
    resolved = resolve(cfg_dir)
    cfg = resolved.engine("infralume")
    assert cfg.engine == "infralume"
    assert cfg["duckdb"]["threads"] == 1
    section = yaml.safe_load((cfg_dir / "infralume.yaml").read_text(encoding="utf-8"))
    assert sorted(cfg) == sorted(section) and len(cfg) == len(section)  # whatever keys the lane adds
    assert cfg.core["alert"]["protocol"] == "oracle"
    assert cfg.section("causalith")["duckdb"]["memory_limit"] == "2GB"
    assert cfg.get_path("duckdb.memory_limit") == "1GB"
    assert cfg.get_path("duckdb.nope", None) is None
    with pytest.raises(ConfigError, match="no such config key"):
        cfg.get_path("duckdb.nope")
    with pytest.raises(ConfigError):
        cfg.section("gateway")
    with pytest.raises(TypeError):
        cfg["duckdb"]["threads"] = 4  # type: ignore[index]  # proving the view is read-only
    assert cfg.for_engine("signalyth")["duckdb"]["memory_limit"] == "1.5GB"
    assert "infralume" in repr(cfg)
    with pytest.raises(ConfigError, match="no config section"):
        resolved.engine("gateway")


def test_engine_values_are_the_lock_values(cfg_dir: Path) -> None:
    resolved = resolve(cfg_dir)
    replayed = ResolvedConfig.from_lock_bytes(resolved.lock_bytes())
    for name in LOCK_SECTIONS:
        fresh, again = resolved.engine(name), replayed.engine(name)
        assert canonical_json(dict(fresh)) == canonical_json(dict(again))
        assert canonical_json(dict(fresh)) == canonical_json(
            json.loads(resolved.lock_bytes())["sections"][name]
        )


def test_non_causentra_engines_get_no_calibration_content(cfg_dir: Path) -> None:
    cfg = resolve(cfg_dir, dataset="synth").engine("causentra")
    assert cfg.calibration is None
    assert cfg.calibration_family == "uncalibrated"
    assert cfg.calibration_sha256 == UNCALIBRATED_SHA256


# ---------------------------------------------------------------------------------------------
# from_lock


def test_from_lock_round_trip(cfg_dir: Path, tmp_path: Path) -> None:
    resolved = resolve(cfg_dir, {"core.alert.shift_s": 30})
    path = tmp_path / "config.lock.json"
    path.write_bytes(resolved.lock_bytes())
    again = ResolvedConfig.from_lock(path)
    assert again == resolved
    assert hash(again) == hash(resolved)
    assert again.source is None
    assert dict(again.environment) == {}
    assert config_sha256(again) == sha256_bytes(path.read_bytes())


def test_from_lock_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ArtifactMissing):
        ResolvedConfig.from_lock(tmp_path / "config.lock.json")


def test_from_lock_rejects_non_canonical_and_invalid_locks(cfg_dir: Path) -> None:
    data = resolve(cfg_dir).lock_bytes()
    obj = json.loads(data)
    pretty = json.dumps(obj, indent=2).encode()
    with pytest.raises(ConfigError, match="canonical"):
        ResolvedConfig.from_lock_bytes(pretty)
    with pytest.raises(ConfigError, match="canonical"):
        ResolvedConfig.from_lock_bytes(data.replace(b"\n", b"\r\n"))
    with pytest.raises(ConfigError, match="duplicate key"):
        ResolvedConfig.from_lock_bytes(b'{"schema_version":"0.1.0","schema_version":"0.1.0"}\n')
    missing = dict(obj, sections={k: v for k, v in obj["sections"].items() if k != "llm"})
    with pytest.raises(ConfigError, match="exactly"):
        ResolvedConfig.from_lock_bytes(canonical_json(missing) + b"\n")
    extra = dict(obj, sections={**obj["sections"], "gateway": {}})
    with pytest.raises(ConfigError, match="exactly"):
        ResolvedConfig.from_lock_bytes(canonical_json(extra) + b"\n")
    leaked = json.loads(data)
    leaked["sections"]["core"]["paths"] = {"runs": "runs"}
    with pytest.raises(ConfigError, match="environment subtree"):
        ResolvedConfig.from_lock_bytes(canonical_json(leaked) + b"\n")
    with pytest.raises(ConfigError, match="not a valid config lock"):
        ResolvedConfig.from_lock_bytes(canonical_json(dict(obj, schema_version="9.9.9")) + b"\n")


def test_from_lock_rejects_bad_paths_inside_the_lock(cfg_dir: Path) -> None:
    obj = json.loads(resolve(cfg_dir).lock_bytes())
    obj["sections"]["infralume"]["events"] = {"overlay_path": "/home/alice/x.parquet"}
    with pytest.raises(ConfigError, match="overlay_path"):
        ResolvedConfig.from_lock_bytes(canonical_json(obj) + b"\n")


def test_with_overrides_on_a_lock(cfg_dir: Path) -> None:
    replayed = ResolvedConfig.from_lock_bytes(resolve(cfg_dir).lock_bytes())
    shifted = replayed.with_overrides({"core.alert.shift_s": 60})
    assert shifted.sections["core"]["alert"]["shift_s"] == 60
    with pytest.raises(ConfigError, match="calibration selection"):
        replayed.with_overrides({"core.alert.protocol": "detected"})
    with pytest.raises(ConfigError, match="unknown key"):
        replayed.with_overrides({"core.paths.runs": "x"})


# ---------------------------------------------------------------------------------------------
# Calibration selection


def test_calibration_is_selected_loaded_and_locked(cfg_dir: Path, tmp_path: Path) -> None:
    fid = "synth.off.oracle.foldA"
    path = write_calibration(cfg_dir / "calibration", calibration_content(fid, "off"))
    resolved = resolve(cfg_dir, dataset="synth")
    assert resolved.calibration is not None
    assert resolved.calibration.family_id == fid
    assert resolved.calibration.sha256 == sha256_bytes(path.read_bytes())
    cfg = resolved.engine("causentra")
    assert cfg.calibration is not None
    assert cfg.calibration.q_hat == pytest.approx(0.291666667)
    assert cfg.calibration_family == fid
    assert cfg.calibration_sha256 == resolved.calibration.sha256
    assert resolved.engine("causivra").calibration is None
    assert resolved.engine("causivra").calibration_family == fid
    lock = json.loads(resolved.lock_bytes())
    assert lock["calibration"]["family_id"] == fid
    assert lock["calibration"]["sha256"] == resolved.calibration.sha256
    # Replay needs only the lock: delete the file and rebuild.
    path.unlink()
    replayed = ResolvedConfig.from_lock_bytes(resolved.lock_bytes())
    assert replayed.engine("causentra").calibration == cfg.calibration
    assert config_sha256(replayed) == config_sha256(resolved)
    assert resolve(cfg_dir, dataset="synth").calibration is None


def test_calibration_changes_config_sha(cfg_dir: Path) -> None:
    without = config_sha256(resolve(cfg_dir, dataset="synth"))
    write_calibration(cfg_dir / "calibration", calibration_content("synth.off.oracle.foldA", "off"))
    assert config_sha256(resolve(cfg_dir, dataset="synth")) != without
    assert config_sha256(resolve(cfg_dir)) == without  # no dataset: no calibration choice


@pytest.mark.parametrize(
    ("dataset", "ai_mode", "overrides", "family_id"),
    [
        ("synth", "record", {}, "synth.brief.oracle.foldA"),
        ("synth", "replay", {"relentra.mode": "investigate"}, "synth.investigate.oracle.foldA"),
        ("synth", "record", {"relentra.enabled": False}, "synth.off.oracle.foldA"),
        ("re2-ob", "off", {}, "rcaeval-re2.off.oracle.foldA"),
        (
            "re2-ob",
            "off",
            {"causentra.calibration.family": "rcaeval-re2-ob"},
            "rcaeval-re2-ob.off.oracle.foldA",
        ),
        ("re2-ob", "off", {"causentra.calibration.fold": "loso-ob"}, "rcaeval-re2.off.oracle.loso-ob"),
        ("synth", "off", {"core.alert.protocol": "detected"}, "synth.off.detected.foldA"),
    ],
)
def test_family_id_selection(
    cfg_dir: Path, dataset: str, ai_mode: str, overrides: dict[str, object], family_id: str
) -> None:
    arm, protocol = family_id.split(".")[1:3]
    write_calibration(cfg_dir / "calibration", calibration_content(family_id, arm, protocol))
    resolved = resolve(cfg_dir, overrides, dataset=dataset, ai_mode=ai_mode)
    assert resolved.calibration is not None
    assert resolved.calibration.family_id == family_id


def test_no_family_or_no_arm_is_uncalibrated(cfg_dir: Path) -> None:
    assert resolve(cfg_dir, dataset="unknown-set").calibration is None
    resolved = resolve(cfg_dir, {"relentra.mode": "agent_only"}, dataset="synth", ai_mode="record")
    assert resolved.calibration is None


def test_calibration_arm_mismatch_is_a_config_error(cfg_dir: Path) -> None:
    fid = "synth.off.oracle.foldA"
    write_calibration(cfg_dir / "calibration", calibration_content(fid, "off"))
    content = calibration_content(fid, "off")
    content["ai_arm"] = "brief"
    from veyltrace_contracts.models import Calibration
    from veyltrace_core.calibration import calibration_bytes

    (cfg_dir / "calibration" / f"{fid}.json").write_bytes(
        calibration_bytes(Calibration.model_validate(content))
    )
    with pytest.raises(ConfigError, match="ai_arm=brief"):
        resolve(cfg_dir, dataset="synth")


def test_bad_calibration_keys(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="fold"):
        resolve(cfg_dir, {"causentra.calibration.fold": "fold.A"}, dataset="synth")
    with pytest.raises(ConfigError, match="family"):
        resolve(cfg_dir, {"causentra.calibration.family": "Not Valid"}, dataset="synth")


def test_with_overrides_reselects_calibration(cfg_dir: Path) -> None:
    write_calibration(
        cfg_dir / "calibration", calibration_content("synth.off.detected.foldA", "off", "detected")
    )
    base = resolve(cfg_dir, dataset="synth")
    assert base.calibration is None
    detected = base.with_overrides({"core.alert.protocol": "detected"})
    assert detected.calibration is not None
    assert detected.calibration.family_id == "synth.off.detected.foldA"


# ---------------------------------------------------------------------------------------------
# Config dir discovery, section files, data root


def test_find_config_dir_walks_up(cfg_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
    deep = cfg_dir.parent / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert find_config_dir() == cfg_dir.resolve()
    assert find_config_dir(cfg_dir.parent) == cfg_dir.resolve()
    assert load_config("core").engine == "core"


def test_find_config_dir_env_wins(cfg_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(cfg_dir))
    monkeypatch.chdir(REPO)
    assert find_config_dir() == cfg_dir.resolve()
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "nowhere"))
    with pytest.raises(ConfigError, match=CONFIG_DIR_ENV):
        find_config_dir()


def test_find_config_dir_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
    with pytest.raises(ConfigError, match=r"no config/core\.yaml"):
        find_config_dir(tmp_path)
    with pytest.raises(ConfigError, match=r"has no core\.yaml"):
        resolve_config(config_dir=tmp_path, ai_mode="off")


def test_load_section_file(cfg_dir: Path) -> None:
    gateway = load_section_file("gateway", config_dir=cfg_dir)
    assert dict(gateway) == {}
    core = load_section_file("core", config_dir=cfg_dir)
    assert core["paths"]["runs"] == "runs" and "data" not in core["paths"]  # no dead keys
    with pytest.raises(ConfigError):
        load_section_file("../core", config_dir=cfg_dir)


def test_load_config(cfg_dir: Path) -> None:
    cfg = load_config("anomara", {"anomara.duckdb.threads": 2}, config_dir=cfg_dir)
    assert cfg["duckdb"]["threads"] == 2


def test_data_root_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_ENV, str(tmp_path / "data"))
    assert data_root() == (tmp_path / "data").resolve()
    assert (
        data_path("overlays/x/events.parquet")
        == (tmp_path / "data").resolve() / "overlays" / "x" / "events.parquet"
    )
    with pytest.raises(ConfigError):
        data_path("/abs/x")


def test_data_root_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert data_root() == (tmp_path / "veyltrace-data").resolve()


def test_data_root_inside_a_git_work_tree_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setenv(DATA_ENV, str(tmp_path / "repo" / "data"))
    with pytest.raises(ConfigError, match="inside the git work tree"):
        data_root()
    monkeypatch.setenv(DATA_ENV, str(REPO / "runs-data"))
    with pytest.raises(ConfigError, match="inside the git work tree"):
        data_root()


# ---------------------------------------------------------------------------------------------
# Property: the lock is lossless for every float it accepts


_BASE = resolve_config(config_dir=REPO_CONFIG, ai_mode="off")


@given(st.floats(allow_nan=True, allow_infinity=True) | st.integers(-(2**53), 2**53))
def test_accepted_numbers_survive_the_lock_exactly(value: float | int) -> None:
    key = "core.thresholds.anomaly_z"
    lossless = math.isfinite(value) and round(float(value), 9) == float(value)
    if not lossless:
        with pytest.raises(ConfigError):
            _BASE.with_overrides({key: value})
        return
    resolved = _BASE.with_overrides({key: value})
    got = resolved.engine("core")["thresholds"]["anomaly_z"]
    assert isinstance(got, float)
    assert got == float(value)
    replayed = ResolvedConfig.from_lock_bytes(resolved.lock_bytes())
    assert replayed.engine("core")["thresholds"]["anomaly_z"] == got
    assert config_sha256(replayed) == config_sha256(resolved)


def test_lock_rejects_url_credentials_and_machine_paths_under_any_key() -> None:
    """config.lock.json is copied into the receipt: no secrets, no machine paths (any key)."""
    from veyltrace_core import config as cfg

    with pytest.raises(ConfigError, match="credentials"):
        resolve_config({"llm.base_url": "https://alice:sk-live-123@api.example.com/v1"}, ai_mode="off")
    for value in ("/home/u/x", "C:/Users/x", r"C:\Users\x", "~/x", r"\\server\share"):
        with pytest.raises(ConfigError, match="machine path"):
            cfg._check_lock_string(value, "x.y")  # pyright: ignore[reportPrivateUsage] - unit under test
    for value in ("http://127.0.0.1:11434", "qwen2.5:7b", "re2-*", "relative/path"):
        cfg._check_lock_string(value, "x.y")  # pyright: ignore[reportPrivateUsage] - unit under test


def test_fetch_subtrees_at_any_depth_stay_out_of_the_lock() -> None:
    from veyltrace_core import config as cfg

    tree = {"infralume": {"sources": {"drop": [], "fetch": {"url": "https://x"}}, "fetch": {"a": 1}}}
    sections, environment = cfg._split_environment(tree)  # pyright: ignore[reportPrivateUsage]
    assert sections == {"infralume": {"sources": {"drop": []}}}
    assert set(environment) == {"infralume.fetch", "infralume.sources.fetch"}
