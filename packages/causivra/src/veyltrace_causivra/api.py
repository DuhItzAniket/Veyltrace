"""Engine entry point of Causivra (registered as `veyltrace.engines:causivra`).

Step 10 is split (02 §6.10): phase `card` (10a) writes `card.json` and `card.md`, then core writes
`config.lock.json` and `run_manifest.json`, then phase `receipt` (10b) writes `receipt.json`.
X-00: the receipt phase is this package's (`veyltrace_causivra.receipt`, 10 §3.8); the card phase is
still the R-02 bootstrap template card, which X-03 replaces. The signature
`run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_causivra.receipt import run_receipt
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.stubs import run_stub


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 10a (card, bootstrap stub until X-03) or 10b (receipt)."""
    if ctx.phase == "receipt":
        return run_receipt(ctx)
    return run_stub(ctx, "causivra")
