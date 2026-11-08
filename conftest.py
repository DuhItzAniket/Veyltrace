"""Workspace-wide pytest setup, loaded before any test module.

Why each piece exists:
- Thread pins: BLAS/OpenMP thread counts change float summation order, so numeric results could
  differ between the team's laptops and CI (M0 lead decision 2026-11-06).
  They are set with setdefault before any test module imports numpy.
- VEYLTRACE_DATA: every test gets a fresh data root in the system temp dir, outside the git work
  tree, so tests never write caches or answer keys into a developer's real data dir and
  `data_root()` never rejects the root as inside the repo (M0 lead decision 2026-11-06).
  Tests marked `real_data` keep the caller's VEYLTRACE_DATA and skip when it is unset.
- Hypothesis profile `ci`: derandomised, so property tests repeat exactly in CI
  (10 §3 property tests; check.py runs pytest with `--hypothesis-profile=ci`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import pytest  # noqa: E402  (imported after the thread pins on purpose)
from hypothesis import settings  # noqa: E402  (same reason: hypothesis may import numpy)

WORK_TREE = Path(__file__).resolve().parent
DATA_ENV = "VEYLTRACE_DATA"

# Hypothesis CI profile values (M0 lead decision 2026-11-06): 200 examples per property, no deadline.
CI_MAX_EXAMPLES = 200
settings.register_profile("ci", derandomize=True, deadline=None, max_examples=CI_MAX_EXAMPLES)


@pytest.fixture(autouse=True)
def _isolated_data_root(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Point VEYLTRACE_DATA at a per-test temp dir outside the work tree (see module docstring)."""
    if request.node.get_closest_marker("real_data") is not None:
        if not os.environ.get(DATA_ENV):
            pytest.skip(f"real_data test: {DATA_ENV} is not set")
        yield
        return
    root = tmp_path_factory.mktemp("veyltrace-data").resolve()
    if root.is_relative_to(WORK_TREE):
        pytest.fail(f"pytest temp dir {root} is inside the work tree {WORK_TREE}; pass --basetemp elsewhere")
    monkeypatch.setenv(DATA_ENV, str(root))
    yield
