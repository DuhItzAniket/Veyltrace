import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import runsSynth from "../fixtures/runs-synth.json";
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

  it("shows a failed cases request as an error, not as loading", async () => {
    stubGateway();
    renderAt("/?dataset=nope"); // the stub answers 404 for an unknown dataset, as the gateway does
    expect((await screen.findByRole("alert")).textContent).toContain("not_found");
    expect(screen.queryByText("Loading cases…")).toBeNull();
  });

  it("lists a failed run the gateway reports next to the case's finished runs", async () => {
    const failed = {
      run_id: "00000000000000a1",
      dataset: "synth",
      case_id: "067c1ba0c360",
      ai_mode: "record",
      state: "failed",
      step: 7,
      step_name: "relentra",
      error: "the run failed",
    };
    stubGateway({ "/runs": [failed, ...runsSynth] });
    renderAt("/");
    const row = within((await screen.findByText("067c1ba0c360")).closest("tr") as HTMLElement);
    const links = row.getAllByRole("link").map((a) => a.textContent);
    expect(links).toEqual([`${failed.run_id} failed`, `${CONFIRMED} done`]);
    expect(row.getByRole("link", { name: `${failed.run_id} failed` }).getAttribute("href")).toBe(
      `/runs/${failed.run_id}`,
    );
  });
});
