// Test harness: a fetch stub that serves the captured gateway responses (src/fixtures) by route,
// and a render helper that mounts the app routes at a URL (docs/06 §5.5).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { AppRoutes } from "../App";
import casesSynth from "../fixtures/cases-synth.json";
import datasets from "../fixtures/datasets.json";
import runsSynth from "../fixtures/runs-synth.json";
import confirmedAlert from "../fixtures/synth-confirmed/alert.json";
import confirmedCard from "../fixtures/synth-confirmed/card.json";
import confirmedEvidence from "../fixtures/synth-confirmed/evidence.json";
import confirmedStatus from "../fixtures/synth-confirmed/status.json";
import confirmedVerdict from "../fixtures/synth-confirmed/verdict.json";
import inconclusiveAlert from "../fixtures/synth-inconclusive/alert.json";
import inconclusiveCard from "../fixtures/synth-inconclusive/card.json";
import inconclusiveStatus from "../fixtures/synth-inconclusive/status.json";
import inconclusiveVerdict from "../fixtures/synth-inconclusive/verdict.json";
import noFaultAlert from "../fixtures/synth-no-fault/alert.json";
import noFaultCard from "../fixtures/synth-no-fault/card.json";
import noFaultStatus from "../fixtures/synth-no-fault/status.json";
import noFaultVerdict from "../fixtures/synth-no-fault/verdict.json";

export const CONFIRMED = confirmedStatus.run_id;
export const INCONCLUSIVE = inconclusiveStatus.run_id;
export const NO_FAULT = noFaultStatus.run_id;
export { confirmedEvidence, confirmedStatus, confirmedVerdict };

const runs: Record<string, Record<string, unknown>> = {
  [CONFIRMED]: { "": confirmedStatus, verdict: confirmedVerdict, card: confirmedCard, alert: confirmedAlert },
  [INCONCLUSIVE]: {
    "": inconclusiveStatus,
    verdict: inconclusiveVerdict,
    card: inconclusiveCard,
    alert: inconclusiveAlert,
  },
  [NO_FAULT]: { "": noFaultStatus, verdict: noFaultVerdict, card: noFaultCard, alert: noFaultAlert },
};

/** Paths (without /api/v1) whose response a test replaces, e.g. `/runs/<id>/verdict`. */
export type Overrides = Record<string, unknown>;

export interface Call {
  method: string;
  url: URL;
  body: string | null;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const notFound = () => json({ error: { code: "not_found", message: "no such route in the stub" } }, 404);

function evidencePage(url: URL): Response {
  const q = url.searchParams;
  const rows = confirmedEvidence.items.filter(
    (row) =>
      (q.get("candidate") ?? row.candidate) === row.candidate &&
      (q.get("kind") ?? row.kind) === row.kind &&
      (q.get("origin") ?? row.origin) === row.origin,
  );
  const limit = Number(q.get("limit") ?? "200");
  const offset = Number(q.get("offset") ?? "0");
  return json({ items: rows.slice(offset, offset + limit), total: rows.length, limit, offset });
}

function route(method: string, url: URL, overrides: Overrides): Response {
  const path = url.pathname.replace(/^\/api\/v1/, "");
  if (path in overrides) return json(overrides[path]);
  if (method === "POST" && path === "/runs") return json(confirmedStatus, 200);
  if (path === "/datasets") return json(datasets);
  if (path === "/cases" && url.searchParams.get("dataset") === "synth") return json(casesSynth);
  if (path === "/runs" && url.searchParams.get("dataset") === "synth") return json(runsSynth);
  const match = /^\/runs\/([0-9a-f]{16})(?:\/(.*))?$/.exec(path);
  if (match?.[1] === undefined) return notFound();
  const [, runId, rest = ""] = match;
  if (runId === CONFIRMED && rest === "evidence") return evidencePage(url);
  const atom = /^evidence\/(E[0-9a-f]{10})$/.exec(rest)?.[1];
  if (runId === CONFIRMED && atom !== undefined) {
    const row = confirmedEvidence.items.find((r) => r.atom_id === atom);
    return row === undefined ? notFound() : json(row);
  }
  const body = runs[runId]?.[rest];
  return body === undefined ? notFound() : json(body);
}

/** Replace `fetch` with the fixture gateway; returns the list of calls the app made. */
export function stubGateway(overrides: Overrides = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : input.toString());
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: typeof init?.body === "string" ? init.body : null });
    return Promise.resolve(route(method, url, overrides));
  });
  return calls;
}

export function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
