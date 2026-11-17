# bench/decoys (`veyltrace_decoys`)

RCAEval-C decoy-change generator (task O-13, **Observe lane**). Spec:
[04-causync §3.7](../../docs/engines/04-causync.md); grid in [04 §5.2](../../docs/04-evaluation-protocol.md).
Use: `DecoySpec.from_protocol` → `generate` → `write_overlay` (the file for `events.overlay_path`,
O-09) and `decoy_changes_json` (the answer-key column), all in `veyltrace_decoys/rcaevalc.py`.

Not in the `veyltrace_bench` wheel yet (tests reach it through `conftest.py`): the runner needs
`decoys/veyltrace_decoys` added to the wheel packages in `bench/pyproject.toml` (Reason lane).
