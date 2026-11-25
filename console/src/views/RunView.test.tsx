import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunStatus } from "../../../contracts/generated/ts/api";
import { ApiError } from "../api";
import {
  CONFIRMED,
  INCONCLUSIVE,
  NO_FAULT,
  confirmedStatus,
  confirmedVerdict,
  renderAt,
  stubGateway,
} from "../test/gateway";
import { pollInterval } from "./RunView";

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
    expect(b.getByText(/^6 of 8 trials passed for payment \(all trials run/)).toBeTruthy();
    expect(b.getByText(/AI mode off/)).toBeTruthy();
    expect(b.getByText(/alert protocol oracle/)).toBeTruthy();
    expect(b.getByRole("link", { name: "0.752427184" }).getAttribute("href")).toBe("#def-margin");
  });

  it("reads INCONCLUSIVE as no single root cause, with the leader unconfirmed and the asks", async () => {
    stubGateway();
    renderAt(`/runs/${INCONCLUSIVE}`);
    const b = await banner();
    expect(b.getByText("INCONCLUSIVE")).toBeTruthy();
    expect(b.getByText("No single root cause established")).toBeTruthy();
    expect(b.getByText("frontend: leading candidate, not confirmed")).toBeTruthy();
    expect(b.getByText(/mandatory trial T1 failed: no_internal_anomaly/)).toBeTruthy();
    const path = within(screen.getByRole("region", { name: "Propagation path" }));
    expect(path.getByText("From the leading candidate, not confirmed")).toBeTruthy();
  });

  it("reads NO_FAULT with an empty candidate set shown as empty", async () => {
    stubGateway();
    renderAt(`/runs/${NO_FAULT}`);
    const b = await banner();
    expect(b.getByText("NO_FAULT")).toBeTruthy();
    expect(b.getByText("No fault detected; the candidate set is empty")).toBeTruthy();
    const set = within(screen.getByRole("region", { name: "Candidate set" }));
    expect(set.getByText("empty")).toBeTruthy();
    expect(screen.getByText("No propagation path")).toBeTruthy();
    expect(b.queryByText(/trials passed/)).toBeNull();
  });

  // Handmade from the CONFIRMED fixture (no synth case yields these): LIKELY, and a margin just
  // under c_high = 0.30 that rounding to 4 digits would show as 0.3.
  it("reads LIKELY as not confirmed and shows the margin at its stored precision", async () => {
    stubGateway({
      [`/runs/${CONFIRMED}/verdict`]: {
        ...confirmedVerdict,
        status: "LIKELY",
        confidence: { ...confirmedVerdict.confidence, level: "medium", margin: 0.29996 },
      },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const b = await banner();
    expect(b.getByText("LIKELY")).toBeTruthy();
    expect(b.getByText("Likely root cause, not confirmed: payment (exception, logs)")).toBeTruthy();
    expect(b.getByRole("link", { name: "0.29996" })).toBeTruthy();
    expect(b.queryByRole("link", { name: "0.3" })).toBeNull();
  });

  // Handmade: an INCONCLUSIVE verdict with no leader (root null).
  it("reads INCONCLUSIVE without a leader and names no candidate", async () => {
    stubGateway({
      [`/runs/${CONFIRMED}/verdict`]: {
        ...confirmedVerdict,
        status: "INCONCLUSIVE",
        root: null,
        confidence: { ...confirmedVerdict.confidence, level: "none" },
      },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const b = await banner();
    expect(b.getByText("No single root cause established")).toBeTruthy();
    expect(b.queryByText(/leading candidate/)).toBeNull();
    expect(b.queryByText(/trials passed/)).toBeNull();
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

describe("run view: ranked table, trial drawer, path and timeline", () => {
  it("ranks every pool candidate with one text badge per trial", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const table = within(await screen.findByRole("table", { name: "Ranked candidates" }));
    const rows = table.getAllByRole("row").slice(1);
    expect(rows.map((r) => r.querySelector("th")?.textContent)).toEqual([
      "payment",
      "checkout",
      "frontend",
      "cart/cart-1",
      "recommend",
    ]);
    const [top] = rows;
    if (top === undefined) throw new Error("no ranked rows");
    const first = within(top);
    expect(first.getByRole("button", { name: "T1 pass" })).toBeTruthy();
    expect(first.getByRole("button", { name: "T6 fail" })).toBeTruthy();
    expect(first.getByRole("button", { name: "T5 untestable" })).toBeTruthy();
    expect(first.getByText("slate")).toBeTruthy();
    expect(top.querySelector("td")?.textContent).toBe("1");
  });

  // Handmade from the CONFIRMED fixture: the same service ranked twice (two components).
  it("opens the trial of the clicked row when a service is ranked twice", async () => {
    const [r1, r2, ...rest] = confirmedVerdict.ranked;
    if (r1 === undefined || r2 === undefined) throw new Error("fixture has fewer than 2 ranked rows");
    stubGateway({
      [`/runs/${CONFIRMED}/verdict`]: {
        ...confirmedVerdict,
        ranked: [r1, { ...r2, service: "payment", component: "payment-2" }, ...rest],
      },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const table = within(await screen.findByRole("table", { name: "Ranked candidates" }));
    const [secondT1] = table.getAllByRole("button", { name: "T1 fail" });
    if (secondT1 === undefined) throw new Error("no failed T1 badge");
    fireEvent.click(secondT1);
    const trial = within(await screen.findByRole("region", { name: "Trial T1 of payment/payment-2" }));
    expect(trial.getByText("fail: explained_by_callee:payment")).toBeTruthy();
  });

  it("names a service ranked twice once in the evidence candidate filter", async () => {
    const [r1, r2, ...rest] = confirmedVerdict.ranked;
    if (r1 === undefined || r2 === undefined) throw new Error("fixture has fewer than 2 ranked rows");
    stubGateway({
      [`/runs/${CONFIRMED}/verdict`]: {
        ...confirmedVerdict,
        ranked: [r1, { ...r2, service: r1.service, component: `${r1.service}-2` }, ...rest],
      },
    });
    renderAt(`/runs/${CONFIRMED}`);
    const region = within(await screen.findByRole("region", { name: "Evidence" }));
    const options = within(region.getByLabelText("Candidate"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options.filter((o) => o === r1.service)).toHaveLength(1);
    expect(new Set(options).size).toBe(options.length);
  });

  it("opens a trial's reason and atoms, and an atom link shows the evidence row", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const table = within(await screen.findByRole("table", { name: "Ranked candidates" }));
    const [checkoutT1] = table.getAllByRole("button", { name: "T1 fail" });
    if (checkoutT1 === undefined) throw new Error("no failed T1 badge");
    fireEvent.click(checkoutT1);
    const trial = within(await screen.findByRole("region", { name: "Trial T1 of checkout" }));
    expect(trial.getByText("fail: explained_by_callee:payment")).toBeTruthy();
    fireEvent.click(trial.getByRole("link", { name: "Ed5c1d9ce83" }));
    const atom = within(await screen.findByRole("region", { name: "Atom Ed5c1d9ce83" }));
    expect(await atom.findByText("internal_anomaly")).toBeTruthy();
    expect(atom.getByText("8 z")).toBeTruthy();
    expect(atom.getByText("payment|payment|log_error_rate|logs")).toBeTruthy();
  });

  it("lists the card's propagation path and timeline", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const path = within(await screen.findByRole("region", { name: "Propagation path" }));
    expect(path.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "payment",
      "checkout",
      "frontend",
    ]);
    expect(path.queryByText(/not confirmed/)).toBeNull();
    const timeline = within(screen.getByRole("region", { name: "Timeline" }));
    expect(timeline.getByText(/cart-1 deploy change/)).toBeTruthy();
    expect(timeline.getByRole("link", { name: "Ea59a066a7a" })).toBeTruthy();
  });
});

describe("run view: evidence table", () => {
  it("pages all atoms and filters them by candidate on the server", async () => {
    const calls = stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const region = within(await screen.findByRole("region", { name: "Evidence" }));
    expect(await region.findByText("235 atoms, showing 1–50")).toBeTruthy();
    fireEvent.change(region.getByLabelText("Candidate"), { target: { value: "payment" } });
    expect(await region.findByText("40 atoms, showing 1–40")).toBeTruthy();
    const last = calls.filter((c) => c.url.pathname.endsWith("/evidence")).at(-1);
    expect(last?.url.searchParams.get("candidate")).toBe("payment");
    const rows = within(region.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.every((r) => r.textContent.includes("payment"))).toBe(true);
  });

  it("moves to the next page", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}`);
    const region = within(await screen.findByRole("region", { name: "Evidence" }));
    await region.findByText("235 atoms, showing 1–50");
    fireEvent.click(region.getByRole("button", { name: "Next page" }));
    expect(await region.findByText("235 atoms, showing 51–100")).toBeTruthy();
  });

  it("opens the atom drawer from an atom link with the row and its refs", async () => {
    stubGateway();
    renderAt(`/runs/${CONFIRMED}?ev_candidate=payment&ev_kind=internal_anomaly`);
    const region = within(await screen.findByRole("region", { name: "Evidence" }));
    fireEvent.click(await region.findByRole("link", { name: "Ed5c1d9ce83" }));
    const atom = within(await screen.findByRole("region", { name: "Atom Ed5c1d9ce83" }));
    expect(await atom.findByText("internal_anomaly")).toBeTruthy();
    expect(atom.getByText("8 z")).toBeTruthy();
    expect(atom.getByText("payment|payment|log_error_rate|logs")).toBeTruthy();
  });
});

describe("run view: status polling", () => {
  const status = (state: RunStatus["state"]) => ({ ...confirmedStatus, state }) as RunStatus;

  it("polls while the run is queued or running and stops when it ended", () => {
    expect(pollInterval(undefined, null)).toBe(2000);
    expect(pollInterval(status("queued"), null)).toBe(2000);
    expect(pollInterval(status("running"), null)).toBe(2000);
    expect(pollInterval(status("done"), null)).toBe(false);
    expect(pollInterval(status("failed"), null)).toBe(false);
  });

  it("stops polling a run the gateway does not know, and keeps polling through other errors", async () => {
    expect(pollInterval(undefined, new ApiError(404, "run_not_found", "no run"))).toBe(false);
    expect(pollInterval(status("running"), new ApiError(503, "http_error", "HTTP 503"))).toBe(2000);
    expect(pollInterval(undefined, new TypeError("Failed to fetch"))).toBe(2000);
    stubGateway();
    renderAt("/runs/0123456789abcdef");
    expect((await screen.findByRole("alert")).textContent).toContain("not_found");
  });
});
