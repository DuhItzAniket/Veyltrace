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
cassette's (`proposals.budget_used`). Delete a kept run to record it again.

An AI-arm run counts only on the pinned GGUF (04 §4, §10.7; #315). `ai.model` names the 04 model
id; `RUNTIME_NAMES` maps it to the config/llm.yaml `model.name` tags that serve it, and the pinned
digest is config/llm.yaml `model.gguf_sha256` (08 §3.8, L-01), read once before the first case.
`check` refuses the experiment when that digest is null or a method's resolved llm section names
another model or digest. Each run's resolved model is its `run_manifest.ai` (03 §12, which core
merges from what Relentra reports): a run that differs from the pin is `rejected` (03 §13.2), so
it is never scored. Every scored row's run therefore names the digest (RQ6 Tier 2 reads it there).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from veyltrace_bench.experiment import Experiment, MethodSpec
from veyltrace_contracts.models import AnswerKeyRow, Proposals, RunManifest
from veyltrace_core import io
from veyltrace_core.config import resolve_config
from veyltrace_core.errors import ArtifactMissing, ConfigError, ContractValidationError
from veyltrace_core.pipeline import CASSETTE_DIR, is_finished, plan_run_id, run_dir_for

MODE_KEY = "relentra.mode"
SEED_KEY = "relentra.sampler.seed_index"  # 08 §3.8, §4 (Explain #354)
AI_KEYS = (MODE_KEY, SEED_KEY)
KEPT = "bench-ai"  # <runs root>/bench-ai/: every AI record run, kept across experiments
RECORD, REPLAY = "record", "replay"
REJECTED = "rejected"  # bench_result.run_outcome of a run on another model (03 §13.2)
MISMATCH = "model_mismatch"  # Executed.reason of such a run
#: 04 §4 model ids (`ai.model`) -> the config/llm.yaml `model.name` tags that serve that GGUF.
#: Ollama's `qwen3.5:9b` is the Q4_K_M build of 08 §3.8; the pinned digest proves it, not the tag.
RUNTIME_NAMES: Mapping[str, tuple[str, ...]] = MappingProxyType({"qwen3.5-9b-q4_k_m": ("qwen3.5:9b",)})


@dataclass(frozen=True)
class AiRun:
    """How one AI-arm run is executed: its AI mode, runs root, the cassette it replays, and whether
    it may overwrite an unfinished record run left by a killed attempt."""

    ai_mode: str
    runs_root: Path
    cassette_dir: Path | None = None
    force_record: bool = False


@dataclass(frozen=True)
class Pin:
    """The GGUF an AI arm's runs must resolve: the 04 model id, the runtime tags that serve it and
    the digest config/llm.yaml pins (04 §10.7; 08 §3.8)."""

    model: str
    names: tuple[str, ...]
    gguf_sha256: str

    def mismatch(self, name: str | None, gguf_sha256: str | None) -> str | None:
        """Why a resolved (model name, digest) is not this GGUF; None when it is."""
        if name not in self.names:
            return f"model {name!r} is not {self.model} ({', '.join(self.names)})"
        if gguf_sha256 != self.gguf_sha256:
            return f"gguf_sha256 {gguf_sha256} is not the pinned {self.gguf_sha256}"
        return None


def seeds_of(method: MethodSpec) -> tuple[int | None, ...]:
    """The method's seeds; (None,) for a deterministic method (bench_result.seed null)."""
    return method.ai.seeds or (None,)


def overrides(method: MethodSpec, seed: int | None) -> dict[str, object]:
    """The relentra keys of one AI-arm run; none with AI off."""
    if method.ai.mode == "off":
        return {}
    keys: dict[str, object] = {MODE_KEY: method.ai.relentra_mode}
    return keys | ({SEED_KEY: seed} if seed is not None else {})


def _llm(cfg: Any) -> tuple[str | None, str | None]:
    """(model.name, model.gguf_sha256) of a resolved config's llm section (08 §4)."""
    model = cast("Mapping[str, Any]", cfg.engine("llm")).get("model")
    if not isinstance(model, Mapping):
        return None, None
    model = cast("Mapping[str, Any]", model)
    return model.get("name"), model.get("gguf_sha256")


def check(exp: Experiment) -> dict[str, Pin]:
    """Before any run, each AI arm's pin (method id -> Pin): Relentra's seed key is in config
    (Explain #354), `ai.model` is a known 04 model id, config/llm.yaml pins its digest, and the
    method's resolved llm section names that model and digest (#315)."""
    arms = [m for m in exp.methods if m.ai.mode != "off"]
    if not arms:
        return {}
    base = resolve_config({}, dataset=exp.dataset.parts[0], ai_mode=RECORD)
    sampler = cast("Mapping[str, Any]", base.engine("relentra")).get("sampler")
    if not isinstance(sampler, Mapping) or "seed_index" not in sampler:
        raise ConfigError(f"AI arms set {SEED_KEY}, which config/relentra.yaml lacks (Relentra brief, #354)")
    _, digest = _llm(base)
    if digest is None:
        raise ConfigError(
            "config/llm.yaml model.gguf_sha256 is null: an AI arm counts only on the pinned GGUF"
            " (04 §10.7; 08 §3.8 L-01 pins it)"
        )
    pins: dict[str, Pin] = {}
    for m in arms:
        names = RUNTIME_NAMES.get(m.ai.model or "")
        if names is None:
            known = ", ".join(sorted(RUNTIME_NAMES))
            raise ConfigError(f"method {m.id}: ai.model {m.ai.model!r} is not a pinned 04 model id ({known})")
        pin = Pin(cast("str", m.ai.model), names, cast("str", digest))
        keys = overrides(m, seeds_of(m)[0]) | m.overrides
        for dataset in exp.dataset.parts:
            got = _llm(resolve_config(keys, dataset=dataset, ai_mode=RECORD))
            if (why := pin.mismatch(*got)) is not None:
                raise ConfigError(f"method {m.id} on {dataset}: {why} (#315)")
        pins[m.id] = pin
    return pins


def mismatch(run_dir: Path | None, pin: Pin) -> str | None:
    """Why a finished run did not resolve the pinned GGUF (its run_manifest.ai); None if it did."""
    if run_dir is None:
        return "no run directory"
    try:
        ai = io.read_model("run_manifest", run_dir, RunManifest).ai
    except (ArtifactMissing, ContractValidationError):
        return "no valid run_manifest"
    return pin.mismatch(ai.model, ai.gguf_sha256)


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
