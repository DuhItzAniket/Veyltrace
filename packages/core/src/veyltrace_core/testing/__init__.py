"""Test helpers for every lane: golden fixtures, run-dir assembly, contexts and variants.

`golden`/`assert_golden` load and compare producer fixtures by canonical content (never file
bytes, D-16); `fixture_run_dir`/`synth_run_dir` assemble a run directory from them;
`make_context` builds the RunContext a step would get; `VARIANTS` lists the fixture variants
(M0 lead decision 2026-11-06 §2.10); the upstream-lock helpers drive the `fixtures-stale` job.

Tests and scripts only: engine source never imports this package (AST ban in the isolation test).
"""

from veyltrace_core.testing.compare import assert_golden, content_lines, content_sha256
from veyltrace_core.testing.contexts import make_context
from veyltrace_core.testing.fixtures import (
    FIXTURE_CODE_COMMIT,
    PRODUCER,
    SYNTH_CASES,
    TWO_PHASE,
    VARIANTS,
    Variant,
    fixture_case,
    fixture_dir,
    fixture_relpath,
    golden,
    golden_file,
    golden_path,
    producer_of,
    repo_root,
    split_case,
)
from veyltrace_core.testing.rundir import (
    UPSTREAM_LOCK,
    UpstreamLock,
    compute_upstream_lock,
    fixture_run_dir,
    read_upstream_lock,
    stale_upstream,
    synth_run_dir,
    upstream_fixtures,
    write_upstream_lock,
)

__all__ = [
    "FIXTURE_CODE_COMMIT",
    "PRODUCER",
    "SYNTH_CASES",
    "TWO_PHASE",
    "UPSTREAM_LOCK",
    "VARIANTS",
    "UpstreamLock",
    "Variant",
    "assert_golden",
    "compute_upstream_lock",
    "content_lines",
    "content_sha256",
    "fixture_case",
    "fixture_dir",
    "fixture_relpath",
    "fixture_run_dir",
    "golden",
    "golden_file",
    "golden_path",
    "make_context",
    "producer_of",
    "read_upstream_lock",
    "repo_root",
    "split_case",
    "stale_upstream",
    "synth_run_dir",
    "upstream_fixtures",
    "write_upstream_lock",
]
