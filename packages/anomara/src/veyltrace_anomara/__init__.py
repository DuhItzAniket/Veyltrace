"""Anomara: engine 3 of Veyltrace v2 (Observe lane, pipeline step 3).

Purpose: anomalies and incident onsets.
Spec: docs/engines/03-anomara.md.
This module stays import-free so that importing the package never pulls in heavy or
network-capable modules (isolation test, 02 §9).
"""

__version__ = "0.1.0"
# Algorithm revision stamped into outputs (e.g. `producer = "<engine>@<ALGO_VERSION>"`).
# Bump only when this package's outputs change, never for a release, so golden fixtures
# do not churn weekly (M0 lead decision 2026-11-06).
ALGO_VERSION = "0"
