"""The Nezha fetcher against an in-memory GitHub (01 §3.11): no network in unit tests."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest

from veyltrace_core.fetch import FetchRequest
from veyltrace_infralume.adapters import nezha_layout as layout
from veyltrace_infralume.fetch import nezha as fn
from veyltrace_infralume.fetch.rcaeval import FetchError
from veyltrace_infralume.index import read_index

DAY = "rca_data/2022-08-22"
FAULTS = json.dumps({"03": [{"inject_time": "2022-08-22 03:53:54", "inject_pod": "p", "inject_type": "cpu"}]})
#: A day with one fault: the fetched files, and files of the repository that must stay behind.
FILES: dict[str, bytes] = {
    f"{DAY}/2022-08-22-fault_list.json": FAULTS.encode(),
    f"{DAY}/log/03_53_log.csv": b"Timestamp,TimeUnixNano\n",
    f"{DAY}/metric/frontend-579b9bff58-t2dbm_metric.csv": b"Time,TimeStamp\n",
    f"{DAY}/trace/03_53_trace.csv": b"TraceID\n",
    f"{DAY}/metric/front_service.csv": b"not fetched",
    f"{DAY}/traceid/03_53_traceid.csv": b"not fetched",
    "construct_data/2022-08-22/metric/x_metric.csv": b"not fetched",
    "README.md": b"not fetched",
}
WANTED = sorted(p for p in FILES if "front_service" not in p and p.startswith(DAY) and "traceid" not in p)


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _tree(files: dict[str, bytes], *, truncated: bool = False) -> bytes:
    entries = [{"path": p, "type": "blob", "sha": _blob(d), "size": len(d)} for p, d in sorted(files.items())]
    entries.append({"path": "rca_data", "type": "tree", "sha": "0" * 40})
    return json.dumps({"sha": fn.COMMIT, "tree": entries, "truncated": truncated}).encode()


def _archive(files: dict[str, bytes]) -> bytes:
    """A tar.gz shaped like GitHub's: every member under one `<repo>-<commit>/` directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(f"Nezha-{fn.COMMIT}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f"Nezha-{fn.COMMIT}/{DAY}/log/03_54_log.csv")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    return buf.getvalue()


class FakeGitHub:
    """Serves the tree API and the archive; counts archive downloads."""

    def __init__(self, tree: dict[str, bytes], archive: dict[str, bytes] | None = None) -> None:
        self.tree, self.archive, self.opened = tree, tree if archive is None else archive, 0

    def get(self, url: str) -> tuple[bytes, str | None]:
        assert url == fn.TREE_URL.format(repo=fn.REPO, commit=fn.COMMIT)
        return _tree(self.tree), None

    @contextmanager
    def open(self, url: str) -> Iterator[IO[bytes]]:
        assert url == fn.ARCHIVE_URL.format(repo=fn.REPO, commit=fn.COMMIT)
        self.opened += 1
        yield io.BytesIO(_archive(self.archive))


def _request(root: Path, **narrow: object) -> FetchRequest:
    return FetchRequest(name="nezha", data_root=root, **narrow)  # type: ignore[arg-type]  # test passes each field


def test_fetches_only_adapter_files_writes_index_and_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    net = FakeGitHub(FILES)
    assert fn.fetch(_request(tmp_path), transport=net) == 0
    src = tmp_path / "nezha" / "src"
    got = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    assert got == WANTED  # no front_service, traceid, construct_data, README or symlink
    assert all((src / p).read_bytes() == FILES[p] for p in WANTED)
    key = layout.nezha_key("ob", "2022-08-22", 0)
    assert list(read_index(tmp_path, "nezha-ob").values()) == ["nezha/src/rca_data/2022-08-22/0"]
    assert layout.discover(tmp_path)[0].key == key and read_index(tmp_path, "nezha-tt") == {}
    lock = json.loads((tmp_path / "nezha" / "fetch.lock.json").read_text(encoding="utf-8"))
    assert lock["commit"] == fn.COMMIT and sorted(lock["files"]) == [f"nezha/src/{p}" for p in WANTED]
    first = lock["files"][f"nezha/src/{WANTED[0]}"]
    assert first == {"bytes": len(FILES[WANTED[0]]), "sha256": hashlib.sha256(FILES[WANTED[0]]).hexdigest()}
    assert "1 nezha-ob" in capsys.readouterr().out and net.opened == 1


def test_a_second_run_downloads_nothing_and_a_damaged_file_is_refetched(tmp_path: Path) -> None:
    net = FakeGitHub(FILES)
    assert fn.fetch(_request(tmp_path), transport=net) == 0
    lock = (tmp_path / "nezha" / "fetch.lock.json").read_bytes()
    assert fn.fetch(_request(tmp_path), transport=net) == 0
    assert net.opened == 1 and (tmp_path / "nezha" / "fetch.lock.json").read_bytes() == lock
    damaged = tmp_path / "nezha" / "src" / WANTED[1]
    damaged.write_bytes(b"x" * len(FILES[WANTED[1]]))  # same size, other bytes
    assert fn.fetch(_request(tmp_path), transport=net) == 0
    assert net.opened == 2 and damaged.read_bytes() == FILES[WANTED[1]]


def test_bytes_that_do_not_match_the_commit_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tampered = FILES | {WANTED[0]: FILES[WANTED[0]] + b" "}
    assert fn.fetch(_request(tmp_path), transport=FakeGitHub(FILES, tampered)) == 1
    assert "do not match the commit's blob" in capsys.readouterr().err
    assert not (tmp_path / "nezha" / "src" / WANTED[0]).exists()  # nothing unverified is left behind
    partial = {p: d for p, d in FILES.items() if p != WANTED[2]}
    assert fn.fetch(_request(tmp_path), transport=FakeGitHub(FILES, partial)) == 1
    assert "lacks 1 listed file" in capsys.readouterr().err


def test_usage_errors_and_bad_trees(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fn.fetch(_request(tmp_path, cases=1), transport=FakeGitHub(FILES)) == 2
    assert fn.fetch(_request(tmp_path, suite="nezha-ob"), transport=FakeGitHub(FILES)) == 2
    assert "fetched whole" in capsys.readouterr().err
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert fn.fetch(_request(tmp_path / "repo" / "data"), transport=FakeGitHub(FILES)) == 2
    assert "git work tree" in capsys.readouterr().err
    with pytest.raises(FetchError, match="truncated"):
        fn.wanted_files(json.loads(_tree(FILES, truncated=True)))
    with pytest.raises(FetchError, match="no Nezha data file"):
        fn.wanted_files(json.loads(_tree({"README.md": b"x"})))
    assert [f.path for f in fn.wanted_files(json.loads(_tree(FILES)))] == WANTED


class _Dropping(io.BytesIO):
    """An archive stream whose connection drops after `limit` bytes, as GitHub's sometimes does."""

    def __init__(self, data: bytes, limit: int) -> None:
        super().__init__(data)
        self.limit = limit

    def read(self, size: int | None = -1) -> bytes:
        if self.tell() >= self.limit:
            raise http.client.IncompleteRead(b"")
        return super().read(min(size if size and size > 0 else self.limit, self.limit - self.tell()))


def test_a_dropped_connection_is_a_clean_error_and_the_next_run_resumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    net = FakeGitHub(FILES)
    whole = _archive(FILES)
    drop = {"on": True}

    @contextmanager
    def flaky(url: str) -> Iterator[IO[bytes]]:
        net.opened += 1
        yield _Dropping(whole, len(whole) // 2) if drop["on"] else io.BytesIO(whole)

    net.open = flaky  # type: ignore[method-assign]  # the fake's stream is replaced for this test
    assert fn.fetch(_request(tmp_path), transport=net) == 1
    assert "run the command again to resume" in capsys.readouterr().err
    assert not (tmp_path / "nezha" / "fetch.lock.json").exists()  # no lock for a partial fetch
    drop["on"] = False
    assert fn.fetch(_request(tmp_path), transport=net) == 0
    src = tmp_path / "nezha" / "src"
    assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()) == WANTED
