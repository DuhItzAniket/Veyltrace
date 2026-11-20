"""bench/stats is not inside the `veyltrace_bench` wheel: put it on sys.path so its tests import
`veyltrace_stats` (importlib mode adds nothing; same approach as bench/decoys/conftest.py)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
