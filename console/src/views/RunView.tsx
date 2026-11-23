// Run view (docs/06 §5.2 "/runs/:runId"): the run's case and its progress until the run is done.
// The verdict sections follow in the next X-05 slices.
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { api } from "../api";
import { Failure } from "./ui";

const POLL_MS = 2000; // run status refresh while queued or running (06 §5.1 polling fallback)

export function RunView() {
  const { runId = "" } = useParams();
  const status = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (q) =>
      q.state.data?.state === "done" || q.state.data?.state === "failed" ? false : POLL_MS,
  });
  const s = status.data;
  return (
    <section aria-labelledby="run-heading">
      <h2 id="run-heading">
        Run <code>{runId}</code>
      </h2>
      {status.error !== null && <Failure error={status.error} />}
      {s !== undefined && (
        <p>
          Case <code>{s.case_id}</code> of {s.dataset}
        </p>
      )}
      <div aria-live="polite">
        {s !== undefined && s.state !== "done" && (
          <p role="status">
            Run {s.state}: step {s.step} ({s.step_name}){s.error === null ? "" : `: ${s.error}`}
          </p>
        )}
      </div>
    </section>
  );
}
