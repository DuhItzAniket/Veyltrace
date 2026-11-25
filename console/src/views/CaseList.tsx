// Case list (docs/06 §5.2 "/"): datasets, cases with system, sources and run states, and a Run
// button with the AI mode. Dataset and page live in the URL so the view can be shared.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { CaseSummary, RunRequest, RunStatus } from "../../../contracts/generated/ts/api";
import { api } from "../api";
import { Failure, Pager } from "./ui";

const PAGE = 50; // cases per page (a priori: one screen of rows)
const AI_MODES: RunRequest["ai_mode"][] = ["off", "record", "replay"];
const UNKNOWN = "unknown until the first run";

function sourcesText(c: CaseSummary): string {
  if (c.sources === null) return UNKNOWN;
  const present = Object.entries(c.sources).filter(([, on]) => on);
  return present.length === 0 ? "none" : present.map(([name]) => name).join(", ");
}

/** The case's finished runs and every queued, running or failed run the gateway reports for it
 * (06 §5.2: the latest run status), sorted by run id. */
function runIds(c: CaseSummary, states: Map<string, RunStatus>): string[] {
  const reported = [...states.values()].filter((r) => r.case_id === c.case_id).map((r) => r.run_id);
  return [...new Set([...c.runs, ...reported])].sort();
}

function CaseRow({ c, states }: { c: CaseSummary; states: Map<string, RunStatus> }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<RunRequest["ai_mode"]>("off");
  const start = useMutation({
    mutationFn: () => api.startRun({ dataset: c.dataset, case_id: c.case_id, ai_mode: mode }),
    onSuccess: (status) => void navigate(`/runs/${status.run_id}`),
  });
  const ids = runIds(c, states);
  return (
    <tr>
      <th scope="row">
        <code>{c.case_id}</code>
      </th>
      <td>{c.system ?? UNKNOWN}</td>
      <td>{sourcesText(c)}</td>
      <td>
        {ids.length === 0 ? (
          "no runs yet"
        ) : (
          <ul className="plain">
            {ids.map((runId) => (
              <li key={runId}>
                <Link to={`/runs/${runId}`}>
                  <code>{runId}</code> {states.get(runId)?.state ?? "status unknown"}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </td>
      <td>
        <label>
          <span className="visually-hidden">AI mode for {c.case_id}</span>
          <select
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as RunRequest["ai_mode"]);
            }}
          >
            {AI_MODES.map((m) => (
              <option key={m} value={m}>
                AI {m}
              </option>
            ))}
          </select>
        </label>{" "}
        <button
          type="button"
          aria-label={`Run ${c.case_id}`}
          disabled={start.isPending}
          onClick={() => {
            start.mutate();
          }}
        >
          Run
        </button>
        {start.error !== null && <Failure error={start.error} />}
      </td>
    </tr>
  );
}

export function CaseList() {
  const [params, setParams] = useSearchParams();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const dataset = params.get("dataset") ?? datasets.data?.[0]?.dataset;
  const offset = Number(params.get("offset") ?? "0");
  const cases = useQuery({
    queryKey: ["cases", dataset, offset],
    queryFn: () => api.cases(dataset ?? "", PAGE, offset),
    enabled: dataset !== undefined,
  });
  const runs = useQuery({
    queryKey: ["runs", dataset],
    queryFn: () => api.runs(dataset ?? ""),
    enabled: dataset !== undefined,
  });
  const states = new Map((runs.data ?? []).map((r) => [r.run_id, r]));

  if (datasets.error !== null) return <Failure error={datasets.error} />;
  if (datasets.data === undefined) return <p>Loading datasets…</p>;
  if (dataset === undefined) return <p>No datasets on this laptop yet.</p>;
  const page = cases.data;
  return (
    <section aria-labelledby="cases-heading">
      <h2 id="cases-heading">Cases</h2>
      <label>
        Dataset{" "}
        <select
          value={dataset}
          onChange={(e) => {
            setParams({ dataset: e.target.value });
          }}
        >
          {datasets.data.map((d) => (
            <option key={d.dataset} value={d.dataset}>
              {d.dataset} ({d.cases} cases)
            </option>
          ))}
        </select>
      </label>
      {cases.error !== null && <Failure error={cases.error} />}
      {page === undefined ? (
        cases.error === null && <p>Loading cases…</p>
      ) : (
        <>
          <p>{page.total} cases</p>
          <table>
            <caption className="visually-hidden">Cases of {dataset}</caption>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">System</th>
                <th scope="col">Sources</th>
                <th scope="col">Runs</th>
                <th scope="col">New run</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((c) => (
                <CaseRow key={c.case_id} c={c} states={states} />
              ))}
            </tbody>
          </table>
          <Pager
            offset={page.offset}
            limit={page.limit}
            total={page.total}
            onPage={(next) => {
              setParams({ dataset, offset: String(next) });
            }}
          />
        </>
      )}
    </section>
  );
}
