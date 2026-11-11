"""Engine entry point of Relentra (registered as `veyltrace.engines:relentra`).

X-00 stub: reads `case_manifest` and `slate` and writes `proposals.json` with `status = skipped` and an
empty `agent_trace.jsonl`, because no model is called yet (`veyltrace_relentra.stub`). X-07 replaces
the stub with brief mode; the signature `run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_core.context import EngineResult, RunContext
from veyltrace_relentra.stub import run_stub


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 7 (X-00 stub): proposals skipped, no model call (see `stub`)."""
    return run_stub(ctx)
