"""The events overlay (01 §3.10): extra change events merged into a case at materialise.

Bench's RCAEval-C generator writes one `telemetry.events` file per case under the data root, and
the run names it in `events.overlay_path`. Its rows are treated as untrusted input: entities go
through the case's name rules, details through the scrubber, and every row is stamped
`source_system = synthetic` with a null `actor`, so no column can tell a true change from a
decoy (02 §6.4). Infralume never reads `bench/` or `lab/`: the path is resolved under
`${VEYLTRACE_DATA}` only.
"""

from __future__ import annotations

import json
from typing import Any, Final, cast

import pyarrow as pa

from veyltrace_core import io
from veyltrace_core.config import data_path
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.hashing import sha256_file
from veyltrace_infralume.names import InvalidName, NameRules
from veyltrace_infralume.scrub import Scrubber

__all__ = ["INPUT_NAME", "SOURCE_SYSTEM", "load_overlay"]

EVENTS: Final = "telemetry.events"
INPUT_NAME: Final = "overlay/events.parquet"  # 01 §3.8: the overlay's entry in `inputs`
SOURCE_SYSTEM: Final = "synthetic"  # 01 §3.10: every overlay row
KEY: Final = "infralume.events.overlay_path"


def load_overlay(relpath: str, rules: NameRules, scrub: Scrubber) -> tuple[pa.Table, tuple[str, str, int]]:
    """The overlay at `relpath` under the data root as contract rows, and its `inputs` entry.

    Rows whose entity is a dropped container or a fault-tool service, or whose detail names a
    chaos object, are dropped and counted in `scrub.dropped_rows`, as the adapters do.
    """
    path = data_path(relpath)
    if not path.is_file():
        raise ConfigError(f"{KEY}: no file at {relpath!r} under the data root")
    try:
        raw = cast("pa.Table", io.read_path(EVENTS, path))
    except (ContractValidationError, pa.ArrowException) as exc:
        raise ConfigError(f"{KEY}: {relpath!r} is not a telemetry.events file: {exc}") from exc
    columns: dict[str, list[Any]] = {name: [] for name in io.arrow_schema(EVENTS).names}
    for row in raw.to_pylist():
        try:
            name = rules.normalise(str(row["entity"]))
        except InvalidName as exc:
            raise ConfigError(f"{KEY}: {exc}") from exc
        if name is None or name.component in scrub.rules.drop_services:
            scrub.dropped_rows += 1
            continue
        detail = scrub.event_detail(
            str(row["kind"]), cast("dict[str, object]", json.loads(row["detail_json"]))
        )
        if detail is None:
            continue  # a chaos object: event_detail counted it
        for column, value in (
            ("t_ns", row["t_ns"]),
            ("entity", name.component),
            ("kind", row["kind"]),
            ("source_system", SOURCE_SYSTEM),
            ("detail_json", detail),
            ("actor", None),
        ):
            columns[column].append(value)
    table = pa.Table.from_pydict(columns, schema=io.arrow_schema(EVENTS))
    return table, (INPUT_NAME, sha256_file(path), path.stat().st_size)
