"""Synthetic cases synth-01…05 for CI, golden fixtures and harness tests (02 §6.1; 04 §2).

A six-service toy system (frontend, recommend, catalog, checkout, cart with two replicas, payment;
plus an external card gateway) with one fault per case: CPU hog (synth-01), network delay
(synth-02), exception burst (synth-03), change-induced regression (synth-04) and no fault
(synth-05). Generator variant `synth-05@silent` stops one cart replica's telemetry at the
injection time.

Modules: `layout` (system, timing and fault specs), `generate` (the telemetry), `adapter` (the
`veyltrace.adapters:synth` entry point), `truth` (answer keys and the normal window) and `fetch`
(the `veyltrace.fetchers:synth` entry point).

Ground truth lives here, so engines never import this package (AST ban in tests/test_isolation.py);
they see synth data only through Infralume and the run directory.
"""

from veyltrace_core.synth.adapter import CASE_KEYS, SynthAdapter, resolve_key
from veyltrace_core.synth.generate import SynthTelemetry, generate

__all__ = ["CASE_KEYS", "SynthAdapter", "SynthTelemetry", "generate", "resolve_key"]
