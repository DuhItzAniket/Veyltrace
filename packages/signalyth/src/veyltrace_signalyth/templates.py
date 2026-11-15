"""Drain3 log templates (02 §3.5 steps 3 to 5).

Mining runs on the distinct masked messages of a service, not on every line. Drain is
order-dependent, so the order is fixed: services A→Z, one fresh in-memory miner per service, its
messages by (count desc, text asc). A message's template is the final text of the cluster it was
put in, read after the last message. That makes templates and `template_id` a function of the
set of log lines alone: no persistence, no `alert.json`, no row order (02-signalyth AGENTS rules).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import duckdb
from drain3 import TemplateMiner  # pyright: ignore[reportMissingTypeStubs] - drain3 ships no types
from drain3.template_miner_config import (  # pyright: ignore[reportMissingTypeStubs] - as above
    TemplateMinerConfig,
)

from veyltrace_core.errors import ContractValidationError
from veyltrace_core.ids import short_id
from veyltrace_core.log import get_logger
from veyltrace_signalyth.loglines import DrainRules

__all__ = ["distinct_messages", "mine_templates", "template_id"]

_log = get_logger(__name__)
TEMPLATE_ID_HEX = 8
type Message = tuple[str, str, int]  # service, masked text, lines
type TemplateRow = tuple[str, str, str, str]  # service, masked text, template_id, template


def distinct_messages(con: duckdb.DuckDBPyConnection) -> list[Message]:
    """(service, masked, lines) per distinct masked message of the `lines` table, over the whole
    data range (02 §3.5 step 3). Rows without text are not mined."""
    rows = con.execute(
        "SELECT service, masked, count(*) FROM lines WHERE masked IS NOT NULL GROUP BY service, masked"
    ).fetchall()
    return [(str(s), str(m), int(n)) for s, m, n in rows]


def template_id(service: str, template: str) -> str:
    """`"T"` + the first 8 hex of sha256 of canonical JSON `[service, template]` (03 §3.3)."""
    return short_id("T", TEMPLATE_ID_HEX, [service, template])


def _mine(texts: list[str], rules: DrainRules) -> list[str]:
    """The final template of each text, fed to a fresh miner in the given order. The config is
    built here, so Drain3 never looks for a `drain3.ini` in the working directory; no masking
    (done in SQL) and no persistence handler."""
    config: Any = TemplateMinerConfig()
    config.drain_sim_th = rules.sim_th
    config.drain_depth = rules.depth
    config.drain_max_children = rules.max_children
    config.drain_max_clusters = None
    config.masking_instructions = []
    miner: Any = TemplateMiner(config=config)  # no persistence handler: in memory only
    clusters = [int(miner.add_log_message(text)["cluster_id"]) for text in texts]
    final = {int(c.cluster_id): str(c.get_template()) for c in miner.drain.clusters}
    return [final[c] for c in clusters]


def mine_templates(messages: Iterable[Message], rules: DrainRules) -> tuple[list[TemplateRow], list[str]]:
    """Templates of the distinct messages, in any input order: rows `(service, masked,
    template_id, template)` sorted by (service, masked), and the services that fell back.

    Clusters of one service with the same final text share a `template_id`. If Drain3 raises for
    a service, its masked strings are its templates (02 §6); the caller reports the fallback. Two
    different (service, template) pairs with the same id fail the step (02 §3.5 step 5)."""
    by_service: dict[str, list[tuple[int, str]]] = {}
    for service, masked, lines in messages:
        by_service.setdefault(service, []).append((-lines, masked))
    rows: list[TemplateRow] = []
    fallback: list[str] = []
    owner: dict[str, tuple[str, str]] = {}
    for service in sorted(by_service):
        texts = [text for _, text in sorted(by_service[service])]  # count desc, text asc
        try:
            templates = _mine(texts, rules)
        except Exception as exc:  # any Drain3 failure takes the documented fallback (02 §6)
            _log.warning("drain3_fallback", service=service, error=f"{type(exc).__name__}: {exc}")
            fallback.append(service)
            templates = texts
        for text, template in zip(texts, templates, strict=True):
            tid = template_id(service, template)
            if owner.setdefault(tid, (service, template)) != (service, template):
                detail = f"template_id {tid} collides: {owner[tid]!r} and {(service, template)!r}"
                raise ContractValidationError("signal_cube.templates", detail)
            rows.append((service, text, tid, template))
    return sorted(rows), fallback
