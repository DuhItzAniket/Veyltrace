"""textio: UTF-8/LF on every OS and atomic replacement with PermissionError retry."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from veyltrace_core import textio
from veyltrace_core.textio import (
    REPLACE_ATTEMPTS,
    AtomicTextWriter,
    atomic_replace,
    open_text,
    read_bytes,
    read_text,
    write_bytes,
    write_text,
)

TEXT = "a → b ≥ c § é\nline 2\n"


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if textio.TMP_INFIX in p.name)


def test_write_text_is_utf8_with_lf(tmp_path: Path) -> None:
    path = tmp_path / "card.md"
    write_text(path, TEXT)
    assert path.read_bytes() == TEXT.encode("utf-8")  # no CRLF on Windows, no cp1252
    assert read_text(path) == TEXT


def test_read_text_does_not_translate_newlines(tmp_path: Path) -> None:
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"a\r\nb\n")
    assert read_text(path) == "a\r\nb\n"
    assert read_bytes(path) == b"a\r\nb\n"


def test_read_text_is_strict_utf8(tmp_path: Path) -> None:
    path = tmp_path / "cp1252.txt"
    path.write_bytes("é".encode("cp1252"))
    with pytest.raises(UnicodeDecodeError):
        read_text(path)


def test_write_creates_parents_and_replaces(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "x.bin"
    write_bytes(path, b"one")
    write_bytes(path, memoryview(b"two"))
    assert path.read_bytes() == b"two"
    assert _leftovers(path.parent) == []


def test_write_without_mkdir_fails_for_missing_parent(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_bytes(tmp_path / "missing" / "x", b"x", mkdir=False)


def test_tmp_path_is_per_process(tmp_path: Path) -> None:
    # textio.tmp_path, not the pytest fixture of the same name
    assert textio.tmp_path(tmp_path / "slate.json") == tmp_path / f"slate.json.tmp-{os.getpid()}"


def test_replace_retries_permission_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_replace = os.replace
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky(src: str, dst: str) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "target is open in another process")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    path = tmp_path / "verdict.json"
    write_text(path, "{}\n")
    assert path.read_text(encoding="utf-8") == "{}\n"
    assert len(calls) == 3
    assert sleeps == [textio.REPLACE_FIRST_DELAY_S, textio.REPLACE_FIRST_DELAY_S * 2]
    assert _leftovers(tmp_path) == []


def test_replace_gives_up_and_keeps_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "verdict.json"
    path.write_bytes(b"old")
    calls: list[int] = []

    def locked(src: str, dst: str) -> None:
        calls.append(1)
        raise PermissionError(13, "locked")

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        write_bytes(path, b"new")
    assert len(calls) == REPLACE_ATTEMPTS
    assert path.read_bytes() == b"old"
    assert _leftovers(tmp_path) == []


def test_other_os_errors_are_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def broken(src: str, dst: str) -> None:
        calls.append(1)
        raise IsADirectoryError(21, "is a directory")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(IsADirectoryError):
        atomic_replace(tmp_path / "a", tmp_path / "b")
    assert len(calls) == 1


def test_failed_write_keeps_the_old_file(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_bytes(b"old")
    with pytest.raises(TypeError):
        write_bytes(path, "not bytes")  # pyright: ignore[reportArgumentType]  # deliberate misuse
    assert path.read_bytes() == b"old"
    assert _leftovers(tmp_path) == []


def test_atomic_text_writer_commit(tmp_path: Path) -> None:
    path = tmp_path / "agent_trace.jsonl"
    path.write_bytes(b"previous\n")
    writer = AtomicTextWriter(path)
    writer.write('{"seq":0}\n')
    writer.flush()
    assert path.read_bytes() == b"previous\n"  # readers see the old file until commit
    writer.write('{"seq":1,"s":"→"}\n')
    writer.commit()
    assert writer.closed
    assert path.read_bytes() == '{"seq":0}\n{"seq":1,"s":"→"}\n'.encode()
    assert _leftovers(tmp_path) == []
    with pytest.raises(ValueError, match="closed"):
        writer.write("late")


def test_atomic_text_writer_abort_and_context_manager(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    with AtomicTextWriter(path) as writer:
        writer.write("x\n")
    assert path.read_bytes() == b"x\n"

    with pytest.raises(RuntimeError), AtomicTextWriter(path) as writer:
        writer.write("partial\n")
        raise RuntimeError("engine failed")
    assert path.read_bytes() == b"x\n"
    assert _leftovers(tmp_path) == []

    writer = AtomicTextWriter(tmp_path / "never.jsonl")
    writer.abort()
    writer.abort()  # idempotent
    assert not (tmp_path / "never.jsonl").exists()
    assert _leftovers(tmp_path) == []


def test_open_text_uses_utf8_and_lf(tmp_path: Path) -> None:
    path = tmp_path / "stream.txt"
    with open_text(path, "w") as fh:
        fh.write("é\n")
    with open_text(path, "a") as fh:
        fh.write("→\n")
    assert path.read_bytes() == "é\n→\n".encode()
    with open_text(path) as fh:
        assert fh.read() == "é\n→\n"
