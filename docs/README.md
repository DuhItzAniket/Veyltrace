# Docs index

> Owner: lead. Only the lead edits this file; lanes edit their own engine specs.
> Precedence when docs disagree: [02-architecture](02-architecture.md) > [03-contracts](03-contracts.md) > everything else. Fix the lower doc or open an ADR.

## Reading order

| Step | Everyone | Observe adds | Reason adds | Explain adds |
|---|---|---|---|---|
| 1 | [../AGENTS.md](../AGENTS.md) | | | |
| 2 | [01 Vision and requirements](01-vision-and-requirements.md) | | | |
| 3 | [02 Architecture](02-architecture.md) (master spec) | | | |
| 4 | [03 Contracts](03-contracts.md) | §2–6 in depth | §7–10, §13 in depth | §9–12 in depth |
| 5 | [07 Roadmap](07-roadmap.md) | | | |
| 6 | [08 Collaboration and git](08-collaboration-and-git.md) | | | |
| 7 | [09 AI agent playbook](09-ai-agent-playbook.md) | | | |
| 8 | [10 SDLC and quality](10-sdlc-and-quality.md) | | | |
| 9 | | engines [01](engines/01-infralume.md)–[05](engines/05-causalith.md) | engines [06](engines/06-faultloom.md), [07](engines/07-causatrix.md), [09](engines/09-causentra.md); [04 Evaluation](04-evaluation-protocol.md) | engines [08](engines/08-relentra.md), [10](engines/10-causivra.md); [05 Fault lab](05-fault-lab-and-dataset.md); [06 Gateway and console](06-gateway-and-console.md) |

## All documents

| Doc | What it decides | Owner |
|---|---|---|
| [01-vision-and-requirements](01-vision-and-requirements.md) | problem, users, goals, requirements, success criteria | lead |
| [02-architecture](02-architecture.md) | engines, pipeline, algorithms, trust model, stack (**master**) | lead |
| [03-contracts](03-contracts.md) | every artifact's fields and vocabularies | lead (file) / producers (semantics) |
| [04-evaluation-protocol](04-evaluation-protocol.md) | RQs, datasets, splits, metrics, baselines, statistics, experiment matrix | Reason |
| [05-fault-lab-and-dataset](05-fault-lab-and-dataset.md) | laptop testbed, fault catalog, VeylLab dataset | Explain |
| [06-gateway-and-console](06-gateway-and-console.md) | HTTP API, MCP tools, UI | Explain |
| [07-roadmap](07-roadmap.md) | phases, milestones, tasks, cut list | lead |
| [08-collaboration-and-git](08-collaboration-and-git.md) | lanes, ownership, branching, contract changes, rhythm | lead |
| [09-ai-agent-playbook](09-ai-agent-playbook.md) | per-tool setup, session protocol, prompt templates | lead |
| [10-sdlc-and-quality](10-sdlc-and-quality.md) | Definition of Done, tests, CI, releases, tracking | lead |
| [11-research-paper-plan](11-research-paper-plan.md) | contributions, related work, venues, artifact checklist | lead |
| [12-risks](12-risks.md) | risk register | lead |
| [13-glossary](13-glossary.md) | terms | lead |
| [engines/](engines/) | one spec per engine (01–10, pipeline order) | engine's lane |
| [adr/](adr/) | architecture decision records | author |
| [team/](team/) | one file per person: laptop, agent, availability | that person |

## Research

- [v2 research report](../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md): state of the art, benchmarks, design evidence (Oct 2026).
- [v2 research notes](../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/): six source-cited notes behind the report.
