"""A minimal deterministic SVG renderer for the paper's data figures (R-17).

Why not matplotlib: its SVG and PDF output embed version strings, font paths and hash-salted ids,
and differ across freetype builds, so "regenerate identically" would hold on one laptop only; it
would also be bench's first heavy dependency. These figures are simple marks (points with
interval bars, connected per series; heatmap cells), drawn with fixed geometry, fixed-precision
coordinates and a generic font family, so the bytes depend only on the data. For the paper,
scripts/paper_generated.py converts each panel to TikZ (one `tikzpicture`, vector, 11 §10); it knows
exactly the elements and attributes written here and refuses anything else, so a change to this
module's markup needs the converter changed with it.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

from veyltrace_bench.tables.cells import fixed

WIDTH, HEIGHT = 640, 360  # px; a two-column figure at 1:1 (a priori layout)
MARGIN = (56, 16, 56, 140)  # left, top, bottom (ticks, axis label, note), right (legend) in px (a priori)
#: Distinguishable categorical colours, dark enough on white (a priori); series beyond 8 repeat.
PALETTE = ("#1b6ca8", "#d1495b", "#3a7d44", "#edae49", "#6c4f9e", "#00798c", "#8c564b", "#555555")
MISSING = "#dddddd"  # a heatmap cell without a value: grey, never the colour of 0
#: A heatmap's left margin fits its longest row label (Fig 6 and 8 labels were cut off at 56 px):
#: about 6.2 px per 11 px sans-serif character plus the 6 px gap and 4 px of air (a priori). It has
#: no legend, so its right margin is the top one's 16 px.
LABEL_CHAR_PX = 6.2
LABEL_PAD_PX = 10
#: A note under the plot wraps to lines of at most this many characters: the 584 px from the left
#: margin to the right edge hold about 94 at LABEL_CHAR_PX, less some air (a priori; Fig 8's
#: one-line note ran past the edge). Each further line adds LINE_PX to the frame's height.
NOTE_CHARS = 88
LINE_PX = 15  # a priori: line spacing of wrapped text (notes, a placeholder's reason)
#: The generator's number at the start of a title ("Fig. 5: "): the SVG's <title> keeps it (the
#: repo's numbering), drawn text drops it, since the paper's caption carries LaTeX's number.
NUMBERED = re.compile(r"^Fig\. \d+: ")


def _n(value: float) -> str:
    """A coordinate with 2 decimals and no trailing zeros, so output never depends on float noise."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _el(tag: str, **attrs: float | str) -> str:
    """A childless element; numbers through `_n`, `_` in a name becomes `-`."""
    body = " ".join(
        f'{k.replace("_", "-")}="{_n(v) if isinstance(v, float | int) else v}"' for k, v in attrs.items()
    )
    return f"<{tag} {body}/>"


def _text(x: float, y: float, value: str, anchor: str = "middle", extra: str = "") -> str:
    return f'<text x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}"{extra}>{escape(value)}</text>'


def _frame(title: str, body: list[str], extra_lines: int = 0) -> str:
    """The SVG around `body`, `extra_lines` × LINE_PX taller than HEIGHT for a wrapped note."""
    height = HEIGHT + LINE_PX * extra_lines
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="sans-serif" font-size="11">'
    )
    return "\n".join([head, f"<title>{escape(title)}</title>", *body, "</svg>"]) + "\n"


def _note(note: str) -> list[str]:
    """The note under the plot from the left margin, wrapped to NOTE_CHARS; one line per item."""
    return [
        _text(MARGIN[0], HEIGHT - 6 + LINE_PX * i, line, "start", ' fill="#555"')
        for i, line in enumerate(textwrap.wrap(note, NOTE_CHARS) or [note])
    ]


XY = tuple[float, float, float | None, float | None]  # x, y and the y interval (low, high)


def lines(
    title: str, x_label: str, y_label: str, xs: Sequence[float], series: Mapping[str, Sequence[XY]], note: str
) -> str:
    """Points with interval bars per series ({label: points}), joined in x order, on a [0, 1] y
    axis; `note` (e.g. how many points are not run, which are never drawn) goes under the plot."""
    left, top, bottom, right = MARGIN
    w, h = WIDTH - left - right, HEIGHT - top - bottom
    lo, hi = min(xs), max(xs)

    def px(x: float) -> float:
        return left + (w * (x - lo) / (hi - lo) if hi > lo else w / 2)

    def py(y: float) -> float:
        return top + h * (1 - y)

    body = [_el("rect", x=left, y=top, width=w, height=h, fill="none", stroke="#999")]
    body += [_text(left - 6, py(t) + 4, f"{t:.2f}", "end") for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    body += [_text(px(x), top + h + 16, f"{x:g}") for x in xs]
    body.append(_text(left + w / 2, top + h + 32, x_label))
    body.append(_text(14, top + h / 2, y_label, extra=f' transform="rotate(-90 14 {_n(top + h / 2)})"'))
    for i, (label, points) in enumerate(series.items()):
        colour = PALETTE[i % len(PALETTE)]
        pts = sorted(points)
        if len(pts) > 1:
            path = " ".join(f"{_n(px(x))},{_n(py(y))}" for x, y, _, _ in pts)
            body.append(_el("polyline", points=path, fill="none", stroke=colour, stroke_width=1.5))
        for x, y, low, high in pts:
            if low is not None and high is not None:
                body.append(_el("line", x1=px(x), y1=py(low), x2=px(x), y2=py(high), stroke=colour))
            body.append(_el("circle", cx=px(x), cy=py(y), r=3, fill=colour))
        key_y = top + 12 + 16 * i
        body.append(_el("rect", x=WIDTH - right + 10, y=key_y - 8, width=10, height=10, fill=colour))
        body.append(_text(WIDTH - right + 26, key_y + 1, label, "start"))
    notes = _note(note)
    return _frame(title, body + notes, len(notes) - 1)


NO_VALUE = "no value"  # a heatmap cell without a value ("not run" only for a cut experiment, 04 §10.8)


def heatmap(
    title: str,
    rows: Sequence[str],
    columns: Sequence[str],
    values: Sequence[Sequence[float | None]],
    note: str,
    missing: Sequence[Sequence[str]] | None = None,
) -> str:
    """A [0, 1] heatmap (white to blue) with each value printed in its cell; a None cell is grey
    and reads its word in `missing` (n/a, not run, revised; "no value" by default; the CSV status
    says why), never the colour of 0."""
    _, top, bottom, _ = MARGIN
    left = max(MARGIN[0], round(LABEL_PAD_PX + LABEL_CHAR_PX * max((len(r) for r in rows), default=0)))
    right = top
    w, h = (WIDTH - left - right) / max(1, len(columns)), (HEIGHT - top - bottom) / max(1, len(rows))
    body = [_text(left + w * (j + 0.5), top + h * len(rows) + 16, col) for j, col in enumerate(columns)]
    for i, row in enumerate(rows):
        body.append(_text(left - 6, top + h * (i + 0.5) + 4, row, "end"))
        for j, v in enumerate(values[i]):
            x, y = left + w * j, top + h * i
            t = 0.0 if v is None else min(1.0, max(0.0, v))  # colour scale clamped to [0, 1]
            fill = MISSING if v is None else f"#{255 - round(200 * t):02x}{255 - round(150 * t):02x}ff"
            body.append(_el("rect", x=x, y=y, width=w, height=h, fill=fill, stroke="#fff"))
            word = missing[i][j] if missing is not None else NO_VALUE
            body.append(_text(x + w / 2, y + h / 2 + 4, word if v is None else fixed(v)))  # tables' rounding
    notes = _note(note)
    return _frame(title, body + notes, len(notes) - 1)


PLACEHOLDER_CHARS = 96  # a priori: about 96 characters of 11 px sans-serif fit across the 640 px frame


def placeholder(title: str, reason: str) -> str:
    """A figure that cannot be drawn: its title (without the generator's number) and the reason,
    as given (the caller says whether it is "not run" or has no data), wrapped so the paper shows
    the whole gap."""
    lines = textwrap.wrap(reason, PLACEHOLDER_CHARS)
    body = [_text(WIDTH / 2, HEIGHT / 2, NUMBERED.sub("", title))]
    body += [_text(WIDTH / 2, HEIGHT / 2 + 18 + LINE_PX * i, line) for i, line in enumerate(lines)]
    return _frame(title, body)
