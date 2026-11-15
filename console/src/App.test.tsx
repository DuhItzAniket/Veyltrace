import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "./App";

afterEach(cleanup);

describe("App shell", () => {
  it("renders the heading and the main landmark", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Veyltrace console" })).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
  });
});
