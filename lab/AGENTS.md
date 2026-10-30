# AGENTS.md — lab/

Adds to the root [AGENTS.md](../AGENTS.md) and never overrides it.

- **Lane:** Explain. Edit only Explain paths (root AGENTS.md §2).
- **Purpose:** the laptop fault lab (Online Boutique v0.10.7 on kind + Chaos Mesh 2.8.7; OpenTelemetry Demo 3.1.0 on Compose as the alternate profile), the fault catalog, campaigns, the capture packager and the VeylLab dataset release.
- **Spec:** [docs/05-fault-lab-and-dataset.md](../docs/05-fault-lab-and-dataset.md) · master [02 §8, §9, §10](../docs/02-architecture.md) · contracts [03 §13.1](../docs/03-contracts.md).
- **Inputs:** plan files, pinned manifests and Helm/Compose files, the running lab. **Outputs:** raw captures and answer keys under `lab/captures/` (git-ignored); packaged captures under `${VEYLTRACE_DATA}/veyllab/`; release bundles.

## Package rules

1. `lab/` is not a uv workspace member. Scripts drive `kind`, `kubectl`, `helm` and `docker` as subprocesses; the packager runs from the repo root with `uv run python lab/package.py` after `uv sync --all-packages`.
2. Answer keys are written only to `lab/captures/answer_keys/`, never into a capture or packaged folder. Only lab and bench code read them; engines never read `lab/`.
3. Scrub before anything leaves `lab/captures/`: drop `feature_flag.*`, flagd and chaos-mesh telemetry and `chaos-mesh.org/*` labels; hash flag keys; use neutral image tags and env names. The deny-list post-scan must pass.
4. Every injected parameter, tool version and seed goes into `injection_json`; pin every image by digest.
5. Never run the `ob` and `otel` profiles at the same time (`lab/up.py` refuses).
6. Keep a case only if the validation rule (05 §8.2) passes; log every attempt with its reason.
7. Tests use small synthetic fixtures under `lab/tests/fixtures/` only.

## Commands

| Task | Command |
|---|---|
| Check | `uv run python scripts/check.py --package lab` (lints and tests `lab/` by path; [08 §3](../docs/08-collaboration-and-git.md)) |
| Start a profile | `uv run python lab/up.py --profile ob` |
| Dry-run a campaign | `uv run python lab/campaign.py --plan lab/plans/<plan>.yaml --dry-run` |
| Package captures | `uv run python lab/package.py --dataset veyllab-ob --captures lab/captures/<id>` |

## Never

- Never commit captures, answer keys, packaged data, release bundles or images.
- Never put a fault, target, flag or injection name into a packaged file, folder name, image tag or env var name.
- Never inject faults outside the local lab cluster or Compose project.
- Never let an answer key, injection time or chaos artifact reach a path an engine reads, except the published oracle hint `oracle_alert.json` (05 §9).
