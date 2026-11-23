import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CONFIRMED,
  INCONCLUSIVE,
  NO_FAULT,
  confirmedStatus,
  confirmedVerdict,
  renderAt,
  stubGateway,
} from "../test/gateway";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const banner = async () => within(await screen.findByRole("region", { name: "Verdict" }));

describe("run view: status banner", () => {
  it("shows a CONFIRMED verdict with level, set, trials, AI mode and alert protocol", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const b = await banner();
    expect(b.getByText("CONFIRMED")).toBeTruthy();
    expect(b.getByText("Root cause: payment (exception, logs)")).toBeTruthy();
    expect(b.getByText(/Confidence high/)).toBeTruthy();
    expect(b.getByText(/set size 1/)).toBeTruthy();
    expect(b.getByText("6 of 8 trials passed for payment")).toBeTruthy();
    expect(b.getByText(/AI mode off/)).toBeTruthy();
    expect(b.getByText(/alert protocol oracle/)).toBeTruthy();
    expect(b.getByRole("link", { name: "0.7524" }).getAttribute("href")).toBe("#def-margin");
  });

  it("reads INCONCLUSIVE as no single root cause, with the leader unconfirmed and the asks", async () => {
    stubGateway();
    renderAt(`/runs/${INCONCLUSIVE}`);
    const b = await banner();
    expect(b.getByText("INCONCLUSIVE")).toBeTruthy();
    expect(b.getByText("No single root cause established")).toBeTruthy();
    expect(b.getByText("frontend: leading candidate, not confirmed")).toBeTruthy();
    expect(b.getByText(/mandatory trial T1 failed: no_internal_anomaly/)).toBeTruthy();
  });

  it("reads NO_FAULT with an empty candidate set shown as empty", async () => {
    stubGateway();
    renderAt(`/runs/${NO_FAULT}`);
    const b = await banner();
    expect(b.getByText("NO_FAULT")).toBeTruthy();
    expect(b.getByText("No fault detected; the candidate set is empty")).toBeTruthy();
    const set = within(screen.getByRole("region", { name: "Candidate set" }));
    expect(set.getByText("empty")).toBeTruthy();
  });

  it("announces progress while the run is still running", async () => {
    stubGateway({
      [`/runs/${CONFIRMED}`]: { ...confirmedStatus, state: "running", step: 4, step_name: "causync" },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const status = await screen.findByRole("status");
    expect(status.textContent).toBe("Run running: step 4 (causync)");
    expect(screen.queryByRole("region", { name: "Verdict" })).toBeNull();
  });

  it("names the case of a finished run and stops announcing progress", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    expect(await screen.findByText("067c1ba0c360")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("run view: candidate set", () => {
  it("states the uncalibrated set and lists its members with V and nonconformity", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const set = within(await screen.findByRole("region", { name: "Candidate set" }));
    expect(set.getByText("Uncalibrated: set = top candidate only; no coverage guarantee")).toBeTruthy();
    expect(set.getByText(/payment/).textContent).toBe("payment · V 0.9 · nonconformity 0");
  });

  it("states the conformal guarantee of a calibrated set, with a null q̂ as ∞", async () => {
    stubGateway({
      [`/runs/${CONFIRMED}/verdict`]: {
        ...confirmedVerdict,
        calibration: { family: "handmade-family", sha256: "0".repeat(64) },
        confidence: { ...confirmedVerdict.confidence, q_hat: null },
      },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const set = within(await screen.findByRole("region", { name: "Candidate set" }));
    const line = set.getByText(/^Split-conformal set at α =/);
    expect(line.textContent).toContain("α = 0.1 (q̂ = ∞): contains the true root in ≥ 1 − α");
    expect(within(line).getByRole("link", { name: "∞" }).getAttribute("href")).toBe("#def-q_hat");
  });
});
