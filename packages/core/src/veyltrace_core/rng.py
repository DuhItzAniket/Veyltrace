"""The only source of randomness in analysis code: generators keyed by (case_id, purpose).

Seeding from the case and a purpose string (never from the clock, a global seed or call order)
means a draw depends only on what it is for, so adding a new random step elsewhere never shifts
another engine's numbers (02 §9 determinism rule 2; packages/core/AGENTS.md Never 3). Purposes
are free strings such as "synth.metrics" or "relentra.seed/0".

Bench (not analysis code) may use numpy.random.default_rng(int_seed) for splits, bootstrap and
permutations (04 §8).
"""

from __future__ import annotations

import numpy as np

from veyltrace_core.hashing import sha256_json
from veyltrace_core.ids import is_case_id

__all__ = ["RNG_SEED_HEX", "SEED_INT_HEX", "SEED_INT_MODULUS", "rng", "seed_int"]

#: Hex digits of sha256_json([case_id, purpose]) that seed PCG64: 64 bits (core_api_spec §3).
RNG_SEED_HEX = 16
#: Hex digits used by seed_int: 32 bits, reduced below 2**31 - 1 (core_api_spec §3).
SEED_INT_HEX = 8
#: seed_int range is [0, 2**31 - 1), the sampler seed range of 08 §3.8 (Relentra; Causivra reuses it).
SEED_INT_MODULUS = 2**31 - 1


def _check(case_id: str, purpose: str) -> None:
    if not is_case_id(case_id):
        msg = f"rng is keyed by a 12-hex case_id, got {case_id!r}"
        raise ValueError(msg)
    if not purpose:
        msg = "rng purpose must be a non-empty string"
        raise ValueError(msg)


def rng(case_id: str, purpose: str) -> np.random.Generator:
    """Return a fresh PCG64 generator seeded with int(sha256_json([case_id, purpose])[:16], 16).

    Each call returns a new generator at the start of its stream, so two calls with the same key
    draw the same numbers.
    """
    _check(case_id, purpose)
    seed = int(sha256_json([case_id, purpose])[:RNG_SEED_HEX], 16)
    return np.random.Generator(np.random.PCG64(seed))


def seed_int(case_id: str, purpose: str) -> int:
    """Return an integer seed in [0, 2**31 - 1) for an external sampler (Relentra, Causivra).

    It is computed from the hash alone, not drawn from numpy, so it is stable across numpy
    versions (core_api_spec D-19; 08 §3.8; 10 §3.2).
    """
    _check(case_id, purpose)
    return int(sha256_json([case_id, purpose])[:SEED_INT_HEX], 16) % SEED_INT_MODULUS
