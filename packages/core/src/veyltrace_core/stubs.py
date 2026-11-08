"""Bootstrap stub engines: schema-valid placeholder outputs for every engine and phase.

Why this exists: the pipeline, the e2e `diagnose` test and the determinism gate need every engine in
`veyltrace.engines` to resolve and to write its contracts before the real engines exist (M0 lead
decision 2026-11-06, bootstrap; critic blocker 2). Each package's R-02 `api.run` calls
`run_stub(ctx, "<engine>")`; the owning lane replaces that call in O-00 / R-00 / X-00.

What a stub writes (02 §3, 03 catalog): every contract its pipeline sub-step produces (`steps.STEPS`),
as the smallest object the schema accepts that is still consistent with the stub run so far: empty
tables with the exact Arrow schema, an empty slate, an INCONCLUSIVE verdict with no root and the
uncalibrated calibration, a template card and a receipt over the real run manifest. Outputs are pure
functions of the run context and upstream files, so two stub runs are byte-identical.

Stubs never import `veyltrace_core.testing` or `veyltrace_core.synth` (engines may not either:
isolation rule), and they never read ground truth.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

import pyarrow as pa
from pydantic import BaseModel

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.adapters import TELEMETRY_CONTRACTS, CanonicalCase, adapter_for, find_adapter
from veyltrace_core.config import data_root
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import self_hash, sha256_file, sha256_json, verify_chain
from veyltrace_core.steps import STEPS, Step, step, step_for

__all__ = [
    "PLACEHOLDER_DATASET",
    "STUB_NOTE",
    "STUB_STEPS",
    "UNCALIBRATED_FAMILY",
    "run_stub",
    "stub_outputs",
]

#: EngineResult.notes entry of every stub result, so bench and reviewers can tell stub runs apart.
STUB_NOTE: Final = "stub: R-02 bootstrap placeholder outputs"
#: The only dataset the stub Infralume fakes when no adapter is installed (the documented
#: bootstrap case); any other dataset without an adapter is a ConfigError, so a run on re2-ob never
#: "succeeds" on invented data.
PLACEHOLDER_DATASET: Final = "synth"

# --- Placeholder case layout (a priori) -------------------------------------------------------
# The Infralume stub has no raw data, but core's alert step needs a hint inside the data span and
# non-empty baseline and incident windows (02 §5.1; 03 §2.6). These values mirror the synth case
# layout (synth_spec: T0 = 2026-01-01T00:00:00Z, 32 min of data, oracle hint at T0 + 22 min), so the
# default windows [-1200 s, -120 s) and [-120 s, +480 s) around the hint fit inside the span.
_NS_PER_S: Final = 1_000_000_000
STUB_T0_NS: Final = 1_767_225_600 * _NS_PER_S
STUB_SPAN_S: Final = 1920
STUB_HINT_OFFSET_S: Final = 1320
#: case_manifest.adapter for stub ingests; "stub" is deliberately not a registered adapter name.
STUB_ADAPTER: Final = {"name": "stub", "version": "0"}
#: case_manifest.scrub for stub ingests: nothing was read, so nothing was dropped.
STUB_SCRUB: Final = {"rules_version": "stub-0", "dropped_attributes": 0, "dropped_rows": 0}
STUB_SYSTEM: Final = "other"

# --- Defaults copied from the engine specs, used only when the engine's config lacks the key ----
#: Causatrix slate size K (07 §3.8: slate.k, default 5).
DEFAULT_SLATE_K: Final = 5
#: Causatrix RRF constant (07 §3.8: rrf.k, default 60).
DEFAULT_RRF_K: Final = 60
#: Causentra conformal miscoverage level (09 §9: alpha 0.10, from 02 §6.9).
DEFAULT_ALPHA: Final = 0.10
#: Relentra mode when config has none (08 §4: brief is the default).
DEFAULT_RELENTRA_MODE: Final = "brief"

#: verdict.calibration.family when no calibration file applies (03 §10; 09 §3.7).
UNCALIBRATED_FAMILY: Final = "uncalibrated"

_RECEIPT_TYPE: Final = "https://in-toto.io/Statement/v1"
_RECEIPT_PREDICATE_TYPE: Final = "https://veyltrace.dev/rca-verdict/v1"
_CARD_MD: Final = "card.md"

_Writer = Callable[[RunContext], list[tuple[str, str]]]


def _version(name: str) -> str:
    return CONTRACTS[name].version


def _cfg_get(ctx: RunContext, dotted: str, default: Any) -> Any:
    """Read a dotted key from the engine's own config section, or `default` if absent.

    The stubs run against whatever keys the owning lane has added so far, so a missing key is
    normal here (real engines declare every key in their YAML).
    """
    return ctx.config.get_path(dotted, default)


def _read[M: BaseModel](ctx: RunContext, name: str, model: type[M]) -> M:
    """Read a JSON contract through the context and check it is the expected model."""
    value = ctx.read(name)
    if not isinstance(value, model):
        msg = f"stub expected {name!r} to read as {model.__name__}, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _empty_tables(ctx: RunContext, names: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(name, ctx.write(name, io.empty_table(name))) for name in names]


def _step_outputs(step_name: str) -> tuple[str, ...]:
    return step(step_name).outputs


# --- Per-step writers -------------------------------------------------------------------------
def _hint(ctx: RunContext, hint: int | None, source: str) -> tuple[int | None, str]:
    """Infralume blanks the hint under the detected protocol (01 §3.3)."""
    if str(ctx.config.core["alert"]["protocol"]) == "detected":
        return None, "none"
    return hint, source


def _placeholder_case(ctx: RunContext) -> list[tuple[str, str]]:
    """No adapter for the dataset yet: case_manifest plus four zero-row tables (no sources)."""
    protocol = str(ctx.config.core["alert"]["protocol"])
    # Live hints are trigger times; every other protocol's stub hint is an oracle hint.
    hint, hint_source = _hint(
        ctx, STUB_T0_NS + STUB_HINT_OFFSET_S * _NS_PER_S, "live" if protocol == "live" else "oracle"
    )
    manifest: dict[str, Any] = {
        "schema_version": _version("case_manifest"),
        "case_id": ctx.case_id,
        "dataset": ctx.dataset,
        "system": STUB_SYSTEM,
        "t_alert_hint_ns": hint,
        "hint_source": hint_source,
        "data_start_ns": STUB_T0_NS,
        "data_end_ns": STUB_T0_NS + STUB_SPAN_S * _NS_PER_S,
        "sources": {"metrics": False, "logs": False, "traces": False, "events": False},
        "services": [],
        "inputs": [],
        "adapter": dict(STUB_ADAPTER),
        "scrub": dict(STUB_SCRUB),
    }
    out = [("case_manifest", ctx.write("case_manifest", manifest))]
    telemetry = tuple(n for n in _step_outputs("infralume") if n.startswith("telemetry."))
    return out + _empty_tables(ctx, telemetry)


def _full_table(contract: str, table: pa.Table) -> pa.Table:
    """Pad an adapter's column subset to the full contract: absent nullable columns become nulls.

    Adapters may omit optional columns (TelemetryTables.from_tables); the written file always has
    the contract schema. A missing required column is a contract error, never a silent default.
    """
    schema: Any = io.arrow_schema(contract)  # pyarrow-stubs leaves Field's parameters Unknown
    present = set(table.column_names)
    columns: list[Any] = []
    for i in range(len(schema.names)):
        field = schema.field(i)
        if field.name in present:
            columns.append(table.column(field.name))
        elif field.nullable:
            columns.append(pa.nulls(table.num_rows, type=field.type))
        else:
            raise ContractValidationError(contract, f"adapter table lacks required column {field.name!r}")
    return io.conform_table(contract, pa.Table.from_arrays(columns, names=list(schema.names)))


def _column_bounds(table: pa.Table, low: str, high: str) -> tuple[int, int] | None:
    """(min of `low`, max of `high`); both columns are non-null int64 in their contracts."""
    if table.num_rows == 0:
        return None
    lows: list[int] = table.column(low).to_pylist()  # pyright: ignore[reportAssignmentType] - non-null int64
    highs: list[int] = table.column(high).to_pylist()  # pyright: ignore[reportAssignmentType] - non-null int64
    return min(lows), max(highs)


def _span(case: CanonicalCase) -> tuple[int, int]:
    """data_start/end over every source, span start/end included (01 §3.8).

    A case with no rows at all keeps the placeholder span, so the run still reaches the alert step,
    which then accepts or rejects the hint on its own rules.
    """
    bounds = [
        _column_bounds(case.tables.metrics, "t_ns", "t_ns"),
        _column_bounds(case.tables.logs, "t_ns", "t_ns"),
        _column_bounds(case.tables.spans, "start_ns", "end_ns"),
        _column_bounds(case.tables.events, "t_ns", "t_ns"),
    ]
    found = [b for b in bounds if b is not None]
    if not found:
        return STUB_T0_NS, STUB_T0_NS + STUB_SPAN_S * _NS_PER_S
    return min(b[0] for b in found), max(b[1] for b in found)


def _adapter_case(ctx: RunContext, case: CanonicalCase) -> list[tuple[str, str]]:
    """case_manifest and telemetry from an adapter's CanonicalCase, without Infralume's cache,
    source drops, overlays or scrubbing (those arrive with O-00)."""
    services: set[str] = set()
    for table in (case.tables.metrics, case.tables.logs, case.tables.spans):
        services.update(str(s) for s in table.column("service").to_pylist())
    data_start, data_end = _span(case)
    hint, hint_source = _hint(ctx, case.t_alert_hint_ns, case.hint_source)
    rules_version, dropped_attributes, dropped_rows = case.scrub
    manifest: dict[str, Any] = {
        "schema_version": _version("case_manifest"),
        "case_id": ctx.case_id,
        "dataset": ctx.dataset,
        "system": case.system,
        "t_alert_hint_ns": hint,
        "hint_source": hint_source,
        "data_start_ns": data_start,
        "data_end_ns": data_end,
        "sources": dict(sorted(case.sources_present.items())),
        "services": sorted(services),  # str order is code-point order, which is UTF-8 byte order
        "inputs": [{"name": n, "sha256": d, "bytes": b} for n, d, b in case.inputs],
        "adapter": {"name": case.adapter_name, "version": case.adapter_version},
        "scrub": {
            "rules_version": rules_version,
            "dropped_attributes": dropped_attributes,
            "dropped_rows": dropped_rows,
        },
    }
    out = [("case_manifest", ctx.write("case_manifest", manifest))]
    for attr, table in case.tables.items():
        contract = TELEMETRY_CONTRACTS[attr]
        out.append((contract, ctx.write(contract, _full_table(contract, table))))
    return out


def _infralume(ctx: RunContext) -> list[tuple[str, str]]:
    """Materialise the case through its dataset adapter (core_api_spec §8: step 0 always calls
    adapter_for), or write a placeholder case while no adapter for the dataset is installed."""
    adapter = find_adapter(ctx.dataset)
    if adapter is None:
        if ctx.dataset != PLACEHOLDER_DATASET:
            adapter_for(ctx.dataset)  # raises ConfigError: no adapter for a real dataset (exit 4)
        return _placeholder_case(ctx)
    ref = adapter.resolve(ctx.dataset, ctx.case_id, data_root())
    if ref.case_id != ctx.case_id:
        msg = f"adapter {adapter.name!r} resolved {ctx.case_id!r} to case {ref.case_id!r}"
        raise ContractValidationError("case_manifest", msg)
    return _adapter_case(ctx, adapter.convert(ref, ctx.config))


def _signalyth(ctx: RunContext) -> list[tuple[str, str]]:
    return _empty_tables(ctx, _step_outputs("signalyth"))


def _anomara(ctx: RunContext) -> list[tuple[str, str]]:
    """No anomalies; onsets fall back to t_alert with one all-null entry per manifest service."""
    alert = _read(ctx, "alert", models.Alert)
    manifest = _read(ctx, "case_manifest", models.CaseManifest)
    detected = alert.protocol == "detected"
    onsets = {
        "schema_version": _version("onsets"),
        "t_onset_ns": alert.t_alert_ns,
        "method": "t_alert_fallback",
        # 03 §6.2: alert.t_alert_ns - alert.shift_ns iff the protocol is detected, else null.
        "slo_breach_ns": alert.t_alert_ns - alert.shift_ns if detected else None,
        "entry_services": sorted(alert.detector.entry_services) if alert.detector is not None else [],
        "per_service": [
            {
                "service": service,
                "external_onset_ns": None,
                "external_onset_source": None,
                "internal_onset_ns": None,
                "internal_onset_source": None,
                "silent": False,
            }
            for service in sorted(manifest.services)
        ],
    }
    out = _empty_tables(ctx, ("anomalies",))
    out.append(("onsets", ctx.write("onsets", onsets)))
    return out


def _causync(ctx: RunContext) -> list[tuple[str, str]]:
    """No offsets estimated, no changes; the reference clock follows the 03 §5.1 rule."""
    manifest = _read(ctx, "case_manifest", models.CaseManifest)
    alignment: dict[str, Any] = {
        "schema_version": _version("alignment"),
        # 03 §5.1: traces if present, else metrics (also when neither is present).
        "reference": "traces" if manifest.sources.traces else "metrics",
        "offsets": [],
        "tolerance_ns": 0,
    }
    out = [("alignment", ctx.write("alignment", alignment))]
    return out + _empty_tables(ctx, ("changes",))


def _causalith(ctx: RunContext) -> list[tuple[str, str]]:
    return _empty_tables(ctx, _step_outputs("causalith"))


def _faultloom(ctx: RunContext) -> list[tuple[str, str]]:
    # Both phases (main and claim_pass) write evidence; with no inputs it has no atoms.
    return _empty_tables(ctx, ("evidence",))


def _causatrix(ctx: RunContext) -> list[tuple[str, str]]:
    """An empty slate: no ranker voted, so there are no candidates and no scores."""
    slate: dict[str, Any] = {
        "schema_version": _version("slate"),
        "case_id": ctx.case_id,
        "k": int(_cfg_get(ctx, "slate.k", DEFAULT_SLATE_K)),
        "rankers_active": [],
        "fusion": {"method": "rrf", "k": int(_cfg_get(ctx, "rrf.k", DEFAULT_RRF_K)), "weights": {}},
        "candidates": [],
        "all_scores": [],
    }
    return [("slate", ctx.write("slate", slate))]


def _relentra(ctx: RunContext) -> list[tuple[str, str]]:
    """Proposals with status skipped (AI on, model not called) and an empty agent trace."""
    proposals: dict[str, Any] = {
        "schema_version": _version("proposals"),
        "case_id": ctx.case_id,
        "status": "skipped",
        "mode": str(_cfg_get(ctx, "mode", DEFAULT_RELENTRA_MODE)),
        "model": None,  # 03 §9.1: null for status skipped
        "budget_used": {"turns": 0, "tokens_in": 0, "tokens_out": 0, "wall_ms": 0.0},
        "proposals": [],
        "asks": [],
    }
    out = [("proposals", ctx.write("proposals", proposals))]
    writer = io.JsonlWriter("agent_trace", ctx.run_dir)
    out.append(("agent_trace", writer.close()))
    return out


def _uncalibrated() -> dict[str, str]:
    # 03 §10: family "uncalibrated" with sha256 = sha256_json({"family": "uncalibrated"}).
    return {"family": UNCALIBRATED_FAMILY, "sha256": sha256_json({"family": UNCALIBRATED_FAMILY})}


def _causentra(ctx: RunContext) -> list[tuple[str, str]]:
    """INCONCLUSIVE with no leader: empty pool, empty set, level none, uncalibrated."""
    verdict: dict[str, Any] = {
        "schema_version": _version("verdict"),
        "case_id": ctx.case_id,
        "run_id": ctx.run_id,
        "status": "INCONCLUSIVE",
        "root": None,
        "candidate_set": [],
        "ranked": [],
        # 09 §3.9: margin 0.0 with no leader; q_hat null means +inf (no calibration).
        "confidence": {
            "level": "none",
            "margin": 0.0,
            "alpha": float(_cfg_get(ctx, "alpha", DEFAULT_ALPHA)),
            "q_hat": None,
            "set_size": 0,
        },
        "asks": [],
        "ranks_rcaeval": [],
        "proposals_accepted": [],
        "proposals_rejected": [],
        "calibration": _uncalibrated(),
        # 09 §2.2: sha256 of the canonical effective causentra section.
        "params_sha256": sha256_json(dict(ctx.config)),
    }
    verdict["verdict_hash"] = self_hash("verdict", verdict)
    return [("verdict", ctx.write("verdict", verdict))]


def _card_markdown(card: Mapping[str, Any]) -> str:
    """The template card.md (10 §3.7 layout, minimal): title, status line, empty set, hashes."""
    lines = [
        f"# {card['title']}",
        "",
        f"Status: {card['status']} (confidence: {card['confidence']['level']})",
        "",
        "Candidate set: empty",
        "",
        "prose: template",
        "",
        f"verdict_hash: {card['verdict_hash']}",
        f"card_hash: {card['card_hash']}",
        "",
    ]
    return "\n".join(lines)


def _causivra_card(ctx: RunContext) -> list[tuple[str, str]]:
    """A template card that copies the verdict's status, root, confidence and candidate set."""
    verdict = _read(ctx, "verdict", models.Verdict)
    v = verdict.model_dump(mode="json", by_alias=True)
    card: dict[str, Any] = {
        "schema_version": _version("card"),
        "case_id": ctx.case_id,
        "verdict_hash": verdict.verdict_hash,
        "title": f"{v['status']}: no root cause (stub)",
        "status": v["status"],
        "root": v["root"],
        "confidence": v["confidence"],
        "candidate_set": [{"service": c["service"], "component": c["component"]} for c in v["candidate_set"]],
        "summary": [],
        "timeline": [],
        "path": [],
        "evidence_table": [],
        "why_not": [],
        "asks": [],
        "next_steps": [],
        "narrator": {"path": "template", "model": None, "attempts": 0, "checker_failures": 0},
    }
    card["card_hash"] = self_hash("card", card)
    out = [("card", ctx.write("card", card))]
    out.append((_CARD_MD, ctx.write_text(_CARD_MD, _card_markdown(card))))
    return out


def _causivra_receipt(ctx: RunContext) -> list[tuple[str, str]]:
    """The in-toto receipt over the real run manifest, verdict file and card (03 §12.3)."""
    run_manifest = _read(ctx, "run_manifest", models.RunManifest)
    verdict = _read(ctx, "verdict", models.Verdict)
    card = _read(ctx, "card", models.Card)
    head: str | None = None
    if ctx.exists("agent_trace"):
        head = verify_chain(io.read_lines("agent_trace", ctx.run_dir, models.AgentTraceLine))
    receipt = {
        "_type": _RECEIPT_TYPE,
        "subject": [
            {
                "name": CONTRACTS["verdict"].path,
                "digest": {"sha256": sha256_file(io.path_of("verdict", ctx.run_dir))},
            }
        ],
        "predicateType": _RECEIPT_PREDICATE_TYPE,
        "predicate": {
            "run_manifest": run_manifest.model_dump(mode="json", by_alias=True),
            "verdict_hash": verdict.verdict_hash,
            "card_hash": card.card_hash,
            "agent_trace_head": head,
        },
    }
    return [("receipt", ctx.write("receipt", receipt))]


# Keyed by sub-step name (the step order is the only engine-specific knowledge core has; this is
# not an engine registry: engines are still resolved through entry points).
_WRITERS: Final[Mapping[str, _Writer]] = {
    "infralume": _infralume,
    "signalyth": _signalyth,
    "anomara": _anomara,
    "causync": _causync,
    "causalith": _causalith,
    "faultloom": _faultloom,
    "causatrix": _causatrix,
    "relentra": _relentra,
    "faultloom.claim_pass": _faultloom,
    "causentra": _causentra,
    "causivra.card": _causivra_card,
    "causivra.receipt": _causivra_receipt,
}

#: Sub-steps a stub can run: every step of steps.STEPS that an engine (not core) runs.
STUB_STEPS: Final[tuple[str, ...]] = tuple(s.name for s in STEPS if s.engine is not None)


def _engine_step(engine: str, phase: str) -> Step:
    found = step_for(engine, phase)
    if found is None:
        msg = f"no pipeline step runs engine {engine!r} in phase {phase!r}"
        raise ValueError(msg)
    return found


def stub_outputs(engine: str, phase: str = "main") -> tuple[str, ...]:
    """Run-dir names a stub writes for (engine, phase): the step's contracts, plus card.md."""
    sub = _engine_step(engine, phase)
    extra = (_CARD_MD,) if sub.name == "causivra.card" else ()
    return tuple(sorted((*sub.outputs, *extra)))


def run_stub(ctx: RunContext, engine: str) -> EngineResult:
    """Write the placeholder outputs of `engine` for `ctx.phase` and report them.

    `engine` is passed explicitly (not taken from ctx.engine) so a mis-wired entry point fails
    loudly instead of writing another engine's contracts. The result lists every file written
    (contract names, plus "card.md" for the card step), sorted, with status "ok".
    """
    if ctx.engine != engine:
        msg = f"stub for {engine!r} called with a context for engine {ctx.engine!r}"
        raise ValueError(msg)
    sub = _engine_step(engine, ctx.phase)
    outputs = tuple(sorted(_WRITERS[sub.name](ctx)))
    return EngineResult(engine=engine, status="ok", outputs=outputs, notes=(STUB_NOTE,))
