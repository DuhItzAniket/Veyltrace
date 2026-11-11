"""Answer keys (03 §13.1): load them for scoring, and derive the RCAEval ones from the case layout.

Evaluation only: only bench reads answer keys, and they are never committed (bench/AGENTS.md). Each
is `${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet`, written and read through core io (schema, unique
case_id, row order); core's fetcher writes synth's (`veyltrace data fetch synth`). An RCAEval label
*is* the case folder name `{service}_{fault}`, its injection time `inject_time.txt` (rcaeval_facts
"Dataset layout", "Ground truth and scoring"; 04 §3), so bench derives the rows from the tree; the
`case_id` hashes the rcaeval adapter's canonical case key (01 §3.2), so key and run share one id.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final, NamedTuple, cast

import pyarrow as pa
from pydantic import ValidationError

from veyltrace_contracts.models import AnswerKeyRow, FaultClass, Indicator, Mode, System
from veyltrace_core import io, textio
from veyltrace_core.config import data_root as default_data_root
from veyltrace_core.errors import ConfigError, ContractValidationError, UsageError, VeyltraceError
from veyltrace_core.ids import case_id

ANSWER_KEY: Final = "answer_key"
ANSWER_KEY_DIR: Final = "answer_keys"  # 03 §13.1: ${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet
INJECT_TIME_FILE: Final = "inject_time.txt"  # integer Unix seconds on line 1 (rcaeval_facts "Dataset layout")
NS_PER_S: Final = 1_000_000_000
_DATASET: Final = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # 03 §1 dataset pattern; also blocks "../"

#: The rcaeval adapter's canonical case key (01 §3.2), spelt only here: the Hugging Face case
#: directory name, lowercase (re2tt_ts-order-service_cpu_1). Zenodo paths convert to the same string.
RCAEVAL_KEY_FORMAT: Final = "{release}{system}_{service}_{fault}_{rep}"
_HF_NAME: Final = re.compile(r"(re[123])(ob|ss|tt)_([^_]+)_([^_]+)_([0-9]+)")
_SUITE: Final = re.compile(r"(re[123])-(ob|ss|tt)")  # dataset ids such as re2-ob (04 §3, §9)
#: Zenodo case directory, last three parts: RE{n}-{SYS}/{service}_{fault}/{rep} (rcaeval_facts).
_ZENODO: Final = re.compile(r"(re[123])-(ob|ss|tt)/([^_/]+)_([^_/]+)/([0-9]+)")
#: Mislabelled Zenodo folders, (suite, service, fault) -> fault: RE3-TT ts-route-service_f6 is
#: really F3 (rcaeval_facts "Data quirks"; RCAEval issue #43; 04 §3).
ZENODO_RELABEL: Final = MappingProxyType({("re3-tt", "ts-route-service", "f6"): "f3"})
#: Infralume's normalisation defaults (01 §3.4 steps 1, 4, 5; §4), so root_service is the adapter's name.
SERVICE_ALIASES: Final = MappingProxyType({"ob": {"frontendservice": "frontend"}})  # normalise.aliases
COMPONENT_SUFFIXES: Final = ("-db",)  # normalise.component_suffixes


class FaultTruth(NamedTuple):
    """What an RCAEval fault label means in the contract vocabularies (03 §1)."""

    fault_class: FaultClass | None
    mode: Mode
    indicator: Indicator | None


_RESOURCE: Final = {"cpu": FaultTruth("cpu", "resource", "cpu"), "mem": FaultTruth("mem", "resource", "mem")}
_NETWORK: Final = {
    "delay": FaultTruth("delay", "network", "latency"),
    "loss": FaultTruth("loss", "network", "latency"),
}
#: Fault labels per release (04 §3) -> truth. Modes follow the injector: stress-ng for cpu, mem, disk,
#: socket (`resource`), tc for delay, loss (`network`), source mutation for F1-F5 (`code`) (rcaeval_facts
#: "Datasets and telemetry per system"). Indicators are RCAEval's fine-grained answers (04 §7; main.py
#: L559-618): RE1 has no disk metric, so its disk faults score against latency (RCAEval issue #77).
#: F1-F5 have no fault class (07 open question 7) and no indicator-level score (04 §7): both null.
RELEASE_FAULTS: Final[Mapping[str, Mapping[str, FaultTruth]]] = MappingProxyType(
    {
        "re1": {**_RESOURCE, **_NETWORK, "disk": FaultTruth("disk", "resource", "latency")},
        "re2": {
            **_RESOURCE,
            **_NETWORK,
            "disk": FaultTruth("disk", "resource", "diskio"),
            "socket": FaultTruth("socket", "resource", "socket"),
        },
        "re3": {code: FaultTruth(None, "code", None) for code in ("f1", "f2", "f3", "f4", "f5")},
    }
)


class LayoutError(VeyltraceError, ValueError):
    """An RCAEval source tree does not match the documented layout (01 §3.3; rcaeval_facts)."""


class CaseKey(NamedTuple):
    """The parts of one RCAEval canonical case key, lowercase, before name normalisation."""

    release: str
    system: str
    service: str
    fault: str
    rep: str

    @property
    def suite(self) -> str:
        return f"{self.release}-{self.system}"

    @property
    def key(self) -> str:
        return RCAEVAL_KEY_FORMAT.format(**self._asdict())


def parse_case_dir(parts: Sequence[str]) -> CaseKey:
    """The case key of a case directory from its path parts below the source root: Hugging Face
    names the directory by the key itself, Zenodo nests `RE{n}-{SYS}/{service}_{fault}/{rep}`."""
    low = [p.lower() for p in parts]
    if low and (hf := _HF_NAME.fullmatch(low[-1])):
        return CaseKey(*hf.groups())
    if zen := _ZENODO.fullmatch("/".join(low[-3:])):
        release, system, service, fault, rep = zen.groups()
        fault = ZENODO_RELABEL.get((f"{release}-{system}", service, fault), fault)
        return CaseKey(release, system, service, fault, rep)
    raise LayoutError(f"{'/'.join(parts) or '.'}: not an RCAEval case directory (Hugging Face or Zenodo)")


def normalise_service(raw: str, system: str) -> tuple[str, str | None]:
    """(service, component) by Infralume's rules (01 §3.4): trim, lowercase, the system's aliases, then
    fold a suffix (`carts-db` -> `carts`, component `carts-db`; as RCAEval). No `_`: labels split on it."""
    name = raw.strip().lower()
    name = SERVICE_ALIASES.get(system, {}).get(name, name)
    for suffix in COMPONENT_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)], name
    return name, None


def _inject_time_ns(path: Path) -> int:
    """inject_time.txt in ns, read as RCAEval's main.py does: `int(f.readlines()[0].strip())` s."""
    lines = textio.read_text(path).splitlines()
    try:
        return int(lines[0].strip()) * NS_PER_S
    except (IndexError, ValueError):
        raise LayoutError(f"{path}: expected an integer Unix time in seconds on the first line") from None


def _row(key: CaseKey, case_dir: Path) -> AnswerKeyRow:
    truth = RELEASE_FAULTS[key.release].get(key.fault)
    if truth is None:
        raise LayoutError(f"{case_dir}: fault label {key.fault!r} is not an {key.release.upper()} fault")
    service, component = normalise_service(key.service, key.system)
    try:
        return AnswerKeyRow(
            case_id=case_id(key.key),
            dataset=key.suite,
            system=cast("System", key.system),  # ob|ss|tt: _HF_NAME and _ZENODO admit no other
            is_no_fault=False,
            root_service=service,
            root_component=component,
            fault_class=truth.fault_class,
            fault_label=key.fault,
            indicator=truth.indicator,
            mode=truth.mode,
            t_inject_ns=_inject_time_ns(case_dir / INJECT_TIME_FILE),
            t_end_ns=None,  # RCAEval publishes no end time (12 min is stated for RE2-TT only)
            injection_json=None,  # not published by RCAEval (03 §13.1)
            extra_roots_json=None,
            decoy_changes_json=None,  # RCAEval-C overlays (O-13) add these, plain RCAEval has none
            validated=None,
            sli_impact_json=None,
        )
    except ValidationError as exc:
        raise LayoutError(f"{case_dir}: {exc}") from None


def rcaeval_answer_key_rows(suite: str, source_root: Path) -> list[AnswerKeyRow]:
    """One row per case of `suite` (e.g. re2-ob) under `source_root`, in case_id order. A case dir
    holds inject_time.txt; other suites are skipped, so the Hugging Face root can be passed as is."""
    if (wanted := _SUITE.fullmatch(suite)) is None:
        raise UsageError(f"unknown RCAEval suite {suite!r}; expected re1|re2|re3 + -ob|-ss|-tt")
    root = Path(source_root)
    found: dict[str, tuple[Path, AnswerKeyRow]] = {}
    for marker in sorted(root.rglob(INJECT_TIME_FILE), key=lambda p: p.relative_to(root).as_posix().encode()):
        case_dir = marker.parent
        key = parse_case_dir(case_dir.relative_to(root).parts)
        if (key.release, key.system) != wanted.groups():
            continue
        if key.key in found:
            raise LayoutError(f"case {key.key!r} appears twice: {found[key.key][0]} and {case_dir}")
        found[key.key] = (case_dir, _row(key, case_dir))
    if not found:
        raise LayoutError(f"no {suite} case directory (with {INJECT_TIME_FILE}) under {root}")
    return sorted((row for _, row in found.values()), key=lambda r: r.case_id)


def answer_key_path(dataset: str, data_root: Path | None = None) -> Path:
    """`<data root>/answer_keys/<dataset>.parquet`; the data root defaults to $VEYLTRACE_DATA."""
    if _DATASET.fullmatch(dataset) is None:
        raise UsageError(f"invalid dataset id {dataset!r} (03 §1: ^[a-z0-9]+(-[a-z0-9]+)*$)")
    root = default_data_root() if data_root is None else Path(data_root)
    return root / ANSWER_KEY_DIR / f"{dataset}.parquet"


def write_answer_keys(
    dataset: str, rows: Sequence[AnswerKeyRow], data_root: Path | None = None
) -> tuple[Path, str]:
    """Write `rows` as the answer key of `dataset` through core io; (path, sha256)."""
    path = answer_key_path(dataset, data_root)
    for parent in path.resolve().parents:  # never inside a git work tree (bench/AGENTS.md Never 5)
        if (parent / ".git").exists():
            raise ConfigError(f"answer keys may not be written inside the git work tree {parent}")
    if stray := sorted({r.dataset for r in rows} - {dataset}):
        raise ContractValidationError(ANSWER_KEY, f"rows of dataset(s) {stray} in the {dataset} key")
    return path, io.write_path(ANSWER_KEY, list(rows), path)


def build_rcaeval_answer_keys(suite: str, source: Path, data_root: Path | None = None) -> tuple[Path, str]:
    """Derive the answer key of an RCAEval suite from its source tree and write it; (path, sha256)."""
    return write_answer_keys(suite, rcaeval_answer_key_rows(suite, source), data_root)


def load_answer_keys(dataset: str, data_root: Path | None = None) -> dict[str, AnswerKeyRow]:
    """`dataset`'s answer key by case_id (in case_id order), fully validated; ArtifactMissing if unfetched."""
    path = answer_key_path(dataset, data_root)
    table = io.read_path(ANSWER_KEY, path, validate=True)
    if not isinstance(table, pa.Table):  # answer_key is a Parquet contract, so io returns a table
        raise ContractValidationError(ANSWER_KEY, f"{path}: read as {type(table).__name__}")
    keys: dict[str, AnswerKeyRow] = {}
    for row in map(AnswerKeyRow.model_validate, table.to_pylist()):
        if row.dataset != dataset:
            raise ContractValidationError(ANSWER_KEY, f"{path}: {row.case_id} has dataset {row.dataset!r}")
        keys[row.case_id] = row
    return keys
