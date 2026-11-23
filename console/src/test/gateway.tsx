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
import confirmedStatus from "../fixtures/synth-confirmed/status.json";

export const CONFIRMED = confirmedStatus.run_id;
export { confirmedStatus };

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

function route(method: string, url: URL, overrides: Overrides): Response {
  const path = url.pathname.replace(/^\/api\/v1/, "");
  if (path in overrides) return json(overrides[path]);
  if (method === "POST" && path === "/runs") return json(confirmedStatus, 200);
  if (path === "/datasets") return json(datasets);
  if (path === "/cases" && url.searchParams.get("dataset") === "synth") return json(casesSynth);
  if (path === "/runs" && url.searchParams.get("dataset") === "synth") return json(runsSynth);
  if (path === `/runs/${CONFIRMED}`) return json(confirmedStatus);
  return notFound();
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
