"""Golden fixtures built from stale upstream fixtures (the non-required `fixtures-stale` job).

Why: when a producer regenerates its goldens, every consumer golden built on the old ones is out
of date. Failing the required tests for that would turn main red across lanes, so staleness is
reported here, by `scripts/check.py --fixtures-stale` only (check_ci §5.3; critic gap "fixture
cascade"; M0 lead decision 2026-11-06 §2.10). The fix is `check.py --update-golden --cascade`.

Without VEYLTRACE_CHECK_FIXTURES_STALE=1 (set by check.py) the test skips, so `pytest` and the
required `--tests` job never fail on it.
"""

from __future__ import annotations

import os

import pytest

from veyltrace_core.steps import STEPS
from veyltrace_core.testing import fixture_dir, stale_upstream
from veyltrace_core.testing.fixtures import FIXTURES_DIR, SYNTH_CASES, VARIANTS, repo_root

STALE_ENV = "VEYLTRACE_CHECK_FIXTURES_STALE"
#: Packages that run a pipeline step and therefore own goldens with upstream locks.
CONSUMERS = tuple(sorted({s.runner for s in STEPS}))
CASES = (*SYNTH_CASES, *sorted(VARIANTS))

pytestmark = pytest.mark.skipif(
    os.environ.get(STALE_ENV) != "1", reason=f"fixtures-stale job only (set {STALE_ENV}=1)"
)


def _existing() -> list[tuple[str, str]]:
    """(consumer, fixture case) for every fixture directory that exists in the work tree."""
    found: list[tuple[str, str]] = []
    for package in CONSUMERS:
        if not (repo_root() / "packages" / package / FIXTURES_DIR).is_dir():
            continue
        found.extend((package, case) for case in CASES if fixture_dir(package, case).is_dir())
    return found


@pytest.mark.parametrize(("package", "case"), _existing(), ids=str)
def test_golden_is_built_from_current_upstream(package: str, case: str) -> None:
    reasons = stale_upstream(package, case)
    lines = "\n".join(f"STALE {package}/{case}: {r}" for r in reasons)
    assert not reasons, f"{lines}\nrun `uv run python scripts/check.py --update-golden --cascade`"
