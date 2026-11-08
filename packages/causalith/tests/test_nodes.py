"""Unit tests of nodes, node kinds and external hosts (05-causalith §3.1, §3.2, §7)."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

import pyarrow as pa

from veyltrace_causalith.graph import KindRules, external_hosts, node_kinds, span_attrs
from veyltrace_causalith.settings import causalith_config
from veyltrace_core.config import load_section_file

CFG = causalith_config(load_section_file("causalith"))


def test_defaults_match_the_spec_table() -> None:
    assert (CFG.graph.include_external, CFG.graph.external_min_calls) == (True, 10)
    assert [p.pattern for p in CFG.kinds.cache] == ["redis", "memcached", "valkey"]


def _spans(rows: Sequence[tuple[str, str, dict[str, str] | None]]) -> pa.Table:
    data = [{"service": s, "kind": k, "attrs_json": None if a is None else json.dumps(a)} for s, k, a in rows]
    return pa.Table.from_pylist(data)


def test_external_hosts_need_enough_client_spans_and_no_known_name() -> None:
    spans = _spans(
        [("payment", "client", {"server.address": "card-gateway.example:443"})] * 10
        + [("payment", "client", {"peer.service": "fraud.example"})] * 9
        + [("cart", "client", {"server.address": "redis-cart.default.svc.cluster.local:6379"})] * 12
        + [("frontend", "client", {"server.address": "cart:7070"})] * 20
        + [("payment", "server", {"server.address": "ignored.example"})] * 20
    )
    hosts = external_hosts(spans, ["cart", "frontend", "payment"], 10)
    assert sorted(hosts) == ["card-gateway.example", "redis-cart.default.svc.cluster.local"]


def test_node_kind_precedence() -> None:
    rules = CFG.kinds
    attrs = {
        "frontend": [{"db.system": "redis"}],  # entry wins over everything
        "redis-cart": [{"db.system": "redis"}],
        "orders-db": [],
        "catalog": [{"db.system": "postgresql"}],
        "events": [{"messaging.system": "kafka"}],
        "card-gateway.example": [],
        "cart": [],
    }
    kinds = node_kinds(
        sorted(attrs),
        frozenset({"frontend"}),
        frozenset({"card-gateway.example", "redis-cart"}),
        attrs,
        rules,
    )
    assert kinds == {
        "card-gateway.example": "external",
        "cart": "service",
        "catalog": "db",
        "events": "queue",
        "frontend": "entry",
        "orders-db": "db",
        "redis-cart": "cache",
    }
    assert node_kinds(
        ["mongo-user"], frozenset(), frozenset(), {}, KindRules((re.compile("mongo"),), (), ())
    ) == {"mongo-user": "db"}


def test_a_service_calling_a_database_is_not_a_database() -> None:
    spans = _spans(
        [("cart", "client", {"db.system": "redis", "server.address": "redis-cart"}), ("cart", "server", None)]
    )
    attrs = span_attrs(spans, {})
    assert node_kinds(["cart"], frozenset(), frozenset(), attrs, CFG.kinds) == {"cart": "service"}
