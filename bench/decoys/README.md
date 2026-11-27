# bench/decoys (`veyltrace_decoys`)

RCAEval-C decoy-change generator (task O-13, **Observe lane**). Spec:
[04-causync §3.7](../../docs/engines/04-causync.md); grid in [04 §5.2](../../docs/04-evaluation-protocol.md).
Use: `DecoySpec.from_protocol` → `generate` → `write_overlay` (the file for `events.overlay_path`,
O-09) and `decoy_changes_json` (the answer-key column), all in `veyltrace_decoys/rcaevalc.py`.

Part of the `veyltrace_bench` wheel (`decoys/veyltrace_decoys` in `bench/pyproject.toml`); the
runner calls it from `veyltrace_bench/decoy_runs.py`. The tests also reach it through `conftest.py`.
