"""`veyltrace data fetch rcaeval` (entry point `veyltrace.fetchers:rcaeval`; 01 §3.11).

Downloads RCAEval cases from the Hugging Face mirror into `${VEYLTRACE_DATA}/rcaeval/hf/<case>/`,
verifies every file against the size and hash the Hugging Face tree API publishes, and writes the
private index `index/<suite>.json` and `rcaeval/fetch.lock.json` (SHA-256 and size of every file).
Only the adapter's allow-listed files and `inject_time.txt` go into case directories; the
ground-truth index `cases.parquet` goes to `rcaeval/answers/` for bench; `root_cause.txt` (a label
in 8 RE3-SS cases) is never fetched.

Isolation: the single network exemption of the engines (02 §6.1, §9). Stdlib `urllib.request`
only; nothing under `veyltrace_infralume` other than this subpackage imports it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final, Protocol, cast

from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import UsageError
from veyltrace_core.fetch import FetchRequest
from veyltrace_infralume.casekey import SUITES, CaseKey, parse_case_dir, parse_suite
from veyltrace_infralume.index import write_index

__all__ = ["FetchError", "RemoteFile", "Transport", "fetch", "list_tree", "plan"]

#: 01 §4 `fetch.rcaeval.hf_repo`; a constant because `data fetch` has no run config.
HF_REPO: Final = "phamquiluan/RCAEval"
#: Branch read from Hugging Face (a priori); fetch.lock.json pins the bytes actually fetched.
HF_REVISION: Final = "main"
HF_HOST: Final = "https://huggingface.co/"
TREE_URL: Final = HF_HOST + "api/datasets/{repo}/tree/{rev}?recursive=true&expand=false"
FILE_URL: Final = HF_HOST + "datasets/{repo}/resolve/{rev}/{path}"
#: Files copied into a case directory: the adapter's Hugging Face allow-list and the hint file.
CASE_FILES: Final = frozenset({"inject_time.txt", "logs.parquet", "metrics.parquet", "traces.parquet"})
#: The HF ground-truth index: fetched for bench only, never into a case directory (01 §3.11).
ANSWER_FILES: Final = frozenset({"cases.parquet"})
HF_DIR: Final = PurePosixPath("rcaeval/hf")
ANSWERS_DIR: Final = PurePosixPath("rcaeval/answers")
LOCK_FILE: Final = PurePosixPath("rcaeval/fetch.lock.json")
#: Bytes per read while streaming a download, and seconds before a stalled socket fails (a priori).
CHUNK_BYTES: Final = 1 << 20
TIMEOUT_S: Final = 120
USER_AGENT: Final = "veyltrace-data-fetch"
EXIT_OK: Final = 0
EXIT_ERROR: Final = 1
EXIT_USAGE: Final = 2
_NEXT: Final = re.compile(r'<([^>]+)>;\s*rel="next"')


class FetchError(Exception):
    """A download failed or did not match its published size or hash."""


@dataclass(frozen=True)
class RemoteFile:
    """One file of the Hugging Face tree: repo path, size, LFS SHA-256 (None for plain git files)
    and git blob id (SHA-1 of `blob <size>\\0<bytes>`, used to verify plain files)."""

    path: str
    size: int
    sha256: str | None
    git_oid: str


class Transport(Protocol):
    """HTTP GET as the fetcher needs it: `get` returns a small body (a tree page) and its `Link`
    header, `open` a readable stream of a file. Tests pass an in-memory fake."""

    def get(self, url: str) -> tuple[bytes, str | None]: ...

    def open(self, url: str) -> AbstractContextManager[IO[bytes]]: ...


class UrllibTransport:
    """The real transport: stdlib urllib, redirects followed (HF serves files from a CDN)."""

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def get(self, url: str) -> tuple[bytes, str | None]:
        with urllib.request.urlopen(self._request(url), timeout=TIMEOUT_S) as resp:
            body: bytes = resp.read()
            link: str | None = resp.headers.get("Link")
        return body, link

    def open(self, url: str) -> AbstractContextManager[IO[bytes]]:
        return cast(
            "AbstractContextManager[IO[bytes]]", urllib.request.urlopen(self._request(url), timeout=TIMEOUT_S)
        )


def _remote(item: object) -> RemoteFile | None:
    """A RemoteFile from one tree entry, or None for directories; FetchError if malformed."""
    if not isinstance(item, dict):
        raise FetchError(f"tree entry is not an object: {item!r}")
    entry = cast("dict[str, Any]", item)
    if entry.get("type") != "file":
        return None
    lfs: object = entry.get("lfs")
    sha256: object = cast("dict[str, Any]", lfs).get("oid") if isinstance(lfs, dict) else None
    path, size, oid = entry.get("path"), entry.get("size"), entry.get("oid")
    if not (isinstance(path, str) and isinstance(size, int) and isinstance(oid, str)):
        raise FetchError(f"tree entry lacks path, size or oid: {entry!r}")
    if sha256 is not None and not isinstance(sha256, str):
        raise FetchError(f"tree entry {path!r} has a non-string LFS oid")
    return RemoteFile(path=path, size=size, sha256=sha256, git_oid=oid)


def list_tree(transport: Transport) -> list[RemoteFile]:
    """Every file of the dataset repo, following the API's `Link: rel="next"` pages, sorted by path."""
    url: str | None = TREE_URL.format(repo=HF_REPO, rev=HF_REVISION)
    files: list[RemoteFile] = []
    while url is not None:
        if not url.startswith(HF_HOST):
            raise FetchError(f"refusing to follow a tree page outside {HF_HOST}: {url}")
        body, link = transport.get(url)
        page: object = json.loads(body)
        if not isinstance(page, list):
            raise FetchError(f"tree page {url} is not a JSON list")
        files.extend(f for f in map(_remote, cast("list[object]", page)) if f is not None)
        found = _NEXT.search(link or "")
        url = found.group(1) if found else None
    return sorted(files, key=lambda f: f.path.encode())


def plan(
    files: Iterable[RemoteFile], suites: Sequence[str], cases: int | None
) -> tuple[list[RemoteFile], dict[str, CaseKey]]:
    """The files to fetch for `suites` (at most `cases` case dirs per suite, by name) plus the
    answer index, and the canonical key of every selected case directory."""
    wanted: list[RemoteFile] = []
    by_dir: dict[str, list[RemoteFile]] = {}
    keys: dict[str, CaseKey] = {}
    for f in files:
        parts = PurePosixPath(f.path).parts
        if len(parts) == 1 and parts[0] in ANSWER_FILES:
            wanted.append(f)
        elif len(parts) == 2 and parts[1] in CASE_FILES:
            key = parse_case_dir(parts[:1])
            if key is not None and key.suite in suites:
                by_dir.setdefault(parts[0], []).append(f)
                keys[parts[0]] = key
    chosen: dict[str, CaseKey] = {}
    for suite in suites:
        dirs = sorted((d for d, k in keys.items() if k.suite == suite), key=str.encode)
        chosen.update((d, keys[d]) for d in dirs[:cases])
    for d in sorted(chosen, key=str.encode):
        wanted.extend(by_dir[d])
    return wanted, chosen


def _copy_hashed(src: IO[bytes], size: int, sink: IO[bytes] | None = None) -> tuple[int, str, str]:
    """(bytes, SHA-256, git blob SHA-1) of a stream, copied to `sink` if one is given."""
    sha, git, n = hashlib.sha256(), hashlib.sha1(b"blob %d\0" % size, usedforsecurity=False), 0
    while chunk := src.read(CHUNK_BYTES):
        sha.update(chunk)
        git.update(chunk)
        n += len(chunk)
        if sink is not None:
            sink.write(chunk)
    return n, sha.hexdigest(), git.hexdigest()


def _verified(remote: RemoteFile, got: tuple[int, str, str]) -> bool:
    size, sha256, git_oid = got
    return size == remote.size and (sha256 == remote.sha256 if remote.sha256 else git_oid == remote.git_oid)


def download(transport: Transport, remote: RemoteFile, dest: Path) -> tuple[str, bool]:
    """Fetch `remote` to `dest` unless a verified copy is there; (SHA-256, downloaded?)."""
    if dest.is_file() and dest.stat().st_size == remote.size:
        with dest.open("rb") as fh:
            got = _copy_hashed(fh, remote.size)
        if _verified(remote, got):
            return got[1], False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = textio.tmp_path(dest)
    url = FILE_URL.format(repo=HF_REPO, rev=HF_REVISION, path=remote.path)
    try:
        with transport.open(url) as resp, part.open("wb") as out:
            got = _copy_hashed(resp, remote.size, out)
        if not _verified(remote, got):
            raise FetchError(f"{remote.path}: {got[0]} bytes do not match the published size or hash")
        textio.atomic_replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    return got[1], True


def _inside_git_tree(root: Path) -> Path | None:
    resolved = root.resolve()
    return next((p for p in (resolved, *resolved.parents) if (p / ".git").exists()), None)


def _read_lock(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw: object = json.loads(textio.read_text(path))
    return cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}


def _suites(req: FetchRequest) -> tuple[str, ...]:
    if req.source not in (None, "hf"):
        raise UsageError(f"rcaeval fetch: --source {req.source} is not supported yet; use --source hf")
    if req.suite is None:
        return SUITES
    parse_suite(req.suite)
    return (req.suite,)


def fetch(req: FetchRequest, *, transport: Transport | None = None) -> int:
    """Fetch the requested RCAEval suites under `req.data_root`; returns a process exit code."""
    try:
        suites = _suites(req)
    except UsageError as exc:
        print(f"rcaeval fetch: {exc}", file=sys.stderr)
        return EXIT_USAGE
    root = Path(req.data_root)
    if (repo := _inside_git_tree(root)) is not None:
        print(f"rcaeval fetch: refusing to download into the git work tree {repo}", file=sys.stderr)
        return EXIT_USAGE
    net = transport if transport is not None else UrllibTransport()
    try:
        files, chosen = plan(list_tree(net), suites, req.cases)
        lock = _read_lock(root / LOCK_FILE)
        fetched = 0
        for remote in files:
            parts = PurePosixPath(remote.path).parts
            rel = (ANSWERS_DIR if parts[0] in ANSWER_FILES else HF_DIR).joinpath(*parts)
            sha256, downloaded = download(net, remote, root.joinpath(*rel.parts))
            lock[rel.as_posix()] = {"bytes": remote.size, "sha256": sha256}
            fetched += downloaded
    except (FetchError, OSError, urllib.error.URLError, ValueError) as exc:
        print(f"rcaeval fetch: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for suite in suites:
        entries = {k.case_id: (HF_DIR / d).as_posix() for d, k in chosen.items() if k.suite == suite}
        if entries:
            write_index(root, suite, entries)
    textio.write_bytes(root / LOCK_FILE, canonical_json(dict(sorted(lock.items()))))
    print(f"rcaeval: {len(chosen)} cases ({', '.join(suites)}), {len(files)} files, {fetched} downloaded")
    return EXIT_OK
