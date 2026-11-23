import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CONFIRMED, confirmedStatus, renderAt, stubGateway } from "../test/gateway";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("run view: progress", () => {
  it("announces progress while the run is still running", async () => {
    stubGateway({
      [`/runs/${CONFIRMED}`]: { ...confirmedStatus, state: "running", step: 4, step_name: "causync" },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("Run running: step 4 (causync)");
  });

  it("names the case of a finished run and stops announcing progress", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    expect(await screen.findByText("067c1ba0c360")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
