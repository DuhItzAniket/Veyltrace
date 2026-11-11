"""RCAEval canonical case keys (01 §3.2): one key per case, whichever mirror holds it.

Why: `case_id` hashes this key, and bench derives its answer keys from the same string, so a case
fetched from Hugging Face or Zenodo gets one id everywhere (03 §1). The key is the Hugging Face case
directory name, lowercase (`re2ob_checkoutservice_cpu_1`); a Zenodo path
`RE2/RE2-OB/checkoutservice_cpu/1` converts to the same string. The key encodes the label (the
folder name is the RCAEval ground truth, rcaeval_facts "Ground truth and scoring"), so it never
leaves Infralume: engines only ever see the `case_id`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from veyltrace_core.errors import UsageError
from veyltrace_core.ids import case_id as make_case_id

__all__ = ["KEY_FORMAT", "SUITES", "ZENODO_RELABEL", "CaseKey", "parse_case_dir", "parse_suite"]

#: The canonical key (01 §3.2), the Hugging Face directory name; bench spells the same format.
KEY_FORMAT: Final = "{release}{system}_{service}_{fault}_{rep}"
#: Every RCAEval suite, as dataset ids (03 §2.1 `dataset`): RE1, RE2, RE3 × OB, SS, TT.
SUITES: Final[tuple[str, ...]] = tuple(f"re{n}-{s}" for n in (1, 2, 3) for s in ("ob", "ss", "tt"))
_SUITE: Final = re.compile(r"(re[123])-(ob|ss|tt)")
_HF: Final = re.compile(r"(re[123])(ob|ss|tt)_([^_/]+)_([^_/]+)_([0-9]+)")
_ZENODO: Final = re.compile(r"(re[123])-(ob|ss|tt)/([^_/]+)_([^_/]+)/([0-9]+)")
#: Mislabelled Zenodo folders, (suite, service, fault) -> fault: RE3-TT `ts-route-service_f6` is
#: really F3 (rcaeval_facts "Data quirks"; RCAEval issue #43). Bench applies the same table.
ZENODO_RELABEL: Final = MappingProxyType({("re3-tt", "ts-route-service", "f6"): "f3"})


@dataclass(frozen=True)
class CaseKey:
    """The parts of one canonical case key, lowercase, before service-name normalisation."""

    release: str
    system: str
    service: str
    fault: str
    rep: str

    @property
    def suite(self) -> str:
        """The dataset id of the case's suite, e.g. `re2-ob`."""
        return f"{self.release}-{self.system}"

    @property
    def key(self) -> str:
        """The canonical case key string (01 §3.2)."""
        return KEY_FORMAT.format(
            release=self.release, system=self.system, service=self.service, fault=self.fault, rep=self.rep
        )

    @property
    def case_id(self) -> str:
        """First 12 hex of SHA-256 of the key (03 §1)."""
        return make_case_id(self.key)


def parse_case_dir(parts: Sequence[str]) -> CaseKey | None:
    """The key of a case directory from its path parts, or None if it is not a case directory.

    Hugging Face names the directory by the key itself; Zenodo nests
    `RE{n}-{SYS}/{service}_{fault}/{rep}`, so its last three parts are read.
    """
    low = [p.lower() for p in parts]
    if low and (hf := _HF.fullmatch(low[-1])):
        return CaseKey(*hf.groups())
    if zen := _ZENODO.fullmatch("/".join(low[-3:])):
        release, system, service, fault, rep = zen.groups()
        fault = ZENODO_RELABEL.get((f"{release}-{system}", service, fault), fault)
        return CaseKey(release, system, service, fault, rep)
    return None


def parse_suite(suite: str) -> tuple[str, str]:
    """(release, system) of a suite id such as `re2-ob`; UsageError for anything else."""
    found = _SUITE.fullmatch(suite)
    if found is None:
        msg = f"unknown RCAEval suite {suite!r}; expected one of {', '.join(SUITES)}"
        raise UsageError(msg)
    return found.group(1), found.group(2)
