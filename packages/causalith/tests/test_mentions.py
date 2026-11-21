"""Unit tests of the mention matcher, log-mention and topology edges (05-causalith §3.4, §3.5, §7)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_causalith.mentions import Matcher, log_edges, topology_edges

M = Matcher.build(["carts", "cartservice", "catalog", "checkout", "frontend", "ts-order-service"])


@pytest.mark.parametrize(
    ("text", "speaker", "expected"),
    [
        ("failed to get cart from cartservice:7070", "frontend", {"cartservice"}),  # host:port
        ("dial cartservice.default.svc.cluster.local:7070", "frontend", {"cartservice"}),  # DNS suffix
        ("GET http://carts:80/carts/1", "frontend", {"carts"}),  # URL
        ("dial mongodb://carts-db:27017/data", "frontend", set()),  # a hyphenated host is another name
        ("GET http://carts.default.svc:80/x", "frontend", {"carts"}),  # URL with a DNS suffix
        ("added item to carts", "frontend", set()),  # ambiguous ^[a-z]+$ name as a plain word
        ("rpc error hipstershop.CartService/GetCart", "frontend", {"cartservice"}),  # gRPC package
        ("calling ts-order-service for order 12", "frontend", {"ts-order-service"}),  # plain word
        ("frontend:8080 is up", "frontend", set()),  # a self-mention is ignored
        ("checkout-v2:8080", "frontend", set()),  # another name, not checkout
        ("upstream CHECKOUT:8080 responded", "frontend", {"checkout"}),
    ],
)
def test_mention_forms_and_the_ambiguity_rule(text: str, speaker: str, expected: set[str]) -> None:
    assert M.mentions(text, speaker) == expected


def test_grpc_package_drops_a_trailing_service() -> None:
    assert Matcher.build(["cart"]).mentions("oteldemo.CartService unavailable", "frontend") == {"cart"}


def test_log_edges_count_lines_and_need_known_nodes() -> None:
    counts = [
        ("frontend", "upstream checkout:8080 responded in 3ms", 2),
        ("frontend", "upstream checkout:8080 responded in 4ms", 1),
        ("frontend", "GET http://catalog:3550/items", 2),  # 2 < min_mentions
        ("load-generator", "GET http://frontend:80/", 50),  # speaker is no node: no edge, no node
    ]
    nodes = frozenset({"catalog", "checkout", "frontend"})
    assert log_edges(counts, nodes, Matcher.build(nodes), 3) == [("frontend", "checkout")]


def test_topology_edges_from_deploy_and_config_events() -> None:
    nodes = frozenset({"catalog", "recommend", "cart"})
    events = [
        ("recommend", "config", '{"key":"CATALOG_ADDR","value":"catalog:3550"}'),
        ("cart-1", "deploy", '{"from":"cart:2.3.1","to":"cart:2.4.0"}'),  # entity is no node
        ("cart", "deploy", '{"image":"registry.local/cart","to":"cart:2.4.0"}'),  # ":2" is no port
        ("recommend", "k8s_event", '{"reason":"Pulled","target":"catalog:3550"}'),  # not a hint kind
        ("recommend", "config", "not json"),
    ]
    assert topology_edges(events, nodes, Matcher.build(nodes)) == [("recommend", "catalog")]


# --- #36: the substring prefilter in Matcher.mentions never changes a result ---------------------
TT = Matcher.build(["kafka", "ts-order-service", "ts-travel-service", "ts-travel2-service"])


def _every_regex(matcher: Matcher, text: str, speaker: str | None = None) -> set[str]:
    """The pre-#36 reference: every form of every name, no prefilter."""
    found = matcher.grpc_names(text)
    for name, forms in matcher.patterns.items():
        if name not in found and any(f.search(text) for f in forms):
            found.add(name)
    found.discard(speaker or "")
    return found


def test_a_tt_shaped_java_line_still_mentions_its_callee() -> None:
    # RE2-TT: a Spring Boot prefix (timestamp, thread) makes every line a distinct body (#36).
    line = (
        "2024-01-22 14:40:08.861  INFO 1 --- [io-18767-exec-9] t.service.TravelServiceImpl      : "
        "[Query] calling http://ts-travel-service:12346/api/v1/travelservice/trips"
    )
    assert TT.mentions(line, "ts-order-service") == {"ts-travel-service"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("dial ts-order-serv\u0131ce:8080", {"ts-order-service"}),  # dotless i
        ("dial ts-order-serv\u0130ce:8080", {"ts-order-service"}),  # dotted capital I
        ("dial t\u017f-order-service:8080", {"ts-order-service"}),  # long s
        ("broker \u212aafka:9092 down", {"kafka"}),  # Kelvin sign
    ],
)
def test_the_four_non_ascii_case_folds_still_match(text: str, expected: set[str]) -> None:
    assert _every_regex(TT, text, "x") == expected  # what re.IGNORECASE itself decides
    assert TT.mentions(text, "x") == expected


_PIECES = st.sampled_from(
    ["ts-", "order", "travel", "travel2", "-service", "kafka", "http://", ":8080", ".svc", "-db",
     "hipster.KafkaService", "TS-ORDER-SERVICE", "\u0130", "\u0131", "\u017f", "\u212a", " ", "/", "."]
)  # fmt: skip
_CHARS = st.text(alphabet="aeikorstvKS2-.:/_ \u0130\u0131\u017f\u212a\u00df", max_size=6)


@settings(max_examples=400, deadline=None)
@given(
    st.lists(st.one_of(_PIECES, _CHARS), max_size=12), st.sampled_from([None, "kafka", "ts-order-service"])
)
def test_prefiltered_mentions_equal_running_every_regex(parts: list[str], speaker: str | None) -> None:
    text = "".join(parts)
    assert TT.mentions(text, speaker) == _every_regex(TT, text, speaker)
