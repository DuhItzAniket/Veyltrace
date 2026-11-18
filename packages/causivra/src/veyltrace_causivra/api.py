"""Engine entry point of Causivra (registered as `veyltrace.engines:causivra`).

Step 10 is split (02 §6.10): phase `card` (10a) writes `card.json` and `card.md`, then core writes
`config.lock.json` and `run_manifest.json`, then phase `receipt` (10b) writes `receipt.json`.
Both phases are this package's: the card (`veyltrace_causivra.card`, 10 §3.1–3.7, template prose
until X-09 adds narration) and the receipt (`veyltrace_causivra.receipt`, 10 §3.8). The signature
`run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_causivra.card import run_card
from veyltrace_causivra.receipt import run_receipt
from veyltrace_core.context import EngineResult, RunContext


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 10a (card) or 10b (receipt)."""
    if ctx.phase == "receipt":
        return run_receipt(ctx)
    return run_card(ctx)
