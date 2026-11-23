// Verdict sections of the run view (docs/06 §5.2 a–b, §5.3): status banner, conformal candidate
// set and the glossary its numbers link to. Abstentions get the same prominence as CONFIRMED, and
// the status is always text plus shape, never colour alone.
import type { Alert, Verdict } from "../../../contracts/generated/ts/api";
import { Field } from "./ui";

type Status = Verdict["status"];

const SHAPE: Record<Status, string> = { CONFIRMED: "✔", LIKELY: "◐", INCONCLUSIVE: "?", NO_FAULT: "∅" };

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
  const top = verdict.ranked[0];
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
          {passed} of {top.trials.length} trials passed for {top.service}
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
