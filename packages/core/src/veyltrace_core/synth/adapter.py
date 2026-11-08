"""The `synth` dataset adapter (entry point `veyltrace.adapters:synth`; 02 §6.1, 01 §1).

It resolves `synth-0N` names, generator-variant names (`synth-05@silent`) and their 12-hex case
ids, and converts a case by generating it (`generate.generate`). There are no raw files, so
`inputs` is empty (synth_spec D-S2) and the case is never cached by Infralume (`cacheable =
False`): a generator edit must never be served stale telemetry (critic gap, accepted).

The hint is the oracle injection time for every case (synth-05 uses the same placed alert time);
Infralume blanks it under the detected protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from veyltrace_core.adapters import SOURCE_NAMES, CanonicalCase, CaseRef
from veyltrace_core.errors import UsageError
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.ids import is_case_id
from veyltrace_core.synth import layout as lay
from veyltrace_core.synth.generate import generate

if TYPE_CHECKING:
    from veyltrace_core.config import EngineConfig

__all__ = ["CASE_KEYS", "SynthAdapter", "resolve_key"]

#: Every canonical key the adapter resolves: the five cases, then the generator variants.
CASE_KEYS: Final[tuple[str, ...]] = (*lay.CASE_NAMES, *sorted(lay.GENERATOR_VARIANTS))
_BY_ID: Final[dict[str, str]] = {make_case_id(key): key for key in CASE_KEYS}


def resolve_key(case: str) -> str:
    """The canonical key of a synth case given by name or 12-hex id; UsageError if unknown."""
    if case in CASE_KEYS:
        return case
    if is_case_id(case) and case in _BY_ID:
        return _BY_ID[case]
    msg = f"unknown {lay.DATASET} case {case!r}; expected one of {', '.join(CASE_KEYS)} or their case ids"
    raise UsageError(msg)


@dataclass(frozen=True)
class SynthAdapter:
    """Adapter protocol implementation for dataset `synth` (veyltrace_core.adapters.Adapter)."""

    name: str = lay.ADAPTER_NAME
    version: str = lay.ADAPTER_VERSION
    datasets: tuple[str, ...] = (lay.DATASET,)
    cacheable: bool = False

    def _check(self, dataset: str) -> None:
        if dataset != lay.DATASET:
            msg = f"the {self.name} adapter reads dataset {lay.DATASET!r}, not {dataset!r}"
            raise UsageError(msg)

    def resolve(self, dataset: str, case: str, data_root: Path) -> CaseRef:
        """Resolve a synth-0N name, a generator-variant name or a case id (data_root is unused)."""
        self._check(dataset)
        key = resolve_key(case)
        return CaseRef(dataset=dataset, case_id=make_case_id(key), canonical_key=key, location=None)

    def list_cases(self, dataset: str, data_root: Path) -> list[str]:
        """The five synth cases' ids, sorted (generator variants are fixtures, not cases)."""
        self._check(dataset)
        return sorted(make_case_id(name) for name in lay.CASE_NAMES)

    def convert(self, ref: CaseRef, cfg: EngineConfig) -> CanonicalCase:
        """Generate the case; every source is present and nothing is scrubbed (nothing leaks)."""
        self._check(ref.dataset)
        key = resolve_key(ref.canonical_key)
        telemetry = generate(key)
        hint, _source = self.alert_hint(ref)
        return CanonicalCase(
            system=lay.SYSTEM,
            tables=telemetry.tables,
            sources_present=dict.fromkeys(SOURCE_NAMES, True),
            inputs=(),
            adapter_name=self.name,
            adapter_version=self.version,
            scrub=(lay.SCRUB_RULES_VERSION, 0, 0),
            t_alert_hint_ns=hint,
            hint_source="oracle" if hint is not None else "none",
        )

    def alert_hint(self, ref: CaseRef) -> tuple[int | None, str]:
        """(injection time, "oracle") for every synth case, before protocol blanking."""
        resolve_key(ref.canonical_key)
        return lay.T_INJECT_NS, "oracle"
