"""Exclusive lock files for run directories and cache keys.

Two processes (bench workers, the gateway job runner) or two threads of one process can target
the same run id or Infralume cache key. Clearing an incomplete run directory that another writer
is still filling would tear its outputs, so the owner holds an operating-system lock on
`<target>.lock` (M0 lead decision 2026-11-06, critic gap "Concurrent runs are unsafe").

Why an OS lock (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) rather than "create the
file, write a pid, take over dead pids": the kernel releases the lock when its owner dies, so a
killed bench subprocess never leaves a lock that needs a stale-pid takeover, and there is no
read-check-unlink race between two takers, no window in which a freshly created, still empty file
looks stale, and no pid-reuse ambiguity. Both lock kinds are per open file, so a second PathLock
in the same process is refused too. A busy lock makes the caller raise instead of waiting.

The file holds the owner's pid only to make the LockHeld message useful. On release the owner
removes the file while still holding the lock (POSIX), so a process that opened the old file
detects that the path now names another file and retries; on Windows an open file cannot be
removed, so it is removed after unlocking when nobody else has it open, and otherwise left for
the next owner. The lock file sits next to the target, never in it, so it is never mistaken for
an output.

Engine-safe: stdlib only.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from veyltrace_core.errors import UsageError

__all__ = ["LOCK_SUFFIX", "LockHeld", "PathLock", "lock_path_for"]

LOCK_SUFFIX: Final = ".lock"
#: How many times acquire() retries when the lock file was replaced while it was being locked.
_REPLACED_ATTEMPTS: Final = 3
#: Byte offset of the one-byte region msvcrt.locking locks: past any pid text, so a reader can
#: still read the pid (Windows byte-range locks are mandatory for reads). A priori.
_WINDOWS_LOCK_OFFSET: Final = 1 << 30
_BUSY_ERRNOS: Final = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EWOULDBLOCK})


class LockHeld(UsageError):
    """Another process, or another PathLock of this process, holds the lock (exit 2: the caller
    started a conflicting run)."""


def lock_path_for(target: Path) -> Path:
    """`<target>.lock`, next to the target directory or file."""
    return target.with_name(target.name + LOCK_SUFFIX)


def _try_lock(fd: int) -> bool:
    """Take the exclusive OS lock on `fd` without waiting; False if someone else holds it."""
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _BUSY_ERRNOS:
            return False
        raise
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _names_file(path: Path, fd: int) -> bool:
    """True if `path` still names the file open as `fd` (it was not removed and recreated)."""
    try:
        return os.path.samestat(os.fstat(fd), os.stat(path))
    except FileNotFoundError:
        return False


def _owner(path: Path) -> str:
    try:
        text = path.read_bytes()[:32].decode("ascii", errors="replace").strip()
    except OSError:
        return "?"
    return text if text.isdigit() else "?"


class PathLock:
    """An exclusive lock on `target`, held through `<target>.lock`. Use as a context manager.

    Not re-entrant: a second PathLock on the same target raises LockHeld even in the owning
    process, so two threads of one gateway never share a run directory.
    """

    def __init__(self, target: Path) -> None:
        self.target = Path(target)
        self.path = lock_path_for(self.target)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        """True between a successful acquire() and release()."""
        return self._fd is not None

    def acquire(self) -> None:
        """Take the lock or raise LockHeld (a lock left by a dead process is free again)."""
        if self._fd is not None:
            msg = f"{self.target} is already locked by this PathLock"
            raise LockHeld(msg)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        for _ in range(_REPLACED_ATTEMPTS):
            fd = os.open(self.path, flags, 0o644)
            try:
                locked = _try_lock(fd)
            except BaseException:
                os.close(fd)
                raise
            if not locked:
                os.close(fd)
                owner = _owner(self.path)
                who = "this process" if owner == str(os.getpid()) else f"process {owner}"
                msg = f"{self.target} is in use by {who} (lock file {self.path})"
                raise LockHeld(msg)
            if not _names_file(self.path, fd):  # the previous owner removed it meanwhile
                _unlock(fd)
                os.close(fd)
                continue
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, str(os.getpid()).encode("ascii"))
            self._fd = fd
            return
        msg = f"the lock file {self.path} kept being replaced; giving up"
        raise LockHeld(msg)

    def release(self) -> None:
        """Release the lock and remove the lock file if this object holds it."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        removed = True
        try:
            self.path.unlink()  # POSIX: while still locked, so no one else can hold this file
        except OSError:
            removed = False  # Windows: an open file cannot be removed; retried below
        try:
            _unlock(fd)
        finally:
            os.close(fd)
        if not removed:
            # another process may have it open (it will lock it next): then leave it
            with contextlib.suppress(OSError):
                self.path.unlink()

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
