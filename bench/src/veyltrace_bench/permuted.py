"""Proposal permutations, `protocol.permute_proposals` (04 §5.2, §9; H2c; R-16 B4, #399).

"The recorded proposals re-ordered with a seeded permutation; Causentra re-run" (04 §5.2). Manager
decision (21 Nov, option b): the permutation is applied **in memory**, through Causentra's own
decision API (`veyltrace_causentra.api.verdict_for`), on the inputs Causentra read in the finished
AI-arm run: the proposals, every proposal's claims and the claim_check atoms are re-ordered, and
the verdict is rebuilt. No run directory is written and no model is called. Each permutation is a
row with variant `perm-<i>`; H2c's `permutation_invariance` is the share of (case, seed) whose
verdict_hash is one value across the unpermuted row and every permuted one.

At the artefact level invariance holds by construction: `proposals.json` is canonical (sorted by
service, fault class and a content-hash id, 03 §9.1), and core's writer refuses any other order.
Whether Relentra's normaliser maps a permuted model reply to the same file is Explain's to test
(#410). Permutations are drawn by numpy's generator seeded with (seed, case id, AI seed, i).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from veyltrace_bench.calibration import causentra_inputs
from veyltrace_bench.experiment import ProposalDraw
from veyltrace_causentra.api import verdict_for
from veyltrace_causentra.inputs import CausentraInputs
from veyltrace_contracts.models import Verdict

PERM = "perm"  # bench_result.variant perm-<i> (03 §13.2 example "perm-3")


def variant(i: int) -> str:
    return f"{PERM}-{i}"


def permuted(inp: CausentraInputs, gen: np.random.Generator) -> CausentraInputs:
    """`inp` with its proposals, each proposal's claims, and the claim atoms re-ordered."""
    claims = [inp.claims[int(j)] for j in gen.permutation(len(inp.claims))]
    if inp.proposals is None:
        return replace(inp, claims=tuple(claims))
    listed = inp.proposals.proposals
    shuffled = []
    for j in gen.permutation(len(listed)):
        p = listed[int(j)]
        order = gen.permutation(len(p.claims))
        shuffled.append(p.model_copy(update={"claims": [p.claims[int(k)] for k in order]}))
    return replace(
        inp, claims=tuple(claims), proposals=inp.proposals.model_copy(update={"proposals": shuffled})
    )


def verdicts(run_dir: Path, draw: ProposalDraw, seed: int | None) -> list[Verdict]:
    """The verdicts of `draw.n` seeded permutations of a finished run's proposals (in memory)."""
    ctx, cfg, inp = causentra_inputs(run_dir)
    out: list[Verdict] = []
    for i in range(1, draw.n + 1):
        gen = np.random.default_rng([draw.seed, int(ctx.case_id, 16), seed if seed is not None else 0, i])
        _, verdict = verdict_for(ctx, cfg, permuted(inp, gen))
        out.append(Verdict.model_validate(verdict))
    return out
