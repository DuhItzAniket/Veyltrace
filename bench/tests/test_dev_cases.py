"""The development-case list (04 §1): one case per RE2 system, excluded from every run it lists."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from veyltrace_bench import experiment
from veyltrace_bench.experiment import Experiment, read_yaml, select_cases
from veyltrace_core.adapters import adapter_for
from veyltrace_core.config import data_root
from veyltrace_core.ids import is_case_id

REPO = Path(__file__).resolve().parents[2]
DEV_CASES = "bench/dev_cases.yaml"
RE2 = ("re2-ob", "re2-ss", "re2-tt")
#: The lead's pick (16 Nov 2026), one per RE2 system; the file must hold exactly these.
EXPECTED = {"re2-ob": "97bf1c72d29f", "re2-ss": "bc159c2c3cde", "re2-tt": "3cfc8cf70d39"}


def _dev_ids() -> list[str]:
    ids = read_yaml(REPO / DEV_CASES, "case list")
    assert isinstance(ids, list) and all(isinstance(i, str) and is_case_id(i) for i in ids)
    return [str(i) for i in ids]


def _re2_experiment() -> Experiment:
    return Experiment.model_validate(
        {
            "experiment_id": "dev-cases-test",
            "description": "x",
            "dataset": {"parts": list(RE2), "exclude": DEV_CASES},
            "methods": [{"id": "veyltrace:off", "kind": "veyltrace"}],
            "metrics": ["ac_at_k"],
        }
    )


def test_one_development_case_per_re2_system() -> None:
    assert _dev_ids() == list(EXPECTED.values())  # in RE2 part order; no extra id, no duplicate


@dataclass(frozen=True)
class _Listing:
    """A stand-in adapter: each RE2 part lists its development case and two other ids."""

    def list_cases(self, dataset: str, root: Path) -> list[str]:
        del root
        n = RE2.index(dataset)
        return [EXPECTED[dataset], f"{n}0000000000a", f"{n}0000000000b"]


def test_the_runner_excludes_the_development_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experiment, "adapter_for", lambda dataset: _Listing())
    selected = select_cases(_re2_experiment(), REPO)
    for n, part in enumerate(RE2):
        assert selected[part] == ([f"{n}0000000000a", f"{n}0000000000b"], [EXPECTED[part]])


@pytest.mark.real_data
def test_development_cases_are_in_the_re2_index() -> None:
    listed = {part: set(adapter_for(part).list_cases(part, data_root())) for part in RE2}
    if not all(listed.values()):
        pytest.skip(f"RE2 not fetched under {data_root()}")
    for part, case in EXPECTED.items():
        assert case in listed[part], (part, case)
    selected = select_cases(_re2_experiment(), REPO)
    for part, (run, excluded) in selected.items():
        assert excluded == [EXPECTED[part]] and EXPECTED[part] not in run
        assert len(run) == len(listed[part]) - 1
