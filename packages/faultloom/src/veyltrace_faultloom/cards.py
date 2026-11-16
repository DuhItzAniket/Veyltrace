"""`evidence_cards` (06 §3.7): the deterministic compact view Relentra's `brief` mode puts in its prompt.

Why: EviRCA-style evidence cards let a small model propose from a few relevant atoms at a fraction of
the tokens of a tool-using agent, and the evidence shown matters more than prompt wording (06 §3.7).
The deck is a pure, read-only function of the run's artefacts: same inputs, same bytes, same hash.
Atoms are cited by id so a proposal's `cites` can point at them. "Against" facts are shown on every
card to counter anchoring. Token counts are byte-based *estimates*; no tokenizer is imported.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from veyltrace_contracts import models
from veyltrace_core.context import RunContext
from veyltrace_core.hashing import sha256_json
from veyltrace_faultloom.predicates import LIBRARY
from veyltrace_faultloom.validation import read_domain

__all__ = ["PRIORITY", "CardDeck", "deck_dict", "evidence_cards"]

#: (kind, args filter) in the 06 §3.7 priority order; the best atom of each is taken until k.
PRIORITY: Final[tuple[tuple[str, Mapping[str, object]], ...]] = (
    ("internal_anomaly", {"detector": "robust_z"}),
    ("external_anomaly", {"detector": "robust_z"}),
    ("onset_precedence", {"scope": "self"}),
    ("change_proximity", {}),
    ("self_time_share", {}),
    ("spectrum", {}),
    ("log_new_template", {"error_level_only": True}),
    ("log_error_rate", {}),
    ("silence", {}),
    ("edge_gap", {"direction": "in", "quantile": "p50"}),
    ("peer_contrast", {}),
    ("propagation", {"scope": "entry"}),
)
#: Args shown on an atom line, per kind (the rest is in the id).
_KEY_ARGS: Final[Mapping[str, tuple[str, ...]]] = {
    "internal_anomaly": ("family", "source"),
    "external_anomaly": ("family", "source"),
    "onset_precedence": ("scope",),
    "propagation": ("scope",),
    "change_proximity": ("event_kind",),
    "peer_contrast": ("source",),
    "edge_gap": ("direction", "quantile"),
}
_PATH_NODES: Final = 6
_ONSETS_SHOWN: Final = 5
_AGAINST: Final = 2
_MIN_K: Final = 2


@dataclass(frozen=True)
class CardDeck:
    """The deck of 06 §3.7: case card, candidate cards, library, rendered text and budget fields."""

    case: Mapping[str, Any]
    candidates: tuple[Mapping[str, Any], ...]
    library: tuple[Mapping[str, Any], ...]
    text: str
    approx_tokens: int
    truncated: bool
    deck_sha256: str


def _num(x: float) -> str:
    return format(x, ".3g")


def _args(atom: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(atom["args_json"])


def _line(atom: Mapping[str, Any]) -> str:
    args = _args(atom)
    key = "/".join(str(args[k]) for k in _KEY_ARGS.get(atom["kind"], ()))
    value = _num(atom["value"]) if atom["unit"] is None else f"{atom['unit']}={_num(atom['value'])}"
    return " ".join(p for p in (atom["atom_id"], atom["kind"], key, value) if p)


def _pick(atoms: Sequence[Mapping[str, Any]], k: int) -> list[Mapping[str, Any]]:
    chosen: list[Mapping[str, Any]] = []
    for kind, where in PRIORITY:
        found = [
            a for a in atoms if a["kind"] == kind and all(_args(a).get(x) == v for x, v in where.items())
        ]
        if kind == "silence":
            found = [a for a in found if a["value"] == 1.0]
        if found and len(chosen) < k:
            chosen.append(min(found, key=lambda a: (-a["value"], a["atom_id"])))
    return chosen


def _top(atoms: Sequence[Mapping[str, Any]], kind: str) -> float | None:
    found = [a["value"] for a in atoms if a["kind"] == kind and _args(a).get("detector") == "robust_z"]
    return max(found) if found else None


def _cards(ctx: RunContext, slate: models.Slate, order: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        r for r in ctx.read_table("evidence").to_pylist() if r["origin"] == "engine"
    ]
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["candidate"], []).append(r)
    edges = ctx.read_table("graph.edges").to_pylist() if ctx.exists("graph.edges") else []
    paths = ctx.read_table("graph.paths").to_pylist() if ctx.exists("graph.paths") else []
    deltas = {}
    if ctx.exists("changes"):
        deltas = {r["change_id"]: r["delta_to_onset_ms"] for r in ctx.read_table("changes").to_pylist()}
    slots = {c.service: c for c in slate.candidates}
    cards: list[dict[str, Any]] = []
    for service in order:
        c, mine = slots[service], by.get(service, [])
        path = next((p["nodes"] for p in paths if p["candidate"] == service and p["path_rank"] == 1), None)
        changes = [a for a in mine if a["kind"] == "change_proximity"]
        latest = max(changes, key=lambda a: (a["value"], a["atom_id"]), default=None)
        change = None
        if latest is not None:
            delta = deltas.get(_args(latest)["change_id"])
            change = {
                "event_kind": _args(latest)["event_kind"],
                "ms_before_onset": None if delta is None else -delta,
            }
        against: list[str] = []
        own = _top(mine, "internal_anomaly") or 0.0  # I(s) = 0 without an atom (07 §2.1)
        callees = sorted({e["dst"] for e in edges if e["src"] == service})
        louder = [(z, d) for d in callees if (z := _top(by.get(d, []), "internal_anomaly")) is not None]
        louder = [(z, d) for z, d in louder if z >= own]
        if louder:
            z, d = min(louder, key=lambda t: (-t[0], t[1]))
            against.append(f"callee {d} has internal z={_num(z)} >= {_num(own)}")
        deps = [a for a in mine if a["kind"] == "onset_precedence" and _args(a)["scope"] == "dependents"]
        if deps and deps[0]["value"] < 1.0:
            against.append(f"precedes only {_num(deps[0]['value'])} of its anomalous dependents")
        cards.append(
            {
                "rank": c.rank,
                "service": service,
                "mode": c.mode,
                "fault_class": c.fault_class,
                "indicator": c.indicator,
                "fused_score": c.fused_score,
                "all_atoms": mine,
                "path": None if path is None else list(path)[:_PATH_NODES],
                "change": change,
                "against": against[:_AGAINST],
            }
        )
    return cards


def _case(ctx: RunContext) -> dict[str, Any]:
    alert = ctx.read_model("alert", models.Alert)
    onsets = ctx.read_model("onsets", models.Onsets)
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    rows: list[dict[str, Any]] = ctx.read_table("evidence").to_pylist()
    selfs = [r for r in rows if r["kind"] == "onset_precedence" and _args(r)["scope"] == "self"]
    entries: list[dict[str, Any]] = []
    for s in onsets.entry_services:
        z = _top([r for r in rows if r["candidate"] == s], "external_anomaly")
        entries.append({"service": s, "external_z": z})
    return {
        "t_onset_s": (onsets.t_onset_ns - alert.t_alert_ns) / 1e9,
        "entries": entries,
        "sources": [s for s, on in sorted(manifest.sources.model_dump().items()) if on],
        "onsets": [
            {"service": r["candidate"], "ms": r["value"]}
            for r in sorted(selfs, key=lambda r: (r["value"], r["candidate"]))[:_ONSETS_SHOWN]
        ],
    }


def _library(ctx: RunContext) -> list[dict[str, Any]]:
    ranges = read_domain(ctx).ranges
    return [
        {
            "name": p.name,
            "params": [
                {"name": q.name, "type": q.type, "range": ranges.get(p.name, {}).get(q.name)}
                for q in p.params
            ],
            "polarity": "supports" if p.polarity == 1 else "refutes",
        }
        for p in LIBRARY.values()
    ]


def _render(
    case: Mapping[str, Any], cards: Sequence[Mapping[str, Any]], library: Sequence[Mapping[str, Any]]
) -> str:
    entries = " ".join(
        e["service"] + ("" if e["external_z"] is None else f"(z={_num(e['external_z'])})")
        for e in case["entries"]
    )
    sources = ",".join(case["sources"])
    lines = [
        f"case: onset {_num(case['t_onset_s'])}s after alert; entries {entries or '-'}; sources {sources}"
    ]
    if case["onsets"]:
        lines.append(
            "first onsets: " + ", ".join(f"{o['service']} {_num(o['ms'])}ms" for o in case["onsets"])
        )
    for c in cards:
        head = f"#{c['rank']} {c['service']} mode={c['mode']} fault={c['fault_class']}"
        lines.append(f"{head} indicator={c['indicator']} fused={_num(c['fused_score'])}")
        lines.extend(f"  {_line(a)}" for a in c["atoms"])
        if c["path"]:
            lines.append("  path " + " > ".join(c["path"]))
        if c["change"] is not None:
            ms = c["change"]["ms_before_onset"]
            lines.append(
                f"  change {c['change']['event_kind']}"
                + ("" if ms is None else f" {_num(ms)}ms before onset")
            )
        lines.extend(f"  against: {fact}" for fact in c["against"])
    for p in library:
        params = ", ".join(
            f"{q['name']}:{q['type']}"
            + ("" if q["range"] is None else f"[{_num(q['range'][0])},{_num(q['range'][1])}]")
            for q in p["params"]
        )
        lines.append(f"check {p['name']}({params}) {p['polarity']}")
    return "\n".join(lines) + "\n"


def evidence_cards(
    slate: models.Slate, k: int | None = None, *, ctx: RunContext, order: Sequence[str] | None = None
) -> CardDeck:
    """The card deck for `slate` (06 §3.7); `k` defaults to `cards.k_default`, `order` (a permutation of
    the slate services) to slate rank order. Reads only through `ctx`; writes nothing."""
    cfg = ctx.config.section("faultloom")["cards"]
    services = [c.service for c in slate.candidates]
    chosen = list(services if order is None else order)
    if sorted(chosen) != sorted(services):
        msg = f"order must be a permutation of the slate services {services}, got {chosen}"
        raise ValueError(msg)
    case: dict[str, Any] = _case(ctx)
    cards, library = _cards(ctx, slate, chosen), _library(ctx)
    k_now, truncated = int(cfg["k_default"] if k is None else k), False

    def build() -> tuple[dict[str, Any], str, int]:
        shown = [
            {**{x: c[x] for x in c if x != "all_atoms"}, "atoms": _pick(c["all_atoms"], k_now)} for c in cards
        ]
        deck: dict[str, Any] = {"case": case, "candidates": shown, "library": library, "truncated": truncated}
        text = _render(case, shown, library)
        return deck, text, math.ceil(len(text.encode("utf-8")) / int(cfg["bytes_per_token"]))

    deck, text, tokens = build()
    budget = int(cfg["max_tokens"])
    while tokens > budget and k_now > _MIN_K:
        k_now -= 1
        deck, text, tokens = build()
    if tokens > budget and case["onsets"]:
        case = {**case, "onsets": []}
        deck, text, tokens = build()
    while tokens > budget and cards:
        cards, truncated = cards[:-1], True
        deck, text, tokens = build()
    body = {**deck, "text": text, "approx_tokens": tokens}
    return CardDeck(
        case=deck["case"],
        candidates=tuple(deck["candidates"]),
        library=tuple(library),
        text=text,
        approx_tokens=tokens,
        truncated=truncated,
        deck_sha256=sha256_json(body),
    )


def deck_dict(deck: CardDeck) -> dict[str, Any]:
    """The deck as plain data without `deck_sha256` (what the hash covers)."""
    return {k: v for k, v in dataclasses.asdict(deck).items() if k != "deck_sha256"}
