/**
 * The app shell scrolls; it does not also decide how wide a page is.
 *
 * Those two jobs were one element once, and both symptoms followed from it.
 * A scrollbar renders at the edge of its own scrollport, so a scroller that
 * was also `container mx-auto` put the bar beside the centred column instead
 * of down the side of the app. And `overflow-y: auto` does not stay on one
 * axis — with the other left `visible`, CSS computes that one to `auto` too,
 * which quietly made the shell a horizontal scroller that anything overrunning
 * anywhere could drag sideways.
 *
 * Asserted against the source because jsdom does no layout, which is why
 * neither was visible to the suite.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SHELL = path.resolve(__dirname, "./_serverRequired/_authenticated.tsx");

/** The `<main>` carrying `data-app-scroll`, as written. */
const scrollerTag = (): string => {
  const source = fs.readFileSync(SHELL, "utf-8");
  const match = source.match(/<main\b[^>]*data-app-scroll[^>]*>/s);
  if (!match) throw new Error("no [data-app-scroll] <main> in the app shell");
  return match[0];
};

describe("the app scroller", () => {
  it("scrolls vertically and refuses the other axis", () => {
    const tag = scrollerTag();
    expect(tag).toContain("overflow-y-auto");
    // Not `overflow-x-auto`: wide content owns its own scroller (the tool
    // rail, every table), so the shell never offers a horizontal bar.
    expect(tag).toContain("overflow-x-clip");
  });

  it("is not also the thing that sets the page width", () => {
    const tag = scrollerTag();
    expect(
      /\bcontainer\b/.test(tag),
      "the scroller carries `container`, which puts its scrollbar beside the centred column"
    ).toBe(false);
    expect(/\bmx-auto\b/.test(tag)).toBe(false);
  });

  it("still spans the row it sits in", () => {
    expect(scrollerTag()).toMatch(/\bflex-1\b/);
  });
});
