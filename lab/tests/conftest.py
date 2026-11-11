"""lab/ is not a workspace package: put it on sys.path so tests import `vlab`, `up` and `campaign`."""

import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
