import { readFileSync } from "node:fs";
import path from "node:path";

import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { atLeast, useWidthClass, WIDTH_CLASSES } from "./useWidthClass";

const stylesheet = readFileSync(path.join(import.meta.dirname, "../styles.css"), "utf8");

const declared = (prefix: string) =>
  Object.fromEntries(
    [...stylesheet.matchAll(new RegExp(`--${prefix}-([a-z-]+):\\s*([^;]+);`, "g"))].map(
      ([, name, value]) => [name, value]
    )
  );

describe("width classes", () => {
  it("declares a breakpoint for every class above compact, and a container size to match", () => {
    const breakpoints = declared("breakpoint");
    expect(Object.keys(breakpoints)).toEqual(WIDTH_CLASSES.slice(1));
    expect(declared("container")).toEqual(breakpoints);
  });

  it("reads the screen's class from the breakpoints styles.css declares", () => {
    const breakpoints = declared("breakpoint");
    const from = (name: string) => `(width >= ${breakpoints[name]})`;
    const asked: string[] = [];
    vi.mocked(window.matchMedia).mockImplementation((query: string) => {
      asked.push(query);
      return {
        matches: query === from("medium") || query === from("expanded"),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      } as unknown as MediaQueryList;
    });

    const { result } = renderHook(() => useWidthClass());

    expect(result.current).toBe("expanded");
    expect(asked).toContain(from("extra-large"));
  });

  it("orders the classes narrowest first", () => {
    expect(atLeast("large", "expanded")).toBe(true);
    expect(atLeast("medium", "expanded")).toBe(false);
  });
});
