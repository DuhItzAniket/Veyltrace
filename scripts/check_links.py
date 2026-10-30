"""Check relative links and #anchors in Markdown files.

Checks every inline link/image `[text](target)` and reference definition
`[label]: target` in *.md files:
  - relative file or directory targets must exist (URL-decoded, relative to the file);
  - `#anchor` (same file) and `file.md#anchor` must match a heading slug
    (GitHub style) or an explicit <a id/name="..."> in the target file.
Skipped: http(s), mailto and any other `scheme:` link, links inside code spans and
fenced code blocks, anchors into non-Markdown files.

GitHub-style slug: heading text without Markdown markup, lower-cased, every
character that is not a letter, digit, space, hyphen or underscore removed,
spaces turned into hyphens; repeated slugs get -1, -2, ...

Usage
  python scripts/check_links.py                    # all *.md in the repo
  python scripts/check_links.py docs AGENTS.md     # only these files/folders
  python scripts/check_links.py --exclude reports  # skip a path prefix (repeatable)

Exit codes: 0 no broken links, 1 broken links found, 2 usage error.
Standard library only; runs on Windows, macOS and Linux.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
PRUNE = {".git", "node_modules", ".venv", "venv", "__pycache__", "_hackday-v1", "dist", "build"}
PRUNE_PREFIXES = (".claude/worktrees/",)

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
HTML_ANCHOR = re.compile(r"""<a\s+[^>]*?(?:id|name)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
INLINE_LINK = re.compile(
    r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]"            # [text] allowing one level of nested []
    r"\(\s*(<[^>]*>|[^)\s]*(?:\([^)\s]*\)[^)\s]*)*)"  # target, allowing balanced ()
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"   # optional title
)
REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
MD_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
HTML_TAG = re.compile(r"<[^>]+>")


def slugify(text: str) -> str:
    text = MD_LINK_TEXT.sub(r"\1", text)
    text = HTML_TAG.sub("", text)
    text = text.replace("`", "")
    text = re.sub(r"(\*\*|__|\*|~~)", "", text)
    text = text.strip().lower()
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in " -_" or cat[0] in ("L", "N"):
            out.append("-" if ch == " " else ch)
    return "".join(out)


def strip_code_spans(line: str) -> str:
    return CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)


def iter_lines(path: Path):
    """Yield (lineno, line, in_code) for a Markdown file."""
    fence: str | None = None
    for no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)[0] * len(m.group(1))
            yield no, line, True
            continue
        if fence is not None:
            if line.strip().startswith(fence) and set(line.strip()) <= {fence[0]}:
                fence = None
            yield no, line, True
            continue
        yield no, line, False


@lru_cache(maxsize=None)
def anchors_of(path: Path) -> frozenset[str]:
    seen: dict[str, int] = {}
    found: set[str] = set()

    def add(slug: str) -> None:
        n = seen.get(slug, 0)
        found.add(slug if n == 0 else f"{slug}-{n}")
        seen[slug] = n + 1

    prev: str | None = None
    for _, line, in_code in iter_lines(path):
        if in_code:
            prev = None
            continue
        for m in HTML_ANCHOR.finditer(line):
            found.add(m.group(1).lower())
        m = ATX.match(line)
        if m:
            add(slugify(m.group(2)))
            prev = None
            continue
        if (
            SETEXT.match(line)
            and prev is not None
            and prev.strip()
            and "|" not in prev
            and not re.match(r"^ {0,3}([-*+]|\d+[.)])\s", prev)
        ):
            add(slugify(prev))
            prev = None
            continue
        prev = line
    return frozenset(found)


def targets_in(path: Path):
    """Yield (lineno, raw_target) for links outside code."""
    for no, line, in_code in iter_lines(path):
        if in_code:
            continue
        clean = strip_code_spans(line)
        m = REF_DEF.match(clean)
        if m:
            yield no, m.group(1)
            continue
        for m in INLINE_LINK.finditer(clean):
            yield no, m.group(1)


def check_target(src: Path, raw: str) -> str | None:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if not target or SCHEME.match(target) or target.startswith("//"):
        return None
    path_part, _, anchor = target.partition("#")
    path_part = unquote(path_part.split("?", 1)[0])
    anchor = unquote(anchor)
    if path_part:
        dest = (ROOT / path_part.lstrip("/")) if path_part.startswith("/") else (src.parent / path_part)
        dest = dest.resolve()
        if not dest.exists():
            return "file not found"
    else:
        dest = src
    if anchor and dest.is_file() and dest.suffix.lower() == ".md":
        if anchor.lower() not in anchors_of(dest):
            return f"anchor #{anchor} not found in {dest.relative_to(ROOT).as_posix() if dest.is_relative_to(ROOT) else dest}"
    return None


def collect(paths: list[str], excludes: list[str]) -> list[Path]:
    files: list[Path] = []
    roots = [ROOT / p for p in paths] if paths else [ROOT]
    for r in roots:
        if r.is_file() and r.suffix.lower() == ".md":
            files.append(r.resolve())
        elif r.is_dir():
            for p in r.rglob("*.md"):
                parts = p.relative_to(ROOT).parts
                if any(part in PRUNE for part in parts):
                    continue
                files.append(p.resolve())
        else:
            print(f"warning: {r} is not a Markdown file or folder", file=sys.stderr)
    out = []
    for f in sorted(set(files)):
        relp = f.relative_to(ROOT).as_posix()
        if relp.startswith(PRUNE_PREFIXES) or any(relp.startswith(e.rstrip("/")) for e in excludes):
            continue
        out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="files or folders relative to the repo root (default: whole repo)")
    ap.add_argument("--exclude", action="append", default=[], help="path prefix to skip, relative to the repo root")
    args = ap.parse_args()
    if isinstance(sys.stdout, io.TextIOWrapper):  # Windows pipes default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    files = collect(args.paths, args.exclude)
    broken = 0
    checked = 0
    for f in files:
        for no, raw in targets_in(f):
            checked += 1
            problem = check_target(f, raw)
            if problem:
                broken += 1
                print(f"{f.relative_to(ROOT).as_posix()}:{no}: {raw} -> {problem}")
    print(f"{'FAIL' if broken else 'OK'}: {len(files)} file(s), {checked} link(s) checked, {broken} broken.")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
