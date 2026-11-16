"""Settings of the bench baselines (R-05, #15): bench/baselines.yaml, one section per baseline.

The file is YAML 1.2 with duplicate keys rejected (as config/), and each section is validated by
its baseline's strict model, so an unknown or missing key fails before the first case. A section's
hash goes into the method's manifest config hash, so a changed threshold changes the manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from veyltrace_bench.experiment import read_yaml
from veyltrace_core.config import find_config_dir
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_json

BASELINES_FILE = ("bench", "baselines.yaml")  # below the repo root


def baselines_path(repo: Path | None = None) -> Path:
    """bench/baselines.yaml of the repo holding config/ (or of `repo`)."""
    return (repo if repo is not None else find_config_dir().parent).joinpath(*BASELINES_FILE)


def section(name: str, repo: Path | None = None) -> dict[str, Any]:
    """The raw `name` section of bench/baselines.yaml; ConfigError when it is missing."""
    path = baselines_path(repo)
    data = read_yaml(path, "bench baselines")
    if not isinstance(data, dict) or not isinstance(got := cast("dict[str, Any]", data).get(name), dict):
        raise ConfigError(f"{path.as_posix()}: no `{name}` section")
    return cast("dict[str, Any]", got)


def load[M: BaseModel](name: str, model: type[M], repo: Path | None = None) -> M:
    """The `name` section validated as `model`."""
    try:
        return model.model_validate(section(name, repo))
    except ValidationError as exc:
        raise ConfigError(f"bench/baselines.yaml `{name}`: {exc}") from None


def config_sha256(pipeline_sha256: str, name: str, repo: Path | None = None) -> str:
    """A baseline method's config hash (03 §13.4 `configs[].config_sha256`): the SHA-256 of the
    pipeline config it reads its inputs with and of its baselines.yaml section."""
    return sha256_json({"baseline": section(name, repo), "pipeline": pipeline_sha256})
