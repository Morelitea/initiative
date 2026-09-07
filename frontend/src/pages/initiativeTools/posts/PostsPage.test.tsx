/**
 * The board's scrolling.
 *
 * Two facts about layout that jsdom cannot measure, and that broke the page in
 * ways only a person scrolling would notice. Both are asserted against the
 * source, which is also where they regress.
 *
 * 1. **Virtualization is not conditional.** Turning it on partway down swaps
 *    every rendered card for an estimated one while the reader is mid-scroll;
 *    the browser holds the offset as the content changes height under it, and
 *    the reader ends up somewhere else — in practice, back at the top.
 * 2. **The gap lives inside the measured element.** `measureElement` reads an
 *    item's own box, so a flex `gap` between items is invisible to it: the
 *    virtualizer's model comes out shorter than the real list by the gap on
 *    every row (measured: 32px adrift over three rows at `gap-4`), and
 *    everything below sits in the wrong place.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE = fs.readFileSync(path.resolve(__dirname, "./PostsPage.tsx"), "utf-8");

describe("the posts board's virtual list", () => {
  it("virtualizes from the first render rather than at a threshold", () => {
    // `enabled` is how a threshold would be expressed, and the mode switch it
    // implies is the bug.
    expect(SOURCE).toContain("useVirtualizer");
    expect(SOURCE).not.toMatch(/enabled:\s*virtualize/);
    expect(SOURCE).not.toMatch(/VIRTUALIZE_THRESHOLD/);
  });

  it("keeps the row spacing inside the element it measures", () => {
    const container = /<div ref={listRef} className="([^"]+)"/.exec(SOURCE)?.[1];

    expect(container, "the virtualized list container moved").toBeTruthy();
    expect(container).not.toMatch(/\bgap-\d/);
    // The measured wrapper is what carries it instead.
    expect(SOURCE).toMatch(/ref={virtualizer\.measureElement}\s*\n\s*className={CARD_GAP}/);
  });

  it("measures where the list starts instead of assuming the top", () => {
    // Read during render the ref is still null, and every offset comes out
    // short by the height of the toolbar and filters above it.
    expect(SOURCE).toContain("useLayoutEffect");
    expect(SOURCE).toContain("scrollMargin: listOffset");
  });
});
