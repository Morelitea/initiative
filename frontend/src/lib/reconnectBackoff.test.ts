import { afterEach, describe, expect, it, vi } from "vitest";

import { reconnectDelay } from "./reconnectBackoff";

describe("reconnectDelay", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("spreads an attempt over the whole window", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(reconnectDelay(3, 1000, 30_000)).toBe(0);

    vi.spyOn(Math, "random").mockReturnValue(0.999);
    expect(reconnectDelay(0, 1000, 30_000)).toBeCloseTo(999);
  });

  it("doubles the window with each attempt up to the cap", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    expect(reconnectDelay(0, 1000, 30_000)).toBe(500);
    expect(reconnectDelay(2, 1000, 30_000)).toBe(2000);
    expect(reconnectDelay(10, 1000, 30_000)).toBe(15_000);
  });
});
