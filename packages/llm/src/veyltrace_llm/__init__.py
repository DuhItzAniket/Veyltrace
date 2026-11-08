"""veyltrace_llm: Explain lane support package of Veyltrace v2.

Purpose: LLM providers, constrained calls and the cassette.
Spec: docs/engines/08-relentra.md (§3.8, §5).
This module stays import-free so that importing the package never pulls in heavy or
network-capable modules (isolation test, 02 §9).
"""

__version__ = "0.1.0"
# Algorithm revision stamped into outputs (e.g. `producer = "<engine>@<ALGO_VERSION>"`).
# Bump only when this package's outputs change, never for a release, so golden fixtures
# do not churn weekly (M0 lead decision 2026-11-06).
ALGO_VERSION = "0"
