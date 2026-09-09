/**
 * The wall's scrolling.
 *
 * Facts about layout that jsdom cannot measure and that a person scrolling
 * would notice, asserted against the source the way the board's are.
 *
 * 1. **The list is fetched as it is read.** An infinite query with a
 *    sentinel at the bottom, not a page in the URL: a wall is scrolled.
 * 2. **Every view is virtualized from the first render.** The grid and the
 *    timeline through the shared row virtualizer, the masonry through a
 *    window over placements it computes without measuring — none of them
 *    mounts the whole gallery.
 * 3. **The row gap lives inside the measured element**, so the virtualizer's
 *    model is not short by the gap on every row.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const read = (relative: string) => fs.readFileSync(path.resolve(__dirname, relative), "utf-8");

const PAGE = read("./GalleryDetailPage.tsx");
const ROWS = read("../../../components/initiativeTools/galleries/VirtualRows.tsx");
const GRID = read("../../../components/initiativeTools/galleries/GalleryGridView.tsx");
const TIMELINE = read("../../../components/initiativeTools/galleries/GalleryTimelineView.tsx");
const MASONRY = read("../../../components/initiativeTools/galleries/MasonryWall.tsx");

describe("the gallery wall", () => {
  it("fetches pictures as the reader scrolls rather than paging", () => {
    expect(PAGE).toContain("useGalleryImagesFeed");
    expect(PAGE).toContain("IntersectionObserver");
    expect(PAGE).toContain("fetchNextPage");
    expect(PAGE).not.toMatch(/PaginationBar/);
  });

  it("virtualizes every view from the first render", () => {
    expect(ROWS).toContain("useVirtualizer");
    expect(ROWS).not.toMatch(/enabled:\s*virtualize/);
    expect(GRID).toContain("<VirtualRows");
    expect(TIMELINE).toContain("<VirtualRows");
    // The wall windows its own placements: only the boxes crossing the
    // viewport are rendered.
    expect(MASONRY).toMatch(/placements\.filter/);
  });

  it("keeps the row spacing inside the element it measures", () => {
    expect(ROWS).toMatch(/ref={virtualizer\.measureElement}\s*\n\s*className={ROW_GAP}/);
  });

  it("measures where the list starts instead of assuming the top", () => {
    expect(ROWS).toContain("useLayoutEffect");
    expect(ROWS).toContain("scrollMargin: listOffset");
  });

  it("scrolls with the app's own scroller, not the window", () => {
    expect(ROWS).toContain("[data-app-scroll]");
    expect(MASONRY).toContain("[data-app-scroll]");
  });
});
