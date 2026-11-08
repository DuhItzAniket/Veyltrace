"""Golden-fixture layout: where each contract's fixture lives, the variant table, and loaders.

Why: every producer ships golden fixtures for `synth-01…05` so consumers build against them
without waiting for each other (02 §7 rule 3; 03 §1). The layout mirrors a run directory:
`packages/<producer>/fixtures/<case>[@<variant>]/<run-dir path>`, except that the two-phase
artefact `evidence` is stored phase-qualified (`evidence.main.parquet` after FaultLoom's main pass,
`evidence.final.parquet` after the claim pass), because both versions are read by different
consumers (M0 lead decision 2026-11-06 §2.10).

Test helpers only: engines never import this package (AST ban, isolation test).
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Literal, get_args

import pyarrow as pa
from pydantic import BaseModel

from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.ids import AIMode

__all__ = [
    "FIXTURES_DIR",
    "FIXTURE_CODE_COMMIT",
    "PRODUCER",
    "SYNTH_CASES",
    "TWO_PHASE",
    "VARIANTS",
    "VARIANT_SEPARATOR",
    "ExpectedOutcome",
    "FixturePhase",
    "Variant",
    "fixture_case",
    "fixture_dir",
    "fixture_relpath",
    "golden",
    "golden_file",
    "golden_path",
    "missing_fixture",
    "producer_of",
    "repo_root",
    "split_case",
]

SYNTH_CASES: Final[tuple[str, ...]] = ("synth-01", "synth-02", "synth-03", "synth-04", "synth-05")
#: Separator between a base case and its variant in fixture directory names (synth-01@fake).
VARIANT_SEPARATOR: Final = "@"
FIXTURES_DIR: Final = "fixtures"
#: code_commit pinned by fixture generation, so goldens do not churn per commit (lead §2.10).
FIXTURE_CODE_COMMIT: Final = "fixture"

#: Which package produces each run-dir contract (03 §1 catalog, 02 §3). Contracts outside a run
#: directory (answer_key, bench_result, calibration, predicates) have no golden fixture here.
PRODUCER: Final[Mapping[str, str]] = MappingProxyType(
    {
        "case_manifest": "infralume",
        "telemetry.metrics": "infralume",
        "telemetry.logs": "infralume",
        "telemetry.spans": "infralume",
        "telemetry.events": "infralume",
        "alert": "core",
        "signal_cube.series": "signalyth",
        "signal_cube.edges": "signalyth",
        "signal_cube.templates": "signalyth",
        "signal_cube.critical_path": "signalyth",
        "anomalies": "anomara",
        "onsets": "anomara",
        "alignment": "causync",
        "changes": "causync",
        "graph.nodes": "causalith",
        "graph.edges": "causalith",
        "graph.paths": "causalith",
        "evidence": "faultloom",
        "slate": "causatrix",
        "proposals": "relentra",
        "agent_trace": "relentra",
        "verdict": "causentra",
        "card": "causivra",
        "config_lock": "core",
        "run_manifest": "core",
        "receipt": "causivra",
    }
)

FixturePhase = Literal["main", "final"]
FIXTURE_PHASES: Final[tuple[str, ...]] = get_args(FixturePhase)
#: Contracts written twice in one run, with the fixture phase each pipeline sub-step produces.
TWO_PHASE: Final[Mapping[str, Mapping[str, FixturePhase]]] = MappingProxyType(
    {"evidence": MappingProxyType({"faultloom": "main", "faultloom.claim_pass": "final"})}
)

ExpectedOutcome = Literal["ok", "failed", "no_alert", "rejected"]


@dataclass(frozen=True)
class Variant:
    """A fixture variant: a synth base case run with config overrides and an AI mode.

    `generator` names a synth generator variant (e.g. "silent": cart-1 stops all telemetry at the
    injection time) for variants that change the data rather than the config; the synth adapter
    (R-03) interprets it. `expected_outcome` is the RunSummary outcome the variant must produce.
    """

    base_case: str
    overrides: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    ai_mode: AIMode = "off"
    expected_outcome: ExpectedOutcome = "ok"
    generator: str | None = None
    description: str = ""


def _drop(*sources: str) -> Mapping[str, Any]:
    # infralume.sources.drop takes the source names of 03 §1 (metrics|logs|traces|events).
    return MappingProxyType({"infralume.sources.drop": list(sources)})


#: The fixture variants (critic gap "fixtures have no variant dimension", plus synth-05@silent;
#: M0 lead decision 2026-11-06 §2.10 and §2.11). Keys are fixture directory names.
VARIANTS: Final[Mapping[str, Variant]] = MappingProxyType(
    {
        "synth-01@fake": Variant(
            "synth-01",
            MappingProxyType({"llm.provider": "fake"}),
            ai_mode="record",
            description="AI on with the FakeProvider (Relentra, claim pass, Causentra, Causivra)",
        ),
        "synth-01@detected": Variant(
            "synth-01",
            MappingProxyType({"core.alert.protocol": "detected"}),
            description="detected alert protocol: alert.detector set, hint blanked",
        ),
        "synth-01@metrics": Variant(
            "synth-01", _drop("logs", "traces", "events"), description="FR-4: metrics only"
        ),
        "synth-01@logs": Variant(
            "synth-01", _drop("metrics", "traces", "events"), description="FR-4: logs only"
        ),
        "synth-01@traces": Variant(
            "synth-01", _drop("metrics", "logs", "events"), description="FR-4: traces only"
        ),
        "synth-01@events": Variant(
            "synth-01",
            _drop("metrics", "logs", "traces"),
            description="FR-4: events only (the neutral k8s events keep both windows in the span)",
        ),
        "synth-01@noevents": Variant(
            "synth-01", _drop("events"), description="FR-4: no change events (RCAEval-shaped)"
        ),
        "synth-05@silent": Variant(
            "synth-05",
            generator="silent",
            description="cart-1 stops all telemetry at t_inject: silence atoms, T4 on cart, not NO_FAULT",
        ),
    }
)


@functools.cache
def repo_root() -> Path:
    """The work-tree root (the directory holding `packages/` and `contracts/schemas/`).

    Found by walking up from this file, so it works from any CWD with an editable install.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages").is_dir() and (parent / "contracts" / "schemas").is_dir():
            return parent
    msg = f"cannot find the Veyltrace work tree above {here}; testing helpers need an editable install"
    raise FileNotFoundError(msg)


def split_case(case: str) -> tuple[str, str | None]:
    """Split "synth-01@fake" into ("synth-01", "fake"); a plain case gives (case, None)."""
    base, sep, variant = case.partition(VARIANT_SEPARATOR)
    return (base, variant) if sep else (base, None)


def fixture_case(case: str, variant: str | None = None) -> str:
    """The fixture directory name for `case` and an optional `variant`, validated.

    `case` is a synth case (synth-0N) or a full variant name (synth-01@fake); passing a variant
    both ways is an error. Unknown cases and variants raise KeyError, so typos fail loudly.
    """
    base, embedded = split_case(case)
    if embedded is not None and variant is not None:
        msg = f"variant given twice: case {case!r} and variant={variant!r}"
        raise ValueError(msg)
    name = embedded if embedded is not None else variant
    if base not in SYNTH_CASES:
        msg = f"unknown fixture case {base!r}; expected one of {', '.join(SYNTH_CASES)}"
        raise KeyError(msg)
    if name is None:
        return base
    full = f"{base}{VARIANT_SEPARATOR}{name}"
    if full not in VARIANTS:
        msg = f"unknown fixture variant {full!r}; expected one of {', '.join(sorted(VARIANTS))}"
        raise KeyError(msg)
    return full


def fixture_dir(package: str, case: str, *, variant: str | None = None) -> Path:
    """`packages/<package>/fixtures/<case>[@<variant>]/` (it may not exist yet)."""
    return repo_root() / "packages" / package / FIXTURES_DIR / fixture_case(case, variant)


def producer_of(contract: str) -> str:
    """The package that owns the golden fixture of `contract`."""
    try:
        return PRODUCER[contract]
    except KeyError:
        msg = f"contract {contract!r} has no golden fixture; expected one of {', '.join(sorted(PRODUCER))}"
        raise KeyError(msg) from None


def fixture_relpath(contract: str, phase: str | None = None) -> str:
    """Fixture-relative POSIX path of `contract`: its run-dir path, phase-qualified if two-phase.

    A two-phase contract (evidence) needs phase "main" or "final"; any other contract refuses a
    phase, so a test cannot silently read the wrong version.
    """
    producer_of(contract)
    path = PurePosixPath(CONTRACTS[contract].path)
    if contract in TWO_PHASE:
        if phase not in FIXTURE_PHASES:
            msg = f"contract {contract!r} has two versions; pass phase='main' or phase='final'"
            raise ValueError(msg)
        return str(path.with_name(f"{path.stem}.{phase}{path.suffix}"))
    if phase is not None:
        msg = f"contract {contract!r} has one version; phase={phase!r} does not apply"
        raise ValueError(msg)
    return str(path)


def golden_path(contract: str, case: str, *, variant: str | None = None, phase: str | None = None) -> Path:
    """Path of the producer's golden fixture for `contract` (it may not exist yet)."""
    rel = fixture_relpath(contract, phase)
    return fixture_dir(producer_of(contract), case, variant=variant) / rel


def golden_file(package: str, case: str, relpath: str, *, variant: str | None = None) -> Path:
    """Path of a non-contract fixture file (card.md, a CIResult record, a cassette entry)."""
    rel = PurePosixPath(relpath)
    if rel.is_absolute() or ".." in rel.parts or "\\" in relpath:
        msg = f"fixture relpath must be relative POSIX without '..', got {relpath!r}"
        raise ValueError(msg)
    return fixture_dir(package, case, variant=variant) / rel


def missing_fixture(name: str, path: Path, producer: str) -> ArtifactMissing:
    """The error for an absent golden fixture, naming the command that regenerates it."""
    err = ArtifactMissing(name, path)
    err.add_note(
        f"golden fixture not generated yet; its producer runs "
        f"`uv run python scripts/check.py --package {producer} --update-golden` (upstream fixtures "
        f"first; `--update-golden --cascade` regenerates every producer in pipeline order)"
    )
    return err


def golden(
    contract: str, case: str, *, variant: str | None = None, phase: str | None = None
) -> BaseModel | pa.Table | list[BaseModel]:
    """Load a golden fixture with the same types as io.read (model, Arrow table or JSONL lines).

    Like io.read, case_manifest comes back hint-redacted (D-15); Infralume compares its own
    manifest, hint included, with assert_golden, which reads fixtures unredacted."""
    path = golden_path(contract, case, variant=variant, phase=phase)
    if not path.is_file():
        raise missing_fixture(contract, path, producer_of(contract))
    return io.read_path(contract, path)
