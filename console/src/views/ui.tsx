// Small shared pieces of the console views: the error line, the pager, number display and the
// links verdict-field numbers need (docs/06 §5.3 rule 2).
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
