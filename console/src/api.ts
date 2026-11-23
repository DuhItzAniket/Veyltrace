// Gateway API client (docs/06 §3.2). Responses are typed with the generated API types only
// (contracts/generated/ts/api). That module has the OpenAPI components but no `paths` map yet, so
// openapi-fetch cannot type the routes; this thin wrapper names each route instead until it does.
import type {
  Alert,
  Card,
  CasePage,
  DatasetSummary,
  ErrorBody,
  EvidencePage,
  EvidenceRow,
  RunRequest,
  RunStatus,
  Verdict,
} from "../../contracts/generated/ts/api";

// Dev: the Vite server talks to the gateway on loopback (CORS allows 127.0.0.1:5173, 06 §3.6);
// the built console is served by the gateway itself, so it uses the same origin.
const ORIGIN = import.meta.env.VITE_GATEWAY_ORIGIN ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");
const BASE = `${ORIGIN}/api/v1`;

/** A non-2xx gateway response, carrying the `{error: {code, message}}` body (06 §3.1). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | undefined>;

async function call<T>(path: string, query: Query = {}, init?: RequestInit): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  const response = await fetch(`${BASE}${path}${qs === "" ? "" : `?${qs}`}`, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ErrorBody | null;
    throw new ApiError(
      response.status,
      body?.error.code ?? "http_error",
      body?.error.message ?? `HTTP ${String(response.status)}`,
    );
  }
  return (await response.json()) as T;
}

export interface EvidenceQuery {
  candidate?: string | undefined;
  kind?: string | undefined;
  origin?: string | undefined;
  limit: number;
  offset: number;
}

export const api = {
  datasets: () => call<DatasetSummary[]>("/datasets"),
  cases: (dataset: string, limit: number, offset: number) =>
    call<CasePage>("/cases", { dataset, limit, offset }),
  runs: (dataset: string) => call<RunStatus[]>("/runs", { dataset }),
  run: (runId: string) => call<RunStatus>(`/runs/${runId}`),
  startRun: (request: RunRequest) =>
    call<RunStatus>(
      "/runs",
      {},
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      },
    ),
  verdict: (runId: string) => call<Verdict>(`/runs/${runId}/verdict`),
  card: (runId: string) => call<Card>(`/runs/${runId}/card`),
  alert: (runId: string) => call<Alert>(`/runs/${runId}/alert`),
  evidence: (runId: string, q: EvidenceQuery) => call<EvidencePage>(`/runs/${runId}/evidence`, { ...q }),
  atom: (runId: string, atomId: string) => call<EvidenceRow>(`/runs/${runId}/evidence/${atomId}`),
};
