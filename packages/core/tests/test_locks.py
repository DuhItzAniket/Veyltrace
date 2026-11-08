"""locks: exclusive OS-backed run-dir locks, same-process exclusion, dead-owner release."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from veyltrace_core.locks import LockHeld, PathLock, lock_path_for

#: Seconds to wait for the helper process (a priori, generous for a cold Windows laptop).
_HELPER_TIMEOUT_S = 60
_HOLD = """
import os, sys
from pathlib import Path
from veyltrace_core.locks import PathLock
lock = PathLock(Path(sys.argv[1]))
lock.acquire()
print("held", flush=True)
sys.stdin.readline()
os._exit(0)  # die without release(): only the kernel can free the lock
"""


def test_lock_sits_next_to_target_and_is_released(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "abc"
    with PathLock(target) as lock:
        assert lock.held
        assert lock.path == lock_path_for(target) == tmp_path / "runs" / "abc.lock"
        assert lock.path.read_bytes() == str(os.getpid()).encode("ascii")
        assert not target.exists()
    assert not lock.held
    assert not lock.path.exists()


def test_second_lock_in_the_same_process_is_refused(tmp_path: Path) -> None:
    """Gateway threads or nested execute calls must not share a run directory."""
    a = PathLock(tmp_path / "run")
    a.acquire()
    b = PathLock(tmp_path / "run")
    with pytest.raises(LockHeld, match="this process"):
        b.acquire()
    assert a.held and not b.held
    with pytest.raises(LockHeld, match="already locked"):
        a.acquire()
    a.release()
    with b:
        assert b.held and b.path.exists()
        a.release()  # a no-op: a no longer holds anything and must not remove b's file
        assert b.path.exists()
    assert not b.path.exists()


def test_leftover_lock_file_is_free(tmp_path: Path) -> None:
    """A lock file nobody holds (a killed owner, garbage or an empty file) is simply taken."""
    target = tmp_path / "run"
    for content in (b"not-a-pid", b"", str(os.getppid()).encode("ascii")):
        lock_path_for(target).write_bytes(content)
        with PathLock(target) as lock:
            assert lock.held


def test_other_process_blocks_until_it_dies(tmp_path: Path) -> None:
    target = tmp_path / "run"
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD, str(target)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == b"held"
        # the pid is the interpreter's, which on Windows venvs is a child of the launcher shim
        with pytest.raises(LockHeld, match=r"in use by process [0-9]+ "):
            PathLock(target).acquire()
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=_HELPER_TIMEOUT_S)
    with PathLock(target) as lock:  # the kernel released the dead owner's lock
        assert lock.held
