"""The generated contract code matches contracts/schemas/ (03 §1, §14; 10 §4 contract round-trip).

Why a pytest wrapper: `scripts/gen_contracts.py --check` is the authority (it regenerates into a temp
dir, byte-compares against contracts/generated/, round-trips every example and reports 03 parity).
Running it under `check.py --tests` means a schema edit without regeneration fails the ordinary test
job too, not only the separate `contracts-in-sync` job.

It runs the script with this interpreter (the synced workspace venv has every dependency the
script's PEP 723 header declares), so the test needs no network and no `uv` on PATH.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
