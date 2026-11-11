"""lab/ is not a workspace package: put it on sys.path so tests import `vlab`, `up` and `campaign`,
and put lab/tests there too so a test can reuse another's fixtures builders (importlib mode)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parent, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
