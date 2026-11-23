// Small shared pieces of the console views: the error line and the pager.
import { ApiError } from "../api";

export function Failure({ error }: { error: Error }) {
  const code = error instanceof ApiError ? ` (${error.code})` : "";
  return (
    <p role="alert">
      Could not load{code}: {error.message}
    </p>
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
