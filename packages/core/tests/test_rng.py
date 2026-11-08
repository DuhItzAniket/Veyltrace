"""rng: generators and seeds depend only on (case_id, purpose), and the streams are pinned."""

from __future__ import annotations

import numpy as np
import pytest

from veyltrace_core.hashing import sha256_json
from veyltrace_core.ids import case_id
from veyltrace_core.rng import SEED_INT_MODULUS, rng, seed_int

CASE = case_id("synth-01")


def test_seed_definition() -> None:
    gen = rng(CASE, "core.test")
    assert isinstance(gen, np.random.Generator)
    assert isinstance(gen.bit_generator, np.random.PCG64)
    expected = np.random.Generator(np.random.PCG64(int(sha256_json([CASE, "core.test"])[:16], 16)))
    assert gen.bit_generator.random_raw(4).tolist() == expected.bit_generator.random_raw(4).tolist()


def test_streams_are_pinned() -> None:
    # PCG64's raw output is fixed by its definition; a change here means the seed rule changed.
    assert rng(CASE, "core.test").bit_generator.random_raw(3).tolist() == [
        9719724668861942643,
        4211470812736793353,
        2091961192806924691,
    ]
    # NEP 19 lets numpy change Generator method streams between versions (raw bits stay fixed). If this
    # fails after a numpy bump, goldens drift too: re-pin with an ADR.
    assert rng(CASE, "core.test").random(2).tolist() == [0.5269073300970534, 0.22830429022642618]


def test_each_call_restarts_the_stream() -> None:
    first = rng(CASE, "synth.metrics").normal(size=5)
    second = rng(CASE, "synth.metrics").normal(size=5)
    assert first.tolist() == second.tolist()


def test_purpose_and_case_separate_streams() -> None:
    a = rng(CASE, "synth.metrics").random(4).tolist()
    assert rng(CASE, "synth.spans").random(4).tolist() != a
    assert rng(case_id("synth-02"), "synth.metrics").random(4).tolist() != a


def test_seed_int() -> None:
    digest = sha256_json([CASE, "relentra.seed/0"])
    assert seed_int(CASE, "relentra.seed/0") == int(digest[:8], 16) % (2**31 - 1)
    assert seed_int(CASE, "relentra.seed/0") == 962354067  # pinned
    assert seed_int(CASE, "causivra.seed/0") == 975862085  # pinned
    for i in range(50):
        assert 0 <= seed_int(CASE, f"relentra.seed/{i}") < SEED_INT_MODULUS


@pytest.mark.parametrize(("case", "purpose"), [("synth-01", "x"), ("59E0D31BCC42", "x"), (CASE, "")])
def test_keys_are_validated(case: str, purpose: str) -> None:
    with pytest.raises(ValueError):
        rng(case, purpose)
    with pytest.raises(ValueError):
        seed_int(case, purpose)
