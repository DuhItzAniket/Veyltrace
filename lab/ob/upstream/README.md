# Vendored Online Boutique manifest

`kubernetes-manifests.yaml` is the Online Boutique v0.10.7 release manifest (Apache-2.0, © Google LLC), vendored unchanged. The kustomize overlay in `../overlay/` changes only what 05 §3.2 allows.

Vendor or refresh it with:

```sh
uv run python lab/up.py --vendor
```

This downloads `online_boutique.manifest_url` from `../pins.yaml`, writes `kubernetes-manifests.yaml` and `SHA256SUMS`, and prints the hash. `lab/up.py --profile ob` refuses to start when the file's hash does not match `SHA256SUMS`.
