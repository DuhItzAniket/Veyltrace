"""The request a `veyltrace.fetchers` plugin receives from `veyltrace data fetch` (core_api_spec §9).

Why a module of its own: fetchers (Infralume's dataset downloaders, core's synth generator) need the
type, but must not import the CLI or the pipeline. It is a plain frozen dataclass with no imports
beyond the stdlib, so importing it never loads anything an isolation check would flag.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

__all__ = ["FETCH_SOURCES", "FetchFn", "FetchRequest", "FetchSource"]

#: Download mirrors a fetcher may be asked to use (01 §3.11: Hugging Face or Zenodo).
FetchSource = Literal["hf", "zenodo"]
FETCH_SOURCES: tuple[str, ...] = get_args(FetchSource)


@dataclass(frozen=True)
class FetchRequest:
    """One `data fetch` call: which dataset, where the data root is, and optional narrowing.

    `suite` picks a sub-suite (e.g. re2-ss), `source` a mirror, and `cases` caps how many cases
    are fetched; None means the fetcher's default for each.
    """

    name: str
    data_root: Path
    suite: str | None = None
    source: FetchSource | None = None
    cases: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            msg = "FetchRequest.name must be a non-empty fetcher name"
            raise ValueError(msg)
        if self.source is not None and self.source not in FETCH_SOURCES:
            msg = f"FetchRequest.source must be one of {FETCH_SOURCES}, got {self.source!r}"
            raise ValueError(msg)
        if self.cases is not None and (isinstance(self.cases, bool) or self.cases < 1):
            msg = f"FetchRequest.cases must be a positive int, got {self.cases!r}"
            raise ValueError(msg)


#: Signature of a `veyltrace.fetchers` entry point: returns a process exit code (0 = ok).
FetchFn = Callable[[FetchRequest], int]
