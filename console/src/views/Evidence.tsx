// Evidence of the run view (docs/06 §5.2 d, §5.3 rule 2): the paged atom table with server-side
// filters, and the atom drawer every atom link opens (`?atom=`). Filters and page live in the URL.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import type { EvidenceRow } from "../../../contracts/generated/ts/api";
import { api } from "../api";
import { AtomLink, Failure, Pager, num } from "./ui";

const PAGE = 50; // atoms per page (a priori: one screen; the gateway default is 200)

// Keyed by the generated unions, so tsc fails if the contract vocabulary changes.
const KINDS = Object.keys({
  internal_anomaly: 1,
  external_anomaly: 1,
  onset_precedence: 1,
  propagation: 1,
  change_proximity: 1,
  peer_contrast: 1,
  spectrum: 1,
  critical_path_share: 1,
  self_time_share: 1,
  log_new_template: 1,
  log_error_rate: 1,
  silence: 1,
  edge_gap: 1,
  intervention: 1,
  claim_check: 1,
} satisfies Record<EvidenceRow["kind"], 1>);
const ORIGINS = Object.keys({ engine: 1, claim_check: 1 } satisfies Record<EvidenceRow["origin"], 1>);

function valueText(row: EvidenceRow): string {
  return row.unit === null ? num(row.value) : `${num(row.value)} ${row.unit}`;
}

export function AtomPanel({ runId }: { runId: string }) {
  const [params] = useSearchParams();
  const atomId = params.get("atom");
  const atom = useQuery({
    queryKey: ["atom", runId, atomId],
    queryFn: () => api.atom(runId, atomId ?? ""),
    enabled: atomId !== null,
    staleTime: Infinity,
  });
  if (atomId === null) return null;
  const row = atom.data;
  return (
    <section aria-label={`Atom ${atomId}`} className="drawer">
      <h3>
        Atom <code>{atomId}</code>
      </h3>
      {atom.error !== null && <Failure error={atom.error} />}
      {row !== undefined && (
        <dl>
          <dt>Candidate</dt>
          <dd>{row.component === null ? row.candidate : `${row.candidate}/${row.component}`}</dd>
          <dt>Kind</dt>
          <dd>{row.kind}</dd>
          <dt>Predicate</dt>
          <dd>{row.predicate ?? "none"}</dd>
          <dt>Window</dt>
          <dd>{row.window}</dd>
          <dt>Value</dt>
          <dd title={String(row.value)}>{valueText(row)}</dd>
          <dt>Holds</dt>
          <dd>{row.holds === null ? "n/a" : String(row.holds)}</dd>
          <dt>Origin and producer</dt>
          <dd>
            {row.origin}, {row.producer}
          </dd>
          <dt>Arguments</dt>
          <dd>
            <code>{row.args_json}</code>
          </dd>
          <dt>Refs</dt>
          <dd>
            <ul>
              {row.refs.map((ref) => (
                <li key={ref}>
                  <code>{ref}</code>
                </li>
              ))}
            </ul>
          </dd>
        </dl>
      )}
    </section>
  );
}

export function EvidenceTable({ runId, services }: { runId: string; services: string[] }) {
  const [params, setParams] = useSearchParams();
  const filter = {
    candidate: params.get("ev_candidate") ?? undefined,
    kind: params.get("ev_kind") ?? undefined,
    origin: params.get("ev_origin") ?? undefined,
  };
  const offset = Number(params.get("ev_offset") ?? "0");
  const page = useQuery({
    queryKey: ["evidence", runId, filter, offset],
    queryFn: () => api.evidence(runId, { ...filter, limit: PAGE, offset }),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value === "") next.delete(key);
    else next.set(key, value);
    if (key !== "ev_offset") next.delete("ev_offset");
    setParams(next);
  };
  const select = (label: string, key: string, options: string[]) => (
    <label>
      {label}{" "}
      <select
        value={params.get(key) ?? ""}
        onChange={(e) => {
          set(key, e.target.value);
        }}
      >
        <option value="">all</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
  const data = page.data;
  return (
    <section aria-label="Evidence">
      <h3>Evidence</h3>
      <div className="filters">
        {select("Candidate", "ev_candidate", services)} {select("Kind", "ev_kind", KINDS)}{" "}
        {select("Origin", "ev_origin", ORIGINS)}
      </div>
      {page.error !== null && <Failure error={page.error} />}
      {data !== undefined && (
        <>
          <p aria-live="polite">
            {data.total} atoms
            {data.items.length > 0
              ? `, showing ${String(data.offset + 1)}–${String(data.offset + data.items.length)}`
              : ""}
          </p>
          <table>
            <caption className="visually-hidden">Evidence atoms</caption>
            <thead>
              <tr>
                <th scope="col">Atom</th>
                <th scope="col">Candidate</th>
                <th scope="col">Kind</th>
                <th scope="col">Window</th>
                <th scope="col">Value</th>
                <th scope="col">Origin</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.atom_id}>
                  <th scope="row">
                    <AtomLink id={row.atom_id} />
                  </th>
                  <td>{row.candidate}</td>
                  <td>{row.kind}</td>
                  <td>{row.window}</td>
                  <td title={String(row.value)}>{valueText(row)}</td>
                  <td>{row.origin}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager
            offset={data.offset}
            limit={data.limit}
            total={data.total}
            onPage={(next) => {
              set("ev_offset", String(next));
            }}
          />
        </>
      )}
    </section>
  );
}
