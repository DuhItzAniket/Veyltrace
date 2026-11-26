"""Put bench/decoys on sys.path so its tests import `veyltrace_decoys` from the source tree, whether
or not the `veyltrace_bench` wheel (which now ships it) is installed (importlib mode adds nothing;
same approach as lab/tests/conftest.py)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
