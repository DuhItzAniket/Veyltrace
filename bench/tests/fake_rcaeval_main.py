"""A stand-in for RCAEval's main.py in bench tests (R-05, #15), run by this interpreter.

Fails if output/ survived from an earlier run, ranks each exported case's columns A→Z into
RCAEval's result file (`output/results/<label>_<case>.json`, `{"0": ranks}`), echoes its argv and
prints a report line naming the number of cases. Never imported; copied as main.py by the tests.
"""

import glob
import json
import os
import sys
from pathlib import Path

assert not os.path.exists("output"), "stale output/"
os.makedirs("output/results")
paths = sorted(glob.glob("data/**/simple_metrics.csv", recursive=True))
for p in paths:
    case_dir = Path(p).parent
    header = Path(p).read_text(encoding="utf-8").splitlines()[0].split(",")
    int((case_dir / "inject_time.txt").read_text(encoding="utf-8"))
    ranks = sorted(c for c in header if c != "time")
    out = Path("output/results") / f"{case_dir.parent.name}_{case_dir.name}.json"
    out.write_text(json.dumps({"0": ranks}), encoding="utf-8")
print("argv", json.dumps(sys.argv[1:]))
print("Avg speed:", len(paths))
