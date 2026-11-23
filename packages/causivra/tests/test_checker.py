"""The claim checker (10 §3.4): the seeded bad sentences of 10 §7, accept examples per rule, and
template safety (every template sentence passes the checker; 10 §7 "Template safety")."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from veyltrace_causivra import assemble
from veyltrace_causivra.checker import CheckerSettings, Finding, check_sentence, checker_settings
from veyltrace_causivra.placeholders import FillContext, RunnerUp, TableAtom
from veyltrace_causivra.prose import template_sentences
from veyltrace_contracts import models
from veyltrace_core.config import resolve_config
from veyltrace_core.errors import ArtifactMissing, ConfigError
from veyltrace_core.testing import SYNTH_CASES, fixture_run_dir, make_context, repo_root

ATOM = "Ea4217049f6"
NODES = frozenset({"payment", "cart", "checkout", "frontend"})


def _section() -> dict[str, Any]:
    resolved = resolve_config({}, config_dir=repo_root() / "config", ai_mode="off")
    return dict(resolved.engine("causivra"))


SETTINGS = checker_settings(_section())


def _ctx(status: str = "LIKELY", root: str | None = "payment") -> FillContext:
    return FillContext(
        status=status,
        root_service=root,
        root_fields={}
        if root is None
        else {"component": root, "fault_class": "cpu", "indicator": "cpu", "mode": "resource"},
        runner_up=RunnerUp("cart", "cpu", "latency"),
        conf_level="medium",
        conf_set_size=2,
        conf_margin=0.27,
        table={ATOM: TableAtom(ATOM, "payment cpu anomaly (incident)", 9.42, "z", "payment", "incident")},
        nodes=NODES,
        onset_ns=None,
        sig_digits=3,
    )


def _check(
    text: str, cites: list[str] | None = None, ctx: FillContext | None = None, **kw: Any
) -> Finding | None:
    return check_sentence(text, [ATOM] if cites is None else cites, ctx or _ctx(), NODES, SETTINGS, **kw)


@pytest.mark.parametrize(
    ("text", "cites", "status", "rule", "token"),
    [
        ("Latency rose to 512 ms.", None, "LIKELY", "C4", "512"),
        ("CPU doubled on {ROOT}.", None, "LIKELY", "C5", "doubled"),
        ("The fault is in paymentservice-v2.", None, "LIKELY", "C6", "paymentservice-v2"),
        ("frontend errors grew.", None, "LIKELY", "C6", "frontend"),
        ("{ROOT} shows {E" + ATOM[1:] + ".label}.", [], "LIKELY", "C3", ""),
        ("{ROOT} leads.", ["Effffffffff"], "LIKELY", "C3", "Effffffffff"),
        ("{ROOT} is named.", None, "NO_FAULT", "C2", "ROOT"),
        ("The root cause is confirmed.", None, "INCONCLUSIVE", "C7", "the root cause is"),
        ("{ROOT} leads. It passed every trial.", None, "LIKELY", "C8", "."),
        ("Its value was {E0000000000.value}.", None, "LIKELY", "C2", "E0000000000.value"),
    ],
)
def test_seeded_bad_sentences_are_rejected_with_their_rule(
    text: str, cites: list[str] | None, status: str, rule: str, token: str
) -> None:
    root = None if status == "NO_FAULT" else "payment"
    finding = _check(text, cites, _ctx(status, root))
    assert finding is not None and (finding.rule, finding.token) == (rule, token), finding


@pytest.mark.parametrize(
    "text",
    [
        "{ROOT} shows {E" + ATOM[1:] + ".label} at {E" + ATOM[1:] + ".value} {E" + ATOM[1:] + ".unit}.",
        "Its p99 latency and 5xx errors rose before {SVC:checkout} on HTTP/2.",
        "The runner-up {RUNNER_UP} failed T3 over gRPC.",
        "{ROOT} is the most likely root cause; the candidate set has {CONF.set_size}.",
    ],
)
def test_grounded_sentences_pass(text: str) -> None:
    assert _check(text) is None


def test_certainty_words_pass_only_when_confirmed() -> None:
    assert _check("The root cause is {ROOT}.", ctx=_ctx("CONFIRMED")) is None
    assert _check("It is definitely {ROOT}.", ctx=_ctx("LIKELY")) == Finding(
        "C7", "definitely", "certainty word under LIKELY"
    )


def test_shape_limits() -> None:
    assert _check("{ROOT} leads") == Finding("C8", "", "does not end in '.'")
    too_many_words = _check("{ROOT} " + "leads " * SETTINGS.max_words + "now.")
    too_long = _check("{ROOT} " + "x" * SETTINGS.max_chars + ".")
    assert too_many_words is not None and too_many_words.rule == "C8"
    assert too_long is not None and too_long.rule == "C8"


def test_percent_and_camel_case_identifiers() -> None:
    assert _check("Errors rose by a large %.") == Finding("C5", "%", "a percent sign outside placeholders")
    assert _check("The paymentService pod restarted.") == Finding(
        "C6", "paymentService", "identifier-shaped token"
    )


def test_templates_may_skip_cites_but_llm_sentences_may_not() -> None:
    text = "No anomaly above threshold was found at the entry service or inside any service."
    assert _check(text, []) == Finding("C3", "", "an LLM sentence must cite at least one atom")
    assert _check(text, [], require_cites=False) is None


def test_the_repo_config_is_valid_and_bad_config_is_refused() -> None:
    assert isinstance(SETTINGS, CheckerSettings) and "HTTP/2" in SETTINGS.allowed_digit_tokens
    section = _section()
    section["checker"] = {**section["checker"], "max_words": 0}
    with pytest.raises(ConfigError):
        checker_settings(section)


@pytest.mark.parametrize("case", SYNTH_CASES)
def test_every_template_sentence_passes_the_checker(case: str, tmp_path: Path) -> None:
    """10 §7 "Template safety", on the synth verdict fixtures, with the card step's own inputs."""
    try:
        run_dir = fixture_run_dir(case, tmp_path, through="causentra")
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")
    ctx = make_context("causivra", run_dir, phase="card", ai_mode="off", overrides={})
    settings = assemble.settings_from(ctx.config, ctx.config.section("causentra"))
    verdict = ctx.read_model("verdict", models.Verdict)
    evidence = ctx.read_table("evidence").to_pylist()
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    table = assemble.evidence_table(verdict, evidence, settings)
    atoms = assemble.table_atoms(table, evidence)
    graph = ctx.read_table("graph.nodes", columns=["node"]).to_pylist() if ctx.exists("graph.nodes") else []
    nodes = {str(r["node"]) for r in graph} | set(manifest.services)
    fill_ctx = assemble.fill_context(verdict, atoms, nodes, None, settings.sig_digits)
    kinds = {str(r["atom_id"]): str(r["kind"]) for r in evidence if str(r["atom_id"]) in atoms}
    entities = frozenset(nodes) | {str(r["component"]) for r in evidence if r.get("component")}
    for text, cites in template_sentences(verdict, fill_ctx, kinds, settings.ask_phrases):
        assert check_sentence(text, cites, fill_ctx, entities, SETTINGS, require_cites=False) is None, text
