"""veyltrace_bench: the evaluation harness (Reason lane; Observe owns bench/decoys and bench/stats).

Spec: docs/04-evaluation-protocol.md. Engines never import this package or read files under
bench/ (02 §9 rule 3); answer keys are read only here.
"""

__version__ = "0.1.0"
# Algorithm revision stamped into outputs (e.g. `producer = "<engine>@<ALGO_VERSION>"`).
# Bump only when this package's outputs change, never for a release, so golden fixtures
# do not churn weekly (M0 lead decision 2026-11-06).
ALGO_VERSION = "0"
