"""The bench runner's child process (#68): one case with one method in its own interpreter, so the
runner can kill a hung run at `resources.timeout_s` (04 §9: a timeout is a miss) and record the
run's peak resident set size (03 §13.2 `peak_rss_mb`, 04 §6 "Cost").

`python -m veyltrace_bench.child REQUEST RESULT`. REQUEST is a JSON object {dataset, case_id,
ai_mode, overrides, runs_root}; the child resolves the config from it exactly as the in-process
runner does (`resolve_config(overrides, dataset, ai_mode)`), so the run id, and every output, are
those of an in-process run. RESULT gets {"summary": pipeline.summary_dict, "wall_ms",
"peak_rss_mb"}, or {"error": {"type", "detail"}} when the run raised. Both files are transient IPC,
never artefacts. The child measures its own peak, because on Windows a venv's python.exe is a
launcher whose own memory is not the run's.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, cast

from veyltrace_core import textio
from veyltrace_core.config import resolve_config
from veyltrace_core.ids import AIMode
from veyltrace_core.pipeline import run_case, summary_dict

MIB = 1024 * 1024  # 03 §13.2 "MB" read as MiB, the unit ps, top and Task Manager report (a priori)
KIB = 1024  # Linux reports ru_maxrss in KiB (getrusage(2)); macOS in bytes
MS_PER_S = 1000.0


def peak_rss_mb() -> float:
    """This process's peak resident set size so far, in MiB (Windows: the peak working set)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS (psapi.h)
            _fields_ = [  # ctypes reads this class attribute by name
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        current = kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        info = kernel32.K32GetProcessMemoryInfo
        info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        info.restype = wintypes.BOOL
        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        if not info(current(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.PeakWorkingSetSize) / MIB
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / MIB if sys.platform == "darwin" else peak * KIB / MIB


def main(argv: list[str]) -> int:
    """Run the requested case and write RESULT; 0 when RESULT holds a summary, 1 on an error."""
    request_path, result_path = (Path(a) for a in argv)
    request = cast("dict[str, Any]", json.loads(textio.read_text(request_path)))
    try:
        ai_mode = cast("AIMode", request["ai_mode"])
        cfg = resolve_config(request["overrides"], dataset=request["dataset"], ai_mode=ai_mode)
        start = time.perf_counter()
        summary = run_case(
            request["dataset"], request["case_id"], ai_mode, config=cfg, runs_root=Path(request["runs_root"])
        )
        wall_ms = (time.perf_counter() - start) * MS_PER_S
    except Exception as exc:  # any error: the parent re-raises it, as an in-process run would
        traceback.print_exc()
        result: dict[str, object] = {"error": {"type": type(exc).__name__, "detail": str(exc)}}
        textio.write_bytes(result_path, json.dumps(result).encode())
        return 1
    result = {"summary": summary_dict(summary), "wall_ms": wall_ms, "peak_rss_mb": peak_rss_mb()}
    textio.write_bytes(result_path, json.dumps(result).encode())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
