# bench/stats (`veyltrace_stats`)

The statistics of [04 §8](../../docs/04-evaluation-protocol.md) (task O-14, **Observe lane**): `cluster.cluster_bootstrap`, `cluster.stratified_cluster_bootstrap` (pooled rows: clusters resampled within each system), `cluster.sign_flip_test`, `exact.mcnemar_exact`, `exact.holm`, `exact.clopper_pearson` (exact binomial interval for proportions without clusters: H2b, H2c, replay rates).
Shipped in the `veyltrace_bench` wheel (`stats/veyltrace_stats` in `bench/pyproject.toml`), as `decoys/` is.
