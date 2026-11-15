// X-00 scaffold: the page shell only. Views (case list, run view, live view) arrive in X-05 and
// X-10 and read the gateway API through types from contracts/generated/ts (console/AGENTS.md).
export function App() {
  return (
    <>
      <header>
        <h1>Veyltrace console</h1>
      </header>
      <main>
        <p>
          No views yet. Start the gateway with <code>uv run python -m veyltrace_gateway</code>; the case list
          and run view arrive with X-05.
        </p>
      </main>
    </>
  );
}
