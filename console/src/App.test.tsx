import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { stubGateway } from "./test/gateway";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App shell", () => {
  it("renders the heading and the main landmark", () => {
    stubGateway();
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Veyltrace console" })).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
  });
});
