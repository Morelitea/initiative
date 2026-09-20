/**
 * The board's scrolling.
 *
 * A fact about layout that jsdom cannot measure, and that broke the page in a
 * way only a person scrolling would notice. It is asserted against the source,
 * which is also where it regresses.
 *
 * **Virtualization is not conditional.** Turning it on partway down swaps
 * every rendered card for an estimated one while the reader is mid-scroll; the
 * browser holds the offset as the content changes height under it, and the
 * reader ends up somewhere else — in practice, back at the top.
 *
 * How the list measures itself is a shape every virtualized list in the app
 * keeps, proved once in `src/__tests__/virtualizedListShape.test.ts`.
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
});
