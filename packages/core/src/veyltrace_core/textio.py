"""File I/O helpers: UTF-8 with LF only, and atomic replacement of whole files.

Why they exist (M0 lead decision 2026-11-06; critic gaps "text handling", "concurrent runs"):

- `open()` without an encoding decodes cp1252 on the team's Windows laptops and UTF-8 on Linux CI,
  so config values, prompts and card text containing "→", "≥" or "§" would hash differently per OS.
  Every helper here uses encoding="utf-8" and newline="\\n" (no newline translation either way:
  text read is exactly the file's bytes decoded, text written is exactly its UTF-8 encoding).
- Readers in another process (a bench worker, the gateway) must never see a half-written file.
  Writers write `<path>.tmp-<pid>`, flush it to disk, then `os.replace` it over the target, which
  is atomic on POSIX and on NTFS. On Windows `os.replace` raises PermissionError while another
  process holds the target open (or a virus scanner briefly does), so the replace is retried with
  backoff. The retry runs on every OS so CI exercises the same code path.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Buffer
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, TextIO

__all__ = [
    "ENCODING",
    "NEWLINE",
    "REPLACE_ATTEMPTS",
    "REPLACE_FIRST_DELAY_S",
    "TMP_INFIX",
    "AtomicTextWriter",
    "StrPath",
    "atomic_replace",
    "open_text",
    "read_bytes",
    "read_text",
    "tmp_path",
    "write_bytes",
    "write_text",
]

type StrPath = str | os.PathLike[str]

ENCODING = "utf-8"
NEWLINE = "\n"
#: Temp files are `<name>.tmp-<pid>` next to the target, so os.replace never crosses a filesystem
#: (core_api_spec critic fix: io.write* and JsonlWriter write <path>.tmp-<pid>, then os.replace).
TMP_INFIX = ".tmp-"
# PermissionError retry on replace: 8 attempts, delay doubling from 10 ms, about 2.5 s in total.
# A priori: long enough for a scanner or Explorer preview to release a file, short enough that a
# genuine permission error still fails fast.
REPLACE_ATTEMPTS = 8
REPLACE_FIRST_DELAY_S = 0.01


def tmp_path(path: StrPath) -> Path:
    """Return the temp path an atomic write of `path` uses in this process: `<path>.tmp-<pid>`."""
    target = Path(path)
    return target.with_name(f"{target.name}{TMP_INFIX}{os.getpid()}")


def atomic_replace(src: StrPath, dst: StrPath) -> None:
    """os.replace(src, dst), retried with backoff while it raises PermissionError (see module doc)."""
    delay = REPLACE_FIRST_DELAY_S
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(delay)  # waiting only; never read as a value, so determinism is unaffected
            delay *= 2
        else:
            return


def read_bytes(path: StrPath) -> bytes:
    """Return a file's bytes."""
    return Path(path).read_bytes()


def read_text(path: StrPath) -> str:
    """Return a file's text: strict UTF-8, no newline translation (CRLF stays CRLF)."""
    return read_bytes(path).decode(ENCODING)


def _discard(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def write_bytes(path: StrPath, data: Buffer, *, mkdir: bool = True) -> None:
    """Atomically replace `path` with `data` (temp file, fsync, os.replace).

    Parent directories are created unless `mkdir` is False. On any failure the temp file is
    removed and the target is left as it was.
    """
    target = Path(path)
    if mkdir:
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path(target)
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        atomic_replace(tmp, target)
    except BaseException:
        _discard(tmp)
        raise


def write_text(path: StrPath, text: str, *, mkdir: bool = True) -> None:
    """Atomically replace `path` with `text` encoded as UTF-8; "\\n" is written as LF on every OS."""
    write_bytes(path, text.encode(ENCODING), mkdir=mkdir)


def open_text(path: StrPath, mode: Literal["r", "w", "a", "x"] = "r") -> TextIO:
    """Open a text file for streaming with UTF-8 and LF (not atomic; see AtomicTextWriter)."""
    return Path(path).open(mode, encoding=ENCODING, newline=NEWLINE)


class AtomicTextWriter:
    """Streams text to `<path>.tmp-<pid>` and publishes it with commit(); abort() discards it.

    For writers that append over time (core.io.JsonlWriter for agent_trace.jsonl): readers see
    either the previous file or the complete new one. As a context manager it commits on normal
    exit and aborts on an exception.
    """

    def __init__(self, path: StrPath, *, mkdir: bool = True) -> None:
        self.path = Path(path)
        if mkdir:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tmp_path(self.path)
        self._fh: TextIO | None = self.tmp.open("w", encoding=ENCODING, newline=NEWLINE)

    @property
    def closed(self) -> bool:
        """True after commit() or abort()."""
        return self._fh is None

    def _stream(self) -> TextIO:
        if self._fh is None:
            msg = f"atomic writer for {self.path} is already closed"
            raise ValueError(msg)
        return self._fh

    def write(self, text: str) -> None:
        """Append `text` to the temp file."""
        self._stream().write(text)

    def flush(self) -> None:
        """Flush buffered text to the temp file (the target is unchanged until commit)."""
        self._stream().flush()

    def commit(self) -> None:
        """Flush, fsync and close the temp file, then atomically replace the target with it."""
        fh = self._stream()
        try:
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()
            self._fh = None
            atomic_replace(self.tmp, self.path)
        except BaseException:
            self.abort()
            raise

    def abort(self) -> None:
        """Close and delete the temp file; the target is left as it was. Safe to call twice."""
        fh, self._fh = self._fh, None
        if fh is not None:
            with contextlib.suppress(OSError):
                fh.close()
        _discard(self.tmp)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            if not self.closed:
                self.commit()
        else:
            self.abort()
