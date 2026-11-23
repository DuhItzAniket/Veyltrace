// Small shared pieces: error line, pager, number display and the links every number needs
// (docs/06 §5.3 rule 2: atoms link to their row, verdict fields to their definition).
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../api";

export function Failure({ error }: { error: Error }) {
  const code = error instanceof ApiError ? ` (${error.code})` : "";
  return (
    <p role="alert">
      Could not load{code}: {error.message}
    </p>
  );
}

/** Display only: 4 significant digits; the full artifact value stays in the title. */
export function num(x: number): string {
  return Number(x.toPrecision(4)).toString();
}

/** URL search with one key set (or removed), so selection survives in a shared link. */
export function useSearchWith(): (changes: Record<string, string | null>) => string {
  const [params] = useSearchParams();
  return (changes) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    return `?${next.toString()}`;
  };
}

export function AtomLink({ id }: { id: string }) {
  const searchWith = useSearchWith();
  return (
    <Link to={{ search: searchWith({ atom: id }) }}>
      <code>{id}</code>
    </Link>
  );
}

/** A verdict field value linked to its one-line definition in the run view's glossary. */
export function Field({ name, value }: { name: string; value: number | null }) {
  return (
    <a href={`#def-${name}`} title={value === null ? "null (+∞)" : String(value)}>
      {value === null ? "∞" : num(value)}
    </a>
  );
}

export function Pager(props: {
  offset: number;
  limit: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  const { offset, limit, total, onPage } = props;
  return (
    <nav aria-label="Pages">
      <button
        type="button"
        disabled={offset === 0}
        onClick={() => {
          onPage(Math.max(0, offset - limit));
        }}
      >
        Previous page
      </button>{" "}
      <button
        type="button"
        disabled={offset + limit >= total}
        onClick={() => {
          onPage(offset + limit);
        }}
      >
        Next page
      </button>
    </nav>
  );
}
