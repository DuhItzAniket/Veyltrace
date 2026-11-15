"""The RCAEval fetcher against an in-memory Hugging Face (01 §3.11): no network in unit tests."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest

from veyltrace_core.fetch import FetchRequest, FetchSource
from veyltrace_infralume.casekey import parse_case_dir
from veyltrace_infralume.fetch import rcaeval as fr
from veyltrace_infralume.index import read_index

# Two RE2-OB cases, one RE2-SS case, a label file and the answer index (sorted, as HF lists them).
FILES: dict[str, bytes] = {
    "cases.parquet": b"answers",
    "re2ob_cartservice_cpu_1/inject_time.txt": b"1705354566",
    "re2ob_cartservice_cpu_1/metrics.parquet": b"m" * 300,
    "re2ob_cartservice_cpu_1/notes.png": b"never fetched",
    "re2ob_emailservice_mem_2/inject_time.txt": b"1705354999",
    "re2ob_emailservice_mem_2/logs.parquet": b"l" * 50,
    "re2ob_emailservice_mem_2/root_cause.txt": b"emailservice",  # a label file in the fetched suite
    "re2ss_carts_cpu_1/metrics.parquet": b"s" * 10,
    "re3ss_carts_f1_1/root_cause.txt": b"carts",
}


def _entry(path: str, data: bytes) -> dict[str, object]:
    git = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    entry: dict[str, object] = {"type": "file", "path": path, "size": len(data), "oid": git}
    if path.endswith(".parquet"):  # HF stores Parquet in LFS, small text files in git
        entry["lfs"] = {"oid": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return entry


class FakeHF:
    """Serves the tree in two pages (to exercise `Link: rel="next"`) and the file bodies."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.opened: list[str] = []
        items = [_entry(p, d) for p, d in sorted(files.items())]
        items.insert(0, {"type": "directory", "path": "re2ob_cartservice_cpu_1", "oid": "x", "size": 0})
        half = len(items) // 2
        self.page2 = fr.HF_HOST + "api/page2"
        self.pages = {fr.TREE_URL.format(repo=fr.HF_REPO, rev=fr.HF_REVISION): (items[:half], self.page2),
                      self.page2: (items[half:], None)}  # fmt: skip

    def get(self, url: str) -> tuple[bytes, str | None]:
        items, nxt = self.pages[url]
        return json.dumps(items).encode(), (f'<{nxt}>; rel="next"' if nxt else None)

    @contextmanager
    def open(self, url: str) -> Iterator[IO[bytes]]:
        path = url.removeprefix(fr.FILE_URL.format(repo=fr.HF_REPO, rev=fr.HF_REVISION, path=""))
        self.opened.append(path)
        yield io.BytesIO(self.files[path])


def _fetch(
    root: Path,
    hf: FakeHF,
    *,
    suite: str | None = None,
    source: FetchSource | None = None,
    cases: int | None = None,
) -> int:
    req = FetchRequest(name="rcaeval", data_root=root, suite=suite, source=source, cases=cases)
    return fr.fetch(req, transport=hf)


def test_plan_takes_allow_listed_files_of_the_suite(tmp_path: Path) -> None:
    files, chosen = fr.plan(fr.list_tree(FakeHF(FILES)), ("re2-ob",), 1)
    assert [f.path for f in files] == [
        "cases.parquet",
        "re2ob_cartservice_cpu_1/inject_time.txt",
        "re2ob_cartservice_cpu_1/metrics.parquet",
    ]
    assert list(chosen) == ["re2ob_cartservice_cpu_1"]


def test_fetch_writes_cases_index_and_lock(tmp_path: Path) -> None:
    hf = FakeHF(FILES)
    assert _fetch(tmp_path, hf, suite="re2-ob") == 0
    case = tmp_path / "rcaeval" / "hf" / "re2ob_cartservice_cpu_1"
    assert (case / "metrics.parquet").read_bytes() == FILES["re2ob_cartservice_cpu_1/metrics.parquet"]
    assert not (case / "notes.png").exists()
    assert (tmp_path / "rcaeval" / "answers" / "cases.parquet").is_file()
    assert not list(tmp_path.rglob("root_cause.txt"))
    index = read_index(tmp_path, "re2-ob")
    key = parse_case_dir(["re2ob_emailservice_mem_2"])
    assert key is not None
    assert index[key.case_id] == "rcaeval/hf/re2ob_emailservice_mem_2"
    assert len(index) == 2
    lock = json.loads((tmp_path / "rcaeval" / "fetch.lock.json").read_bytes())
    meta = lock["rcaeval/hf/re2ob_cartservice_cpu_1/metrics.parquet"]
    assert meta == {"bytes": 300, "sha256": hashlib.sha256(b"m" * 300).hexdigest()}


def test_refetch_skips_verified_files_and_is_byte_identical(tmp_path: Path) -> None:
    assert _fetch(tmp_path, FakeHF(FILES), suite="re2-ob") == 0
    snapshot = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    again = FakeHF(FILES)
    assert _fetch(tmp_path, again, suite="re2-ob") == 0
    assert again.opened == []
    assert {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()} == snapshot


def test_hash_mismatch_fails_and_leaves_no_file(tmp_path: Path) -> None:
    hf = FakeHF(FILES)
    hf.files["re2ob_cartservice_cpu_1/metrics.parquet"] = b"x" * 300  # same size, wrong bytes
    assert _fetch(tmp_path, hf, suite="re2-ob", cases=1) == 1
    case = tmp_path / "rcaeval" / "hf" / "re2ob_cartservice_cpu_1"
    assert sorted(p.name for p in case.iterdir()) == ["inject_time.txt"]


def test_usage_errors(tmp_path: Path) -> None:
    assert _fetch(tmp_path, FakeHF(FILES), suite="re4-ob") == 2
    assert _fetch(tmp_path, FakeHF(FILES), source="zenodo") == 2
    (tmp_path / ".git").mkdir()
    assert _fetch(tmp_path / "data", FakeHF(FILES)) == 2


def test_foreign_next_page_is_refused() -> None:
    hf = FakeHF(FILES)
    first = fr.TREE_URL.format(repo=fr.HF_REPO, rev=fr.HF_REVISION)
    hf.pages[first] = (hf.pages[first][0], "https://example.com/page2")
    with pytest.raises(fr.FetchError, match="outside"):
        fr.list_tree(hf)
