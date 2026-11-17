"""The generated contract code matches contracts/schemas/ (03 §1, §14; 10 §4 contract round-trip).

Why a pytest wrapper: `scripts/gen_contracts.py --check` is the authority (it regenerates into a temp
dir, byte-compares against contracts/generated/, round-trips every example and reports 03 parity).
Running it under `check.py --tests` means a schema edit without regeneration fails the ordinary test
job too, not only the separate `contracts-in-sync` job.

It runs the script with this interpreter (the synced workspace venv has every dependency the
script's PEP 723 header declares), so the test needs no network and no `uv` on PATH.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEN_CONTRACTS = ROOT / "scripts" / "gen_contracts.py"
#: Seconds for a full regenerate-and-compare; about 2 s locally (a priori margin for CI).
TIMEOUT_S = 300
#: gen_contracts.py exit codes (its module docstring): 0 ok, 1 diff/validation, 2 usage.
EXIT_OK = 0


def test_generated_contracts_in_sync() -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(GEN_CONTRACTS), "--check"],
        cwd=ROOT,
        capture_output=True,
        timeout=TIMEOUT_S,
        env=env,
        check=False,
    )
    output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    assert proc.returncode == EXIT_OK, (
        f"gen_contracts.py --check exited {proc.returncode}; regenerate with "
        f"`uv run scripts/gen_contracts.py` (Reason lane) and commit the result.\n{output}"
    )


# Per-contract series (#319): one contract can move to a new minor alone; references to another
# series are absolute `$id`s. These run the real generator on a copy of contracts/ in which `alert`
# is moved to 0.2.
COMMON_REL = '"$ref": "common.schema.json#'
COMMON_ABS = '"$ref": "https://veyltrace.dev/schemas/0.1/common.schema.json#'


def _gen_contracts() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_contracts_under_test", GEN_CONTRACTS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses resolve their module while it executes
    spec.loader.exec_module(module)
    return module


def _contracts_copy(tmp_path: Path, *, id_series: str, refs: str) -> Path:
    """contracts/ copied to tmp_path with `alert` at version 0.2.0, its `$id` in `id_series`."""
    shutil.copytree(ROOT / "contracts" / "schemas", tmp_path / "contracts" / "schemas")
    shutil.copytree(ROOT / "contracts" / "examples", tmp_path / "contracts" / "examples")
    shutil.copy(ROOT / "contracts" / "predicates.json", tmp_path / "contracts" / "predicates.json")
    schema = tmp_path / "contracts" / "schemas" / "alert.schema.json"
    text = schema.read_text(encoding="utf-8").replace(COMMON_REL, refs)
    text = text.replace('"version": "0.1.0"', '"version": "0.2.0"')
    text = text.replace(r'"^0\\.1\\.', r'"^0\\.2\\.')  # the schema_version pattern, JSON-escaped
    text = text.replace("/schemas/0.1/alert.schema.json", f"/schemas/{id_series}/alert.schema.json")
    schema.write_text(text, encoding="utf-8", newline="\n")
    example = tmp_path / "contracts" / "examples" / "alert.example.json"
    text = example.read_text(encoding="utf-8").replace('"0.1.0"', '"0.2.0"')
    example.write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = _gen_contracts().main(["--root", str(root), "--out", str(root / "generated")])
    return code, capsys.readouterr().out


def test_a_02_contract_references_the_01_common_by_absolute_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(_contracts_copy(tmp_path, id_series="0.2", refs=COMMON_ABS), capsys)
    assert code == EXIT_OK, out
    registry = (tmp_path / "generated" / "python" / "veyltrace_contracts" / "registry.py").read_text("utf-8")
    versions = dict(re.findall(r'name="([^"]+)",\s+kind="[a-z]+",\s+version="([^"]+)"', registry))
    assert versions["alert"] == "0.2.0"
    assert {v for name, v in versions.items() if name != "alert"} == {"0.1.0"}  # the others stay


def test_the_id_folder_must_be_the_contracts_own_series(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(_contracts_copy(tmp_path, id_series="0.1", refs=COMMON_ABS), capsys)
    assert code != EXIT_OK and '"$id" must be https://veyltrace.dev/schemas/<major>.<minor>/alert' in out


def test_a_sibling_reference_stays_in_the_referring_series(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(_contracts_copy(tmp_path, id_series="0.2", refs=COMMON_REL), capsys)
    assert code != EXIT_OK and "no schema has that $id" in out  # 0.2/common.schema.json does not exist
