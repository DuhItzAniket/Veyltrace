"""Drain3 templates (02 §3.5 steps 3 to 5): order rules, ids, merging, collisions, fallback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_core import duck
from veyltrace_core.config import resolve_config
from veyltrace_core.errors import ContractValidationError
from veyltrace_signalyth import templates
from veyltrace_signalyth.loglines import DrainRules, LogRules, load_lines
from veyltrace_signalyth.templates import Message, distinct_messages, mine_templates, template_id

CONFIG = resolve_config({}, ai_mode="off").engine("signalyth")
RULES = LogRules.from_config(CONFIG)
DRAIN = RULES.drain
MESSAGES: list[Message] = [
    ("cart", "cart <NUM> holds <NUM> items", 40),
    ("db", "connect to replica-a failed", 9),
    ("db", "connect to replica-b failed", 7),
    ("db", "connect to replica-c failed", 7),
    ("db", "vacuum finished in <DUR>", 3),
    ("pay", "charged order <NUM> amount <NUM> cents", 12),
    ("pay", "tokenized card for order <NUM>", 12),
]


def _by_text(rows: list[templates.TemplateRow]) -> dict[tuple[str, str], tuple[str, str]]:
    return {(service, masked): (tid, template) for service, masked, tid, template in rows}


def test_template_id_formula() -> None:
    canonical = json.dumps(["db", "connect to <*> failed"], ensure_ascii=False, separators=(",", ":"))
    expected = "T" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    assert template_id("db", "connect to <*> failed") == expected
    assert template_id("pay", "connect to <*> failed") != expected  # the service is part of the id


def test_messages_take_the_final_text_of_their_cluster() -> None:
    rows, fallback = mine_templates(MESSAGES, DRAIN)
    assert fallback == []
    assert rows == sorted(rows)
    by = _by_text(rows)
    merged = {by[("db", f"connect to replica-{x} failed")] for x in "abc"}
    # the first message joined the cluster before it had a wildcard: it still gets the final text
    assert merged == {(template_id("db", "connect to <*> failed"), "connect to <*> failed")}
    assert by[("db", "vacuum finished in <DUR>")][1] == "vacuum finished in <DUR>"
    assert by[("pay", "tokenized card for order <NUM>")][1] == "tokenized card for order <NUM>"


def test_one_fresh_miner_per_service() -> None:
    alone, _ = mine_templates([m for m in MESSAGES if m[0] == "db"], DRAIN)
    together, _ = mine_templates(MESSAGES, DRAIN)
    assert [r for r in together if r[0] == "db"] == alone
    twin = [("a", "ping <NUM> ok", 1), ("b", "ping <NUM> ok", 1)]
    ids = {tid for _, _, tid, _ in mine_templates(twin, DRAIN)[0]}
    assert len(ids) == 2


def test_drain_settings_come_from_config() -> None:
    strict = DrainRules(sim_th=1.0, depth=DRAIN.depth, max_children=DRAIN.max_children)
    rows, _ = mine_templates(MESSAGES, strict)
    assert {template for service, _, _, template in rows if service == "db"} == {
        m[1] for m in MESSAGES if m[0] == "db"
    }


@given(st.permutations(MESSAGES))
def test_templates_do_not_depend_on_input_order(shuffled: list[Message]) -> None:
    assert mine_templates(shuffled, DRAIN) == mine_templates(MESSAGES, DRAIN)


def test_count_then_text_is_the_feeding_order(monkeypatch: pytest.MonkeyPatch) -> None:
    fed: list[list[str]] = []
    monkeypatch.setattr(templates, "_mine", lambda texts, rules: fed.append(list(texts)) or list(texts))
    mine_templates(reversed(MESSAGES), DRAIN)
    assert fed[1] == [
        "connect to replica-a failed",  # 9 lines
        "connect to replica-b failed",  # 7 lines, text asc
        "connect to replica-c failed",
        "vacuum finished in <DUR>",
    ]
    assert [texts[0][:4] for texts in fed] == ["cart", "conn", "char"]  # services A→Z


def test_clusters_with_identical_text_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(templates, "_mine", lambda texts, rules: ["same <*>"] * len(texts))
    rows, _ = mine_templates([("db", "same a", 2), ("db", "same b", 1)], DRAIN)
    assert {(tid, template) for _, _, tid, template in rows} == {(template_id("db", "same <*>"), "same <*>")}


def test_id_collision_fails_the_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(templates, "template_id", lambda service, template: "T00000000")
    with pytest.raises(ContractValidationError, match="T00000000 collides"):
        mine_templates(MESSAGES, DRAIN)


def test_drain_failure_falls_back_to_masked_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    real = templates._mine  # pyright: ignore[reportPrivateUsage]

    def flaky(texts: list[str], rules: DrainRules) -> list[str]:
        if texts[0].startswith("connect"):
            raise RuntimeError("boom")
        return real(texts, rules)

    monkeypatch.setattr(templates, "_mine", flaky)
    rows, fallback = mine_templates(MESSAGES, DRAIN)
    assert fallback == ["db"]
    assert all(masked == template for service, masked, _, template in rows if service == "db")
    assert _by_text(rows)[("pay", "tokenized card for order <NUM>")][1] == "tokenized card for order <NUM>"


def test_distinct_messages_count_lines_over_the_whole_range(tmp_path: Path) -> None:
    bodies = ["order 1 ok", "order 2 ok", "", "boom", "order 3 ok"]
    logs = pa.table(
        {
            "t_ns": pa.array(range(len(bodies)), pa.int64()),
            "service": pa.array(["b", "b", "b", "a", "a"]),
            "severity": pa.array(["INFO"] * len(bodies)),
            "body": pa.array(bodies),
        }
    )
    with duck.connect(CONFIG, tmp_path) as con:
        load_lines(con, logs, RULES)
        found = sorted(distinct_messages(con))
    assert found == [("a", "boom", 1), ("a", "order <NUM> ok", 1), ("b", "order <NUM> ok", 2)]
