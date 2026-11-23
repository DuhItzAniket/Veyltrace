// Console v0 (X-05, docs/06 §5.2): the case list and the run view, built in slices. Server state
// lives in TanStack Query, UI selection in the URL; the live view, graph, timeline chart and
// receipt arrive with X-10.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes } from "react-router";

import { CaseList } from "./views/CaseList";
import { RunView } from "./views/RunView";

export function AppRoutes() {
  return (
    <>
      <header>
        <h1>
          <Link to="/">Veyltrace console</Link>
        </h1>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<CaseList />} />
          <Route path="/runs/:runId" element={<RunView />} />
          <Route path="*" element={<p>No such page.</p>} />
        </Routes>
      </main>
    </>
  );
}

const client = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

export function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
