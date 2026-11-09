"""Run lab commands, or only print them under ``--dry-run`` (05 §8.1: a dry run touches no cluster)."""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TextIO


class CommandError(RuntimeError):
    """A lab command exited non-zero."""

    def __init__(self, line: str, code: int, stderr: str) -> None:
        super().__init__(f"{line!r} exited {code}: {stderr.strip()[-2000:]}")
        self.code = code


@dataclass
class Runner:
    """Executes argv lists, or prints them prefixed with ``+`` when ``dry_run`` is set.

    Every command, wait and HTTP probe goes through here, so a dry run is exactly the list of what a
    live run would do, and tests can assert on ``log``.
    """

    dry_run: bool
    out: TextIO = field(default_factory=lambda: sys.stdout)
    log: list[str] = field(default_factory=list[str])

    def _note(self, line: str) -> None:
        self.log.append(line)
        if self.dry_run:
            print(f"+ {line}", file=self.out)

    def run(self, argv: Sequence[str], *, stdin: str | None = None, check: bool = True) -> str:
        """Run ``argv`` and return its stdout ("" in a dry run)."""
        line = shlex.join(argv) + (" <<stdin" if stdin is not None else "")
        self._note(line)
        if self.dry_run:
            return ""
        proc = subprocess.run(
            list(argv), input=stdin, capture_output=True, text=True, encoding="utf-8", check=False
        )
        if check and proc.returncode != 0:
            raise CommandError(line, proc.returncode, proc.stderr)
        return proc.stdout

    def sleep(self, seconds: float, reason: str) -> None:
        self._note(f"sleep {seconds:g}  # {reason}")
        if not self.dry_run:
            time.sleep(seconds)

    def http_ok(self, url: str, timeout_s: float = 10.0) -> bool:
        """True if ``url`` answers HTTP 2xx (always True in a dry run)."""
        self._note(f"GET {url}")
        if self.dry_run:
            return True
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError):
            return False

    def time_ns(self) -> int:
        """Host wall clock in ns. Lab code may read the clock; analysis code may not (AGENTS §4.4)."""
        return time.time_ns()
