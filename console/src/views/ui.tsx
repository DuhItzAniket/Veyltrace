// Small shared pieces of the console views: the error line.
import { ApiError } from "../api";

export function Failure({ error }: { error: Error }) {
  const code = error instanceof ApiError ? ` (${error.code})` : "";
  return (
    <p role="alert">
      Could not load{code}: {error.message}
    </p>
  );
}
