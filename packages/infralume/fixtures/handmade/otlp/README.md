# Handmade OTLP/JSON requests

Synthetic, written by hand in the shape of a lab capture's `otlp/{traces,metrics,logs}.jsonl`
([05 §9](../../../../../docs/05-fault-lab-and-dataset.md)): one OTLP/JSON export request per line,
lowerCamelCase fields, hex ids, 64-bit integers as strings. Service and pod names imitate Online
Boutique; no captured data. `expected.json` holds, per file and line, the rows and scrub counts
`veyltrace_infralume.otlp` must return (01 §3.9); `tests/test_otlp.py` compares them.
