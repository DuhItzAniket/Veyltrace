"""`openapi.json` (06 §3.5): the committed document equals a fresh export and lists every route."""

from __future__ import annotations

import json

from veyltrace_core.testing import repo_root
from veyltrace_gateway.export_openapi import OPENAPI_PATH, export

CONFIG = repo_root() / "config"
#: The routes of 06 §3.2 that X-04 builds and the live routes of 06 §3.4 that X-10 builds (the
#: live series and event stream are cut to v1.1, #227).
ROUTES = (
    "/health", "/datasets", "/cases", "/cases/{dataset}/{case_id}", "/runs", "/runs/{run_id}",
    "/runs/{run_id}/events", "/runs/{run_id}/alert", "/runs/{run_id}/slate", "/runs/{run_id}/proposals",
    "/runs/{run_id}/agent-trace", "/runs/{run_id}/verdict", "/runs/{run_id}/card", "/runs/{run_id}/card.md",
    "/runs/{run_id}/receipt", "/runs/{run_id}/run-manifest", "/runs/{run_id}/evidence",
    "/runs/{run_id}/evidence/{atom_id}", "/runs/{run_id}/graph", "/runs/{run_id}/series",
    "/runs/{run_id}/onsets", "/runs/{run_id}/changes", "/runs/{run_id}/replay",
    "/live/status", "/live/snapshot", "/live/diagnose",
)  # fmt: skip


def test_committed_openapi_is_a_fresh_export() -> None:
    committed = (repo_root() / OPENAPI_PATH).read_bytes()
    assert committed == export(CONFIG), "run `uv run python -m veyltrace_gateway.export_openapi`"


def test_openapi_lists_every_route_and_reuses_contract_schemas() -> None:
    document = json.loads(export(CONFIG))
    assert sorted(document["paths"]) == sorted(f"/api/v1{r}" for r in ROUTES)
    schemas = document["components"]["schemas"]
    assert {"Verdict", "EvidenceRow", "CaseManifest", "RunStatus", "ErrorBody"} <= set(schemas)
