"""`card.md`: the card rendered as Markdown from `card.json` alone (10 §3.7; package rule 7).

Layout: title; status banner with the confidence level, set size and margin (never a probability);
summary; candidate set ("empty" when empty); evidence table; timeline as `HH:MM:SS UTC — label`;
path joined with →; why-not; asks; next steps with playbook ids; the narrator line; a footer with
both hashes and the replay command. No render-time timestamp, so the bytes are stable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from veyltrace_causivra.fmt import format_margin, format_number, format_time_utc

__all__ = ["render_card"]

EMPTY: Final = "empty"
NONE: Final = "none"
ARROW: Final = " \u2192 "
DASH: Final = " \u2014 "
REPLAY: Final = "uv run veyltrace replay <run dir>/receipt.json"


def _cell(text: str) -> str:
    """A Markdown table cell: pipes escaped, line breaks flattened."""
    return text.replace("|", "\\|").replace("\n", " ")


def _bullets(items: Sequence[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else [f"- {NONE}"]


def _cites(cites: Sequence[str]) -> str:
    return f" (cites: {', '.join(cites)})" if cites else ""


def render_card(card: Mapping[str, Any], sig_digits: int) -> str:
    """The Markdown text of `card` (LF line endings; the writer adds none of its own)."""
    conf = card["confidence"]
    members = [
        c["service"] if c["component"] in (None, c["service"]) else f"{c['service']} ({c['component']})"
        for c in card["candidate_set"]
    ]
    lines = [
        f"# {card['title']}",
        "",
        f"**{card['status']}** · confidence: {conf['level']} · candidate set size: {conf['set_size']}"
        f" · margin: {format_margin(conf['margin'])}",
        "",
        "## Summary",
        "",
        *(_bullets([f"{s['text']}{_cites(s['cites'])}" for s in card["summary"]])),
        "",
        "## Candidate set",
        "",
        *(_bullets(members) if members else [f"- {EMPTY}"]),
        "",
        "## Evidence",
        "",
    ]
    if card["evidence_table"]:
        lines += ["| Atom | Evidence | Value | Unit |", "|---|---|---|---|"]
        lines += [
            f"| {r['atom_id']} | {_cell(r['label'])} | {format_number(r['value'], sig_digits)} "
            f"| {_cell(r['unit'] or '')} |"
            for r in card["evidence_table"]
        ]
    else:
        lines.append(f"- {NONE}")
    lines += [
        "",
        "## Timeline",
        "",
        *_bullets(
            [f"{format_time_utc(e['t_ns'])}{DASH}{e['label']}{_cites(e['cites'])}" for e in card["timeline"]]
        ),
        "",
        "## Path",
        "",
        ARROW.join(card["path"]) if card["path"] else NONE,
        "",
        "## Why not",
        "",
        *_bullets([f"**{w['service']}**: {w['text']}{_cites(w['cites'])}" for w in card["why_not"]]),
        "",
        "## Asks",
        "",
        *_bullets([a["text"] for a in card["asks"]]),
        "",
        "## Next steps",
        "",
        *_bullets([f"{s['text']} ({s['playbook_id']})" for s in card["next_steps"]]),
        "",
    ]
    narrator = card["narrator"]
    lines.append(
        "prose: template" if narrator["path"] == "template" else f"prose: LLM {narrator['model']}, checked"
    )
    lines += [
        "",
        "---",
        "",
        f"verdict_hash: `{card['verdict_hash']}`  ",
        f"card_hash: `{card['card_hash']}`  ",
        f"replay: `{REPLAY}`",
        "",
    ]
    return "\n".join(lines)
