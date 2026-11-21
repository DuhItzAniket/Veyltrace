"""AI arms in the bench runner (04 §4, §8 "LLM arms"; R-16 B3a, #397).

A method with `ai: {mode: record, relentra_mode, model, seeds}` runs once per seed: bench sets
`relentra.mode` and `relentra.sampler.seed_index` (08 §3.8: bench varies the seed index through
config, so each seed has its own config hash and run id), and `bench_result.seed` is the seed.

Bench calls the model at most once per run id. A record run goes to `<runs root>/bench-ai/`, which
bench never empties, so its cassette (and receipt) is kept for replay (RQ6 Tier 1) and for the
experiments that re-run the verifier from it (B4). Before a record run bench asks core for its run
id (`plan_run_id`): when that run is already finished, from this or an earlier experiment with the
same case, config, seed and code commit, bench runs in `replay` against its cassette instead
(strict: a changed request is a cassette miss, so the run fails rather than calling the model). A
replayed row's `ai_mode` is `replay`; its wall time has no model time, its tokens are the
cassette's (`proposals.budget_used`). Delete a kept run to record it again. `ai.model` names the
04 model id; matching it to the resolved LLM model and its digest is #315.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from veyltrace_bench.experiment import Experiment, MethodSpec
from veyltrace_contracts.models import AnswerKeyRow, Proposals
from veyltrace_core import io
from veyltrace_core.config import resolve_config
from veyltrace_core.errors import ArtifactMissing, ConfigError, ContractValidationError
from veyltrace_core.pipeline import CASSETTE_DIR, is_finished, plan_run_id, run_dir_for

MODE_KEY = "relentra.mode"
SEED_KEY = "relentra.sampler.seed_index"  # 08 §3.8, §4 (Explain #354)
AI_KEYS = (MODE_KEY, SEED_KEY)
KEPT = "bench-ai"  # <runs root>/bench-ai/: every AI record run, kept across experiments
RECORD, REPLAY = "record", "replay"


@dataclass(frozen=True)
class AiRun:
    """How one AI-arm run is executed: its AI mode, runs root, the cassette it replays, and whether
    it may overwrite an unfinished record run left by a killed attempt."""

    ai_mode: str
    runs_root: Path
    cassette_dir: Path | None = None
    force_record: bool = False


def seeds_of(method: MethodSpec) -> tuple[int | None, ...]:
    """The method's seeds; (None,) for a deterministic method (bench_result.seed null)."""
    return method.ai.seeds or (None,)


def overrides(method: MethodSpec, seed: int | None) -> dict[str, object]:
    """The relentra keys of one AI-arm run; none with AI off."""
    if method.ai.mode == "off":
        return {}
    keys: dict[str, object] = {MODE_KEY: method.ai.relentra_mode}
    return keys | ({SEED_KEY: seed} if seed is not None else {})


def check(exp: Experiment) -> None:
    """Before any run: AI arms need Relentra's seed key in config (Explain #354)."""
    if not any(m.ai.mode != "off" for m in exp.methods):
        return
    relentra = cast(
        "Mapping[str, Any]",
        resolve_config({}, dataset=exp.dataset.parts[0], ai_mode="record").engine("relentra"),
    )
    sampler = relentra.get("sampler")
    if not isinstance(sampler, Mapping) or "seed_index" not in sampler:
        raise ConfigError(f"AI arms set {SEED_KEY}, which config/relentra.yaml lacks (Relentra brief, #354)")


def plan(
    key: AnswerKeyRow, ai_mode: str, overrides_: Mapping[str, object], runs_root: Path, kept: Path
) -> AiRun:
    """Record into the `kept` root, or replay the kept record run with the same run id."""
    if ai_mode != RECORD:
        return AiRun(ai_mode, runs_root)
    rid = plan_run_id(key.dataset, key.case_id, RECORD, dict(overrides_), runs_root=kept)
    record = run_dir_for(kept, key.dataset, key.case_id, rid)
    if is_finished(record):
        return AiRun(REPLAY, runs_root, record / CASSETTE_DIR)
    return AiRun(RECORD, kept, force_record=record.exists())


def tokens(run_dir: Path | None) -> tuple[int | None, int | None]:
    """(tokens_in, tokens_out) of a run's proposals (03 §9.1 budget_used); None without them."""
    if run_dir is None:
        return None, None
    try:
        got = io.read_model("proposals", run_dir, Proposals)
    except (ArtifactMissing, ContractValidationError):
        return None, None
    return got.budget_used.tokens_in, got.budget_used.tokens_out
