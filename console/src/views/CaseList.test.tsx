import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CONFIRMED, renderAt, stubGateway } from "../test/gateway";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("case list", () => {
  it("lists the synth cases with system, sources and each run's state", async () => {
    stubGateway();
    renderAt("/");
    const row = (await screen.findByText("067c1ba0c360")).closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText("other")).toBeTruthy();
    expect(cells.getByText("metrics, logs, traces, events")).toBeTruthy();
    const link = cells.getByRole("link", { name: `${CONFIRMED} done` });
    expect(link.getAttribute("href")).toBe(`/runs/${CONFIRMED}`);
    expect(screen.getByText("5 cases")).toBeTruthy();
  });

  it("shows a dataset before its first run (an RE2 dataset folder)", async () => {
    stubGateway({
      "/datasets": [
        { dataset: "re2-ob", cases: 1 },
        { dataset: "synth", cases: 5 },
      ],
      "/cases": {
        items: [{ case_id: "0123456789ab", dataset: "re2-ob", system: null, sources: null, runs: [] }],
        total: 1,
        limit: 50,
        offset: 0,
      },
      "/runs": [],
    });
    renderAt("/?dataset=re2-ob");
    const row = (await screen.findByText("0123456789ab")).closest("tr") as HTMLElement;
    expect(within(row).getByText("no runs yet")).toBeTruthy();
    expect(within(row).getAllByText("unknown until the first run")).toHaveLength(2);
    expect(screen.getByLabelText<HTMLSelectElement>("Dataset").value).toBe("re2-ob");
  });

  it("starts a run with the chosen AI mode and opens its run view", async () => {
    const calls = stubGateway();
    renderAt("/");
    const row = (await screen.findByText("067c1ba0c360")).closest("tr") as HTMLElement;
    fireEvent.change(within(row).getByLabelText("AI mode for 067c1ba0c360"), { target: { value: "record" } });
    fireEvent.click(within(row).getByRole("button", { name: "Run 067c1ba0c360" }));
    expect(await screen.findByRole("heading", { level: 2, name: `Run ${CONFIRMED}` })).toBeTruthy();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url.pathname).toBe("/api/v1/runs");
    expect(JSON.parse(post?.body ?? "null")).toEqual({
      dataset: "synth",
      case_id: "067c1ba0c360",
      ai_mode: "record",
    });
  });
});
