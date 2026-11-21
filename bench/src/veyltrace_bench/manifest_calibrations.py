"""bench_manifest.calibrations (03 §13.4; CCR #404, #405): the calibration files behind a result.

A run's `config.lock.json` (03 §12.2) names the calibration file Causentra applied, with its hash
and content. bench reads it through core io from every recorded run's directory, so the manifest
lists what the runs actually used, not what a config would select. A file counts as fitted by the
experiment when the experiment fits (`calibration.fit`) and the file's own `experiment_id` is the
experiment's: a fitting experiment writes its files before its held-out runs read them (04 §5.4).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from veyltrace_bench.experiment import Experiment
from veyltrace_contracts.models import ConfigLock
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.pipeline import run_dir_for


def recorded(
    exp: Experiment, runs: Iterable[Mapping[str, object]], runs_root: Path
) -> list[dict[str, object]]:
    """{family_id, sha256, fitted} of every calibration file a recorded run read, sorted by family_id
    then sha256 (03 §13.4). `runs` are the manifest's runs[] entries and `runs_root` the directory
    their full runs were made in (bench's own, per experiment), absolute: the CLI resolves
    --runs-root, since a relative one would name another directory here than in the run children.
    A killed run (no run_id), a baseline's partial run (elsewhere) or a run that stopped before the
    manifest step (no lock) read none that bench can name; an uncalibrated run's lock has a null
    calibration."""
    found: set[tuple[str, str, bool]] = set()
    for run in runs:
        run_id = run.get("run_id")
        if not isinstance(run_id, str):
            continue
        run_dir = run_dir_for(runs_root, str(run["dataset"]), str(run["case_id"]), run_id)
        try:
            lock = io.read_model("config_lock", run_dir, ConfigLock)
        except ArtifactMissing:
            continue
        if (file := lock.calibration) is None:
            continue
        fitted = exp.calibration.fit and file.content.experiment_id == exp.experiment_id
        found.add((file.family_id, file.sha256, fitted))
    return [{"family_id": f, "sha256": h, "fitted": fitted} for f, h, fitted in sorted(found)]
