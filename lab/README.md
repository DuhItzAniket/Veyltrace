# Veyltrace lab

A fault-injection testbed that fits one 16 GB Windows laptop (Docker Desktop + WSL2), used for the live demo and to collect the VeylLab dataset.

- Profiles: `ob` (Online Boutique v0.10.7 on kind, Chaos Mesh 2.8.7, OTel Collector contrib v0.164.0) and `otel` (OpenTelemetry Demo 3.1.0 on Compose). Never both at once.
- Fault catalog F01–F16: CPU, memory, disk, network delay and loss, pod kill, container restart, pod failure, error injection, exceptions via flags, config regression, bad deploy, dependency slowdown, no-fault, multi-fault, benign noise; decoy changes.
- Per case: reset, 3 min warm-up, 10 min baseline, 10 min fault, 2 min recovery (≈ 25 min); kept only if user-facing latency or errors moved.
- Spec and setup (`.wslconfig`, memory budget, capture format, release plan): [docs/05-fault-lab-and-dataset.md](../docs/05-fault-lab-and-dataset.md)

```sh
uv run python lab/up.py --profile ob
uv run python lab/campaign.py --plan lab/plans/<plan>.yaml --dry-run
uv run python lab/package.py --dataset veyllab-ob --captures lab/captures/<capture_id>
```

Captures and answer keys stay in `lab/captures/` (git-ignored).
