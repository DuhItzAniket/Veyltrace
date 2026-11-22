"""`veyltrace data fetch nezha` (entry point `veyltrace.fetchers:nezha`; 01 §3.11).

Nezha is published only as a git repository (IntelligentDDS/Nezha, MIT), so the fetcher streams
GitHub's tar archive of one pinned commit and extracts the files the adapter reads, plus each day's
fault list, into `${VEYLTRACE_DATA}/nezha/src/rca_data/`. Every extracted file is verified against
the size and git blob id that the GitHub tree API reports for that commit, so the bytes are tied to
the commit hash. Then it writes the private index of `nezha-ob` and `nezha-tt` and
`nezha/fetch.lock.json` (commit, SHA-256 and size of every file). A second run with every file
present and verified downloads nothing.

The fault lists hold the labels. They land beside the telemetry because bench derives the answer
keys from them; the adapter reads their `inject_time` only (01 §3.3).

Isolation: part of the single network exemption of the engines (02 §6.1, §9); stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final, cast

from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import UsageError
from veyltrace_core.fetch import FetchRequest
from veyltrace_infralume.adapters.nezha_layout import SRC, build_index
from veyltrace_infralume.fetch.rcaeval import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    FetchError,
    RemoteFile,
    Transport,
    UrllibTransport,
    _copy_hashed,  # pyright: ignore[reportPrivateUsage]  # same subpackage: one hashing loop
    _inside_git_tree,  # pyright: ignore[reportPrivateUsage]
    _verified,  # pyright: ignore[reportPrivateUsage]
)

__all__ = ["ARCHIVE_URL", "COMMIT", "REPO", "TREE_URL", "fetch", "wanted_files"]

#: 01 §4 `fetch.nezha.*`; constants because `data fetch` has no run config (as fetch.rcaeval).
REPO: Final = "IntelligentDDS/Nezha"
#: Pinned at O-08 (22 Nov 2026): `main` of that day; the format in 01 §3.3 was verified on it.
COMMIT: Final = "d8140101fdb4e7dfb60d3ef9f64706f382b68470"
TREE_URL: Final = "https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1"
ARCHIVE_URL: Final = "https://codeload.github.com/{repo}/tar.gz/{commit}"
LOCK_FILE: Final = PurePosixPath("nezha/fetch.lock.json")
#: Repository paths that are fetched: per day, the fault list and the files on the adapter's
#: allow-list. `traceid/`, `front_service.csv`, `dependency.csv`, `source_50.csv`,
#: `destination_50.csv` and `construct_data/` are not (01 §3.3).
_WANTED: Final = re.compile(
    r"rca_data/(\d{4}-\d{2}-\d{2})/"
    r"(?:\1-fault_list\.json|metric/[^/]+_metric\.csv|log/\d{2}_\d{2}_log\.csv|trace/\d{2}_\d{2}_trace\.csv)"
)
_SRC_DIR: Final = PurePosixPath(*SRC).parent  # nezha/src: repository paths start with rca_data/


def wanted_files(tree: object) -> list[RemoteFile]:
    """The fetched files of a GitHub tree response, sorted by path; FetchError if it is malformed
    or truncated (a truncated tree would silently fetch a partial dataset)."""
    if not isinstance(tree, dict) or cast("dict[str, Any]", tree).get("truncated") is not False:
        raise FetchError("the GitHub tree response is malformed or truncated")
    entries: object = cast("dict[str, Any]", tree).get("tree")
    if not isinstance(entries, list):
        raise FetchError("the GitHub tree response has no `tree` list")
    files: list[RemoteFile] = []
    for item in cast("list[object]", entries):
        entry = cast("dict[str, Any]", item) if isinstance(item, dict) else {}
        path, size, oid = entry.get("path"), entry.get("size"), entry.get("sha")
        if entry.get("type") != "blob" or not isinstance(path, str) or _WANTED.fullmatch(path) is None:
            continue
        if not (isinstance(size, int) and isinstance(oid, str)):
            raise FetchError(f"tree entry {path!r} lacks a size or blob id")
        files.append(RemoteFile(path=path, size=size, sha256=None, git_oid=oid))
    if not files:
        raise FetchError("the GitHub tree lists no Nezha data file")
    return sorted(files, key=lambda f: f.path.encode())


def _local(root: Path, remote: RemoteFile) -> Path:
    return root.joinpath(*_SRC_DIR.parts, *PurePosixPath(remote.path).parts)


def _present(root: Path, remote: RemoteFile) -> str | None:
    """The SHA-256 of the local copy if it matches the commit's blob, else None."""
    path = _local(root, remote)
    if not path.is_file() or path.stat().st_size != remote.size:
        return None
    with path.open("rb") as fh:
        got = _copy_hashed(fh, remote.size)
    return got[1] if _verified(remote, got) else None


def _extract(stream: IO[bytes], missing: dict[str, RemoteFile], root: Path) -> dict[str, str]:
    """Stream the commit's tar archive and write the `missing` files, each verified against its
    blob id before it replaces anything; repo path -> SHA-256. Member names are matched against the
    tree's paths, so nothing outside them (absolute paths, `..`, links) can be written."""
    done: dict[str, str] = {}
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            _, _, path = member.name.partition("/")  # the archive's top directory is <repo>-<commit>
            remote = missing.get(path)
            if remote is None or not member.isreg():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise FetchError(f"{path}: the archive member cannot be read")
            dest = _local(root, remote)
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = textio.tmp_path(dest)
            try:
                with part.open("wb") as out:
                    got = _copy_hashed(source, remote.size, out)
                if not _verified(remote, got):
                    raise FetchError(
                        f"{path}: {got[0]} bytes do not match the commit's blob {remote.git_oid}"
                    )
                textio.atomic_replace(part, dest)
            finally:
                part.unlink(missing_ok=True)
            done[path] = got[1]
    if absent := sorted(set(missing) - set(done)):
        raise FetchError(f"the archive lacks {len(absent)} listed file(s), e.g. {absent[0]}")
    return done


def fetch(req: FetchRequest, *, transport: Transport | None = None) -> int:
    """Fetch Nezha at the pinned commit under `req.data_root`; returns a process exit code."""
    try:
        if req.suite is not None or req.source is not None or req.cases is not None:
            raise UsageError(
                "nezha is one archive, fetched whole: --suite, --source and --cases do not apply"
            )
    except UsageError as exc:
        print(f"nezha fetch: {exc}", file=sys.stderr)
        return EXIT_USAGE
    root = Path(req.data_root)
    if (repo := _inside_git_tree(root)) is not None:
        print(f"nezha fetch: refusing to download into the git work tree {repo}", file=sys.stderr)
        return EXIT_USAGE
    net = transport if transport is not None else UrllibTransport()
    try:
        body, _ = net.get(TREE_URL.format(repo=REPO, commit=COMMIT))
        files = wanted_files(json.loads(body))
        hashes = {f.path: sha for f in files if (sha := _present(root, f)) is not None}
        missing = {f.path: f for f in files if f.path not in hashes}
        if missing:
            with net.open(ARCHIVE_URL.format(repo=REPO, commit=COMMIT)) as stream:
                hashes |= _extract(stream, missing, root)
        counts = build_index(root)
    except Exception as exc:
        # Any failure ends the command with exit 1, as a CLI boundary should. It is deliberately
        # broad: a connection dropped mid-archive raises http.client.IncompleteRead, which is not an
        # OSError, and the isolation rule keeps `http.client` out of this package (02 §9).
        # Files written so far are verified and stay, so the next run only fetches the rest.
        print(f"nezha fetch: {type(exc).__name__}: {exc}; run the command again to resume", file=sys.stderr)
        return EXIT_ERROR
    lock = {
        "commit": COMMIT,
        "files": {(_SRC_DIR / f.path).as_posix(): {"bytes": f.size, "sha256": hashes[f.path]} for f in files},
        "repo": REPO,
    }
    textio.write_bytes(root / LOCK_FILE, canonical_json(lock))
    cases = ", ".join(f"{n} {d}" for d, n in sorted(counts.items()))
    print(f"nezha: {cases} cases at {COMMIT[:12]}, {len(files)} files, {len(missing)} downloaded")
    return EXIT_OK
