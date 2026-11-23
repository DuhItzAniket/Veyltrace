// Verdict sections of the run view (docs/06 §5.2 a–c, §5.3): status banner, conformal candidate
// set, ranked table with trial badges and the trial drawer. Abstentions get the same prominence
// as CONFIRMED, and status and trial results are always text plus shape, never colour alone.
import { useSearchParams } from "react-router";

import type { Alert, Verdict, VerdictRanked, VerdictRankedTrials } from "../../../contracts/generated/ts/api";
import { AtomLink, Field } from "./ui";

type Status = Verdict["status"];
type TrialId = VerdictRankedTrials["id"];

const SHAPE: Record<Status, string> = { CONFIRMED: "✔", LIKELY: "◐", INCONCLUSIVE: "?", NO_FAULT: "∅" };
const BADGE: Record<VerdictRankedTrials["result"], string> = { pass: "●", fail: "✖", untestable: "○" };
const TRIALS: TrialId[] = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10"];

function Headline({ verdict }: { verdict: Verdict }) {
  const root = verdict.root;
  const named = root === null ? "" : `${root.service} (${root.fault_class}, ${root.indicator})`;
  switch (verdict.status) {
    case "CONFIRMED":
      return <p className="headline">Root cause: {named}</p>;
    case "LIKELY":
      return <p className="headline">Likely root cause, not confirmed: {named}</p>;
    case "INCONCLUSIVE":
      return (
        <>
          <p className="headline">No single root cause established</p>
          {root !== null && <p>{root.service}: leading candidate, not confirmed</p>}
        </>
      );
    case "NO_FAULT":
      return <p className="headline">No fault detected; the candidate set is empty</p>;
  }
}

export function StatusBanner({ verdict, alert, aiMode }: { verdict: Verdict; alert: Alert; aiMode: string }) {
  const c = verdict.confidence;
  const root = verdict.root;
  // The root's own row; never a stand-in under NO_FAULT or a leaderless INCONCLUSIVE (06 §5.3 rule 1).
  const top =
    root === null
      ? undefined
      : verdict.ranked.find((r) => r.service === root.service && r.component === root.component);
  const passed = top?.trials.filter((t) => t.result === "pass").length ?? 0;
  return (
    <section aria-label="Verdict" className={`banner status-${verdict.status}`}>
      <h3>
        <span aria-hidden="true">{SHAPE[verdict.status]}</span> {verdict.status}
      </h3>
      <Headline verdict={verdict} />
      <p>
        Confidence {c.level} · set size {c.set_size} · margin <Field name="margin" value={c.margin} /> · AI
        mode {aiMode} · alert protocol {alert.protocol}
        {alert.clamped ? " · windows clamped to the data span" : ""}
      </p>
      {top !== undefined && (
        <p>
          {passed} of {top.trials.length} trials passed for {top.service} (all trials run; the verdict does
          not mark which are mandatory)
        </p>
      )}
      {verdict.asks.length > 0 && (
        <>
          <h4>Asks</h4>
          <ul>
            {verdict.asks.map((a) => (
              <li key={`${a.kind}-${a.target}`}>
                {a.kind} {a.target}: {a.why}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function CandidateSet({ verdict }: { verdict: Verdict }) {
  const c = verdict.confidence;
  return (
    <section aria-label="Candidate set">
      <h3>Candidate set</h3>
      {verdict.calibration.family === "uncalibrated" ? (
        <p>Uncalibrated: set = top candidate only; no coverage guarantee</p>
      ) : (
        <p>
          Split-conformal set at α = <Field name="alpha" value={c.alpha} /> (q̂ ={" "}
          <Field name="q_hat" value={c.q_hat} />
          ): contains the true root in ≥ 1 − α of cases like the calibration cases (marginal guarantee)
        </p>
      )}
      {verdict.candidate_set.length === 0 ? (
        <p>empty</p>
      ) : (
        <ul className="chips">
          {verdict.candidate_set.map((m) => (
            <li key={`${m.service}/${m.component ?? ""}`}>
              {m.service}
              {m.component === null ? "" : `/${m.component}`} · V <Field name="v" value={m.v} /> ·
              nonconformity <Field name="nonconformity" value={m.nonconformity} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** `service` or `service/component`: the table and drawer name a candidate the same way. */
function candidateName(r: VerdictRanked): string {
  return r.component === null ? r.service : `${r.service}/${r.component}`;
}

export function RankedTable({ verdict }: { verdict: Verdict }) {
  const [params, setParams] = useSearchParams();
  // Keyed by rank, which is unique per row; a service can appear on more than one row.
  const open = (rank: number, id: TrialId) => {
    const next = new URLSearchParams(params);
    next.set("trial", id);
    next.set("rank", String(rank));
    setParams(next);
  };
  return (
    <table>
      <caption>Ranked candidates</caption>
      <thead>
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Candidate</th>
          <th scope="col">Origin</th>
          <th scope="col">Fused score</th>
          <th scope="col">V</th>
          <th scope="col">Fault class</th>
          <th scope="col">Indicator</th>
          <th scope="col">Trials</th>
        </tr>
      </thead>
      <tbody>
        {verdict.ranked.map((r) => (
          <tr key={r.rank}>
            <td>{r.rank}</td>
            <th scope="row">{candidateName(r)}</th>
            <td>{r.origin}</td>
            <td>
              <Field name="fused_score" value={r.fused_score} />
            </td>
            <td>
              <Field name="v" value={r.v} />
            </td>
            <td>{r.fault_class}</td>
            <td>{r.indicator}</td>
            <td className="badges">
              {r.trials.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`badge ${t.result}`}
                  onClick={() => {
                    open(r.rank, t.id);
                  }}
                >
                  <span aria-hidden="true">{BADGE[t.result]}</span> {t.id} {t.result}
                </button>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The trial drawer: the selected badge's result, reason and atoms (from `?trial=&rank=`). */
export function TrialPanel({ verdict }: { verdict: Verdict }) {
  const [params] = useSearchParams();
  const id = TRIALS.find((t) => t === params.get("trial"));
  const row = verdict.ranked.find((r) => String(r.rank) === params.get("rank"));
  const trial = row?.trials.find((t) => t.id === id);
  if (row === undefined || trial === undefined) return null;
  const name = candidateName(row);
  return (
    <section aria-label={`Trial ${trial.id} of ${name}`} className="drawer">
      <h3>
        Trial {trial.id} of {name}
      </h3>
      <p>{trial.reason === null ? trial.result : `${trial.result}: ${trial.reason}`}</p>
      {trial.atoms.length === 0 ? (
        <p>No atoms.</p>
      ) : (
        <ul>
          {trial.atoms.map((a) => (
            <li key={a}>
              <AtomLink id={a} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One-line definitions of the verdict fields that numbers link to (06 §5.3 rule 2; 03 §10). */
export function Glossary() {
  const defs: [string, string][] = [
    ["v", "V: the verified score of a candidate after its trials (verdict.ranked[].v)."],
    ["nonconformity", "Nonconformity: the candidate's conformal score; set members have it ≤ q̂."],
    ["fused_score", "Fused score: Causatrix's rank-fusion score from the slate, before trials."],
    ["margin", "Margin: (V_top − V_runner-up) / V_top."],
    ["alpha", "α: the miscoverage level of the conformal set."],
    ["q_hat", "q̂: the conformal threshold from calibration; null means +∞."],
  ];
  return (
    <section aria-label="Verdict fields">
      <h3>Verdict fields</h3>
      <ul>
        {defs.map(([name, text]) => (
          <li key={name} id={`def-${name}`}>
            {text}
          </li>
        ))}
      </ul>
    </section>
  );
}
