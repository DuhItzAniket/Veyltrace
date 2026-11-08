"""`veyltrace data fetch synth` (entry point `veyltrace.fetchers:synth`).

Synth telemetry is generated on demand by the adapter and never cached, so "fetching" synth only
writes the evaluation-only answer keys to `${VEYLTRACE_DATA}/answer_keys/synth.parquet`. Nothing is
downloaded: no network module is imported.
"""

from __future__ import annotations

import sys
from typing import Final

from veyltrace_core.fetch import FetchRequest
from veyltrace_core.synth import layout as lay
from veyltrace_core.synth.truth import answer_key_rows, write_answer_keys

__all__ = ["fetch"]

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2


def fetch(req: FetchRequest) -> int:
    """Write the synth answer keys under `req.data_root`; returns a process exit code."""
    if req.suite not in (None, lay.DATASET):
        print(
            f"synth fetch: unknown suite {req.suite!r}; synth has one suite, {lay.DATASET!r}", file=sys.stderr
        )
        return EXIT_USAGE
    if req.source is not None:
        print("synth fetch: --source does not apply (synth cases are generated locally)", file=sys.stderr)
        return EXIT_USAGE
    path, digest = write_answer_keys(req.data_root)
    rows = len(answer_key_rows())
    print(f"synth: generated on demand (not cached); wrote {rows} answer-key rows to {path}")
    print(f"synth: answer_keys sha256 {digest}")
    return EXIT_OK
