"""veyltrace_core: the shared kernel of Veyltrace v2 (Reason lane).

Canonical JSON, hashing, IDs, rng, config, contract I/O, the run context, plugins, the pipeline,
the alert step, the CLI, test helpers and the synth generator (packages/core/README.md).
This module stays import-free, and the version is a constant rather than an importlib.metadata
lookup, because engines import core and importlib.metadata pulls networking modules into
sys.modules (isolation test, 02 §9).
"""

__version__ = "0.1.0"
