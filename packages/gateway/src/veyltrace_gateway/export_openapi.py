"""Write `packages/gateway/openapi.json` (06 §3.5): `uv run python -m veyltrace_gateway.export_openapi`.

Why a committed file: the console gets types only from `contracts/generated/ts`, which the lead's
`scripts/gen_contracts.py` generates from this document (03 §14), and CI fails when the file and a
fresh export differ. The output is indented, key-sorted JSON so a route change is a readable diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

from veyltrace_core.config import find_config_dir
from veyltrace_core.textio import write_bytes
from veyltrace_gateway.app import create_app

__all__ = ["OPENAPI_PATH", "export", "main"]

#: Where the document lives, relative to the repository root (03 §14).
OPENAPI_PATH: Final = Path("packages/gateway/openapi.json")


def export(config_dir: Path | None = None) -> bytes:
    """The OpenAPI document of the app built from `config_dir` (default: found from the CWD)."""
    directory = config_dir if config_dir is not None else find_config_dir()
    app = create_app(config_dir=directory, runs=directory.parent / "runs")
    text = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def main() -> int:
    directory = find_config_dir()
    write_bytes(directory.parent / OPENAPI_PATH, export(directory))
    return 0


if __name__ == "__main__":
    sys.exit(main())
