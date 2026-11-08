"""Build the RunContext an engine would receive, for unit and golden tests.

Why: engine tests run `run(ctx)` on a fixture run directory without the pipeline. The context must
match what the pipeline would hand that step: the step name (so case_manifest hint redaction
applies exactly as in a run, D-15), the run's resolved config with overrides and calibration, and
the run_id that fixture generation pins (code_commit "fixture", M0 lead decision 2026-11-06 §2.10).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import textio
from veyltrace_core.config import config_sha256, resolve_config
from veyltrace_core.context import RunContext
from veyltrace_core.hint import HINT_READERS
from veyltrace_core.ids import AIMode
from veyltrace_core.ids import run_id as make_run_id
from veyltrace_core.steps import CORE_ENGINE, Phase, step_for
from veyltrace_core.testing.fixtures import FIXTURE_CODE_COMMIT, repo_root

__all__ = ["CASSETTE_DIR", "DEFAULT_CORE_STEP", "make_context"]

#: Run-dir subdirectory of the LLM cassette (02 §4.1).
CASSETTE_DIR: Final = "cassette"
#: The core sub-step a "core" context runs unless told otherwise (the alert step reads the hint).
DEFAULT_CORE_STEP: Final = "alert"
_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})


def _case_id_from_manifest(run_dir: Path) -> str:
    path = run_dir / CONTRACTS["case_manifest"].path
    if not path.is_file():
        msg = f"make_context needs case_id= or a case_manifest.json in {run_dir}"
        raise ValueError(msg)
    raw: object = json.loads(textio.read_text(path))
    found: object = cast("Mapping[str, object]", raw).get("case_id") if isinstance(raw, Mapping) else None
    if not isinstance(found, str):
        msg = f"{path} has no string case_id"
        raise ValueError(msg)
    return found


def make_context(
    engine: str,
    run_dir: Path,
    *,
    phase: Phase = "main",
    ai_mode: AIMode = "off",
    overrides: Mapping[str, Any] = _EMPTY,
    case_id: str | None = None,
    dataset: str = "synth",
    run_id: str | None = None,
    step: str | None = None,
    cassette_dir: Path | None = None,
    force_record: bool = False,
    config_dir: Path | None = None,
) -> RunContext:
    """A RunContext for `engine` in `phase` over `run_dir`, as the pipeline would build it.

    - config: resolved from the work tree's `config/` (or `config_dir`) with `overrides`,
      `dataset` (calibration selection) and `ai_mode`;
    - case_id: from `run_dir/case_manifest.json` unless given;
    - run_id: `ids.run_id(case_id, config_sha256, "fixture", ai_mode)` unless given;
    - step: the sub-step that runs (engine, phase), "alert" for engine "core";
    - cassette_dir: `run_dir/cassette` when AI is on, unless given.
    """
    resolved = resolve_config(
        overrides,
        config_dir=config_dir if config_dir is not None else repo_root() / "config",
        dataset=dataset,
        ai_mode=ai_mode,
    )
    cid = case_id if case_id is not None else _case_id_from_manifest(run_dir)
    rid = (
        run_id
        if run_id is not None
        else make_run_id(cid, config_sha256(resolved), FIXTURE_CODE_COMMIT, ai_mode)
    )
    if step is None:
        found = step_for(engine, phase)
        if found is not None:
            step = found.name
        elif engine == CORE_ENGINE:
            step = DEFAULT_CORE_STEP
        else:
            msg = f"no pipeline step runs engine {engine!r} in phase {phase!r}; pass step="
            raise ValueError(msg)
    if cassette_dir is None and ai_mode != "off":
        cassette_dir = run_dir / CASSETTE_DIR
    return RunContext(
        case_id=cid,
        run_id=rid,
        dataset=dataset,
        run_dir=run_dir,
        ai_mode=ai_mode,
        engine=engine,
        config=resolved.engine(engine),
        phase=phase,
        step=step,
        cassette_dir=cassette_dir,
        force_record=force_record,
        resolved=resolved,
        unredacted_hint=step in HINT_READERS,
    )
