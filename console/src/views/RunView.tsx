// Run view (docs/06 §5.2 "/runs/:runId"): progress until the run is done, then the verdict
// sections a–b and the evidence table (d). Every value shown is an artifact value.
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { api } from "../api";
import { AtomPanel, EvidenceTable } from "./Evidence";
import { Failure } from "./ui";
import { CandidateSet, Glossary, StatusBanner } from "./Verdict";

const POLL_MS = 2000; // run status refresh while queued or running (06 §5.1 polling fallback)

function FinishedRun({ runId, aiMode }: { runId: string; aiMode: string }) {
  const finished = { staleTime: Infinity } as const; // finished-run artifacts are immutable (06 §5.1)
  const verdict = useQuery({ queryKey: ["verdict", runId], queryFn: () => api.verdict(runId), ...finished });
  const alert = useQuery({ queryKey: ["alert", runId], queryFn: () => api.alert(runId), ...finished });
  const error = verdict.error ?? alert.error;
  if (error !== null) return <Failure error={error} />;
  if (verdict.data === undefined || alert.data === undefined) return <p>Loading verdict…</p>;
  const v = verdict.data;
  return (
    <>
      <StatusBanner verdict={v} alert={alert.data} aiMode={aiMode} />
      <CandidateSet verdict={v} />
      <AtomPanel runId={runId} />
      <EvidenceTable runId={runId} services={v.ranked.map((r) => r.service)} />
      <Glossary />
    </>
  );
}

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
      {s?.state === "done" && <FinishedRun runId={runId} aiMode={s.ai_mode} />}
    </section>
  );
}
