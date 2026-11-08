"""Shared inputs for the Causentra tests: contract examples and a fixture run directory.

The contract examples (contracts/examples) give a populated slate and proposals for synth-01's
case id; the fixture run dir gives every upstream artefact as the committed goldens hold it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core.testing import fixture_run_dir, repo_root

#: The step before Causentra: its run dir holds the claim-pass evidence (09 §2.1).
THROUGH = "faultloom.claim_pass"


def example(name: str) -> dict[str, Any]:
    path = repo_root() / "contracts" / "examples" / f"{name}.example.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def example_slate() -> models.Slate:
    """A populated slate (five candidates, six services in U) for synth-01's case id."""
    return models.Slate.model_validate(example("slate"))


@pytest.fixture
def example_proposals() -> models.Proposals:
    return models.Proposals.model_validate(example("proposals"))


@pytest.fixture
def synth01_dir(tmp_path: Path) -> Path:
    """synth-01's committed fixtures through the claim pass, AI off."""
    return fixture_run_dir("synth-01", tmp_path, through=THROUGH)
