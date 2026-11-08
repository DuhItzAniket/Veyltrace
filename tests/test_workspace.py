"""Workspace skeleton invariants (R-02 bootstrap): members, package layout, entry points, config files.

Why: the bootstrap PR turns on every CI job at once. A missing workspace member, an unregistered
engine, a package `__init__` that imports something, or a config file without its owner header
must fail here with a clear message, not as an import error deep inside the pipeline.
These tests read files and installed distribution metadata only; they never import the engine
stubs, which depend on core modules written later in R-02.
"""

from __future__ import annotations

import ast
import os
import tomllib
from importlib.metadata import distribution, entry_points
from pathlib import Path
from typing import Any

import pytest
import yaml

from veyltrace_contracts.predicates import PREDICATES

ROOT = Path(__file__).resolve().parents[1]

# The ten engines in pipeline order (AGENTS §1) and the other workspace packages (02 §8).
ENGINES = (
    "infralume",
    "signalyth",
    "anomara",
    "causync",
    "causalith",
    "faultloom",
    "causatrix",
    "relentra",
    "causentra",
    "causivra",
)
PACKAGES = ("core", *ENGINES, "llm", "gateway")
CONFIG_SECTIONS = ("core", *ENGINES, "llm", "gateway")
VERSION = "0.1.0"
NUMERIC_PARAM_TYPES = ("float", "int")
RUN_STUB_ARITY = 2  # run_stub(ctx, engine_name)
# Engines whose api.run no longer calls core's R-02 bootstrap `run_stub(ctx, name)` because the
# owning lane replaced it with the package's own implementation (R-00 Reason stubs, #9; X-00 Relentra, #102).
PACKAGE_OWNED = frozenset({"faultloom", "causatrix", "causentra", "relentra"})

# 03 §7, "Default weight" column of the predicate library table.
DEFAULT_WEIGHTS = {
    "zscore_above": 0.10,
    "onset_before": 0.10,
    "edge_anomalous": 0.10,
    "self_time_share_above": 0.10,
    "change_before_onset": 0.10,
    "template_new_in_incident": 0.05,
    "error_rate_above": 0.05,
    "silent": 0.10,
    "on_critical_path": 0.05,
    "peer_gap_above": 0.10,
}


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_bytes().decode("utf-8"))


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_bytes())


def _package_dir(name: str) -> Path:
    return ROOT / "bench" if name == "bench" else ROOT / "packages" / name


def test_root_is_a_virtual_workspace_with_all_members() -> None:
    root = _toml(ROOT / "pyproject.toml")
    assert "project" not in root, "the root must stay a virtual workspace (nothing is built from it)"
    members = root["tool"]["uv"]["workspace"]["members"]
    expected = [f"packages/{p}" for p in PACKAGES] + ["bench", "contracts/generated/python"]
    assert sorted(members) == sorted(expected)
    for member in members:
        assert (ROOT / member / "pyproject.toml").is_file(), member


@pytest.mark.parametrize("name", [*PACKAGES, "bench"])
def test_package_metadata(name: str) -> None:
    meta = _toml(_package_dir(name) / "pyproject.toml")
    project = meta["project"]
    assert project["name"] == f"veyltrace-{name}"
    assert project["version"] == VERSION
    assert project["requires-python"] == ">=3.12"
    assert meta["build-system"]["build-backend"] == "hatchling.build"
    assert meta["tool"]["veyltrace"]["isolation"]["allow"] == []
    deps = [d for d in project["dependencies"] if d.startswith("veyltrace-")]
    expected_deps = ["veyltrace-contracts"] if name == "core" else ["veyltrace-core", "veyltrace-contracts"]
    assert sorted(deps) == sorted(expected_deps)
    sources = meta["tool"]["uv"]["sources"]
    assert all(sources[d] == {"workspace": True} for d in expected_deps)
    module = _package_dir(name) / "src" / f"veyltrace_{name}"
    assert meta["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [f"src/veyltrace_{name}"]
    assert (module / "py.typed").is_file()


@pytest.mark.parametrize("name", [*PACKAGES, "bench"])
def test_package_init_is_import_free(name: str) -> None:
    path = _package_dir(name) / "src" / f"veyltrace_{name}" / "__init__.py"
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    assert ast.get_docstring(tree), f"{path}: missing module docstring"
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]
    assert not imports, f"{path}: package __init__ must stay import-free (02 §9 isolation)"
    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert constants.get("__version__") == VERSION
    if name != "core":
        assert isinstance(constants.get("ALGO_VERSION"), str)


def test_engine_entry_points_are_registered() -> None:
    found = {ep.name: ep.value for ep in entry_points(group="veyltrace.engines")}
    assert found == {e: f"veyltrace_{e}.api:run" for e in ENGINES}


@pytest.mark.parametrize("engine", ENGINES)
def test_engine_api_stub_shape(engine: str) -> None:
    path = ROOT / "packages" / engine / "src" / f"veyltrace_{engine}" / "api.py"
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    runs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"]
    assert len(runs) == 1, f"{path}: exactly one top-level run()"
    assert [a.arg for a in runs[0].args.args] == ["ctx"]
    if engine in PACKAGE_OWNED:
        # The package's own implementation: core's bootstrap placeholder must be gone entirely.
        core_stubs = [
            n
            for n in ast.walk(tree)
            if (isinstance(n, ast.ImportFrom) and n.module == "veyltrace_core.stubs")
            or (isinstance(n, ast.Import) and any(a.name == "veyltrace_core.stubs" for a in n.names))
        ]
        assert not core_stubs, f"{path}: a package-owned engine must not use veyltrace_core.stubs"
        return
    names = [
        n.args[1].value
        for n in ast.walk(runs[0])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "run_stub"
        and len(n.args) == RUN_STUB_ARITY
        and isinstance(n.args[1], ast.Constant)
    ]
    assert names == [engine], f"{path}: run_stub must receive its own engine name"


def test_cli_script_is_registered() -> None:
    scripts = {ep.name: ep.value for ep in distribution("veyltrace-core").entry_points}
    assert scripts.get("veyltrace") == "veyltrace_core.cli:app"


def test_config_files_exist_with_owner_header_and_no_wrapper_key() -> None:
    stems = sorted(p.stem for p in (ROOT / "config").glob("*.yaml"))
    assert stems == sorted(CONFIG_SECTIONS)
    for stem in CONFIG_SECTIONS:
        path = ROOT / "config" / f"{stem}.yaml"
        text = path.read_bytes().decode("utf-8")
        assert "\r" not in text, f"{path}: LF line endings only"
        header = text.split("\n\n", 1)[0]
        assert header.startswith(f"# config/{stem}.yaml"), path
        assert "Owner:" in header and "Spec:" in header, f"{path}: header must name owner lane and spec"
        body = _yaml(path)
        assert isinstance(body, dict), f"{path}: the section body must be a mapping"
        assert stem not in body, f"{path}: the file stem is the section; no wrapper key"


def test_core_defaults_match_02_section_5_1() -> None:
    core = _yaml(ROOT / "config" / "core.yaml")
    assert core["alert"] == {"protocol": "oracle", "shift_s": 0, "reject_hint_outside_span": True}
    # 02 §5.1: baseline [t_alert - 20 min, t_alert - 2 min], incident [t_alert - 2 min, t_alert + 8 min].
    assert core["windows"] == {"baseline_s": [-1200, -120], "incident_s": [-120, 480]}
    assert core["thresholds"]["anomaly_z"] == 3.0
    assert core["universe"]["include_external"] is False
    assert "ai" not in core, "ai.mode is a run parameter, not a config key (03 §12.2)"


def test_causentra_weights_cover_the_predicate_library() -> None:
    weights = _yaml(ROOT / "config" / "causentra.yaml")["predicates"]
    assert sorted(weights) == sorted(p.name for p in PREDICATES)
    assert {name: entry["weight"] for name, entry in weights.items()} == DEFAULT_WEIGHTS


def test_faultloom_ranges_cover_every_numeric_param_with_matching_types() -> None:
    ranges = _yaml(ROOT / "config" / "faultloom.yaml")["predicates"]
    expected = {
        (p.name, param.name): param.type
        for p in PREDICATES
        for param in p.params
        if param.type in NUMERIC_PARAM_TYPES
    }
    found = {(pred, param) for pred, params in ranges.items() for param in params}
    assert found == set(expected)
    for (pred, param), kind in sorted(expected.items()):
        bounds = ranges[pred][param]
        assert sorted(bounds) == ["max", "min"]
        py_type = float if kind == "float" else int
        assert all(type(v) is py_type for v in bounds.values()), (pred, param, bounds)
        assert bounds["min"] <= bounds["max"]


def test_root_conftest_isolates_data_root_and_pins_threads() -> None:
    data = Path(os.environ["VEYLTRACE_DATA"]).resolve()
    assert data.is_dir()
    assert not data.is_relative_to(ROOT)
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        assert var in os.environ
