import { describe, expect, it, vi } from "vitest";

import { fetchAllPages } from "./fetchAllPages";

type Item = { id: number };
type Params = { page?: number; page_size?: number; initiative_id?: number };
type Response = {
  items: Item[];
  has_next?: boolean | null;
  total_count?: number;
  page?: number;
};

const page = (ids: number[], hasNext: boolean, total: number): Response => ({
  items: ids.map((id) => ({ id })),
  has_next: hasNext,
  total_count: total,
  page: 1,
});

const GUILD = 7;

describe("fetchAllPages", () => {
  it("passes a positive page_size through as a single request, even with has_next", async () => {
    const fetcher = vi.fn(async (_guildId: number, _params?: Params) => page([1, 2], true, 9));
    const result = await fetchAllPages(fetcher, GUILD, { page: 1, page_size: 2 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(GUILD, { page: 1, page_size: 2 });
    expect(result.has_next).toBe(true); // paginated screens keep their pager
  });

  it("returns a complete page_size=0 single window as-is with one request", async () => {
    const fetcher = vi.fn(async (_guildId: number, _params?: Params) => page([1, 2], false, 2));
    const result = await fetchAllPages(fetcher, GUILD, { page_size: 0 });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(GUILD, { page_size: 0, page: 1 });
    expect(result.items.map((i) => i.id)).toEqual([1, 2]);
    expect(result.has_next).toBe(false);
  });

  it("walks windows until has_next is false, preserving order and extra params", async () => {
    const windows = [page([1, 2, 3], true, 7), page([4, 5, 6], true, 7), page([7], false, 7)];
    const fetcher = vi.fn(
      async (_guildId: number, params?: Params) => windows[(params?.page ?? 1) - 1]
    );
    const result = await fetchAllPages(fetcher, GUILD, { page_size: 0, initiative_id: 42 });
    expect(fetcher.mock.calls.map(([, p]) => p?.page)).toEqual([1, 2, 3]);
    for (const [, params] of fetcher.mock.calls) {
      expect(params?.initiative_id).toBe(42);
    }
    expect(result.items.map((i) => i.id)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(result.has_next).toBe(false);
    expect(result.total_count).toBe(7);
  });

  it("dedupes rows repeated across window boundaries (concurrent writes)", async () => {
    // A row deleted between requests shifts the offset: id 3 appears twice.
    const windows = [page([1, 2, 3], true, 6), page([3, 4, 5], false, 5)];
    const fetcher = vi.fn(
      async (_guildId: number, params?: Params) => windows[(params?.page ?? 1) - 1]
    );
    const result = await fetchAllPages(fetcher, GUILD, { page_size: 0 });
    expect(result.items.map((i) => i.id)).toEqual([1, 2, 3, 4, 5]);
  });

  it("stops at the page safety bound instead of looping forever", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      // A misbehaving server that always reports another page.
      const fetcher = vi.fn(async (_guildId: number, params?: Params) =>
        page([params?.page ?? 1], true, 9999)
      );
      const result = await fetchAllPages(fetcher, GUILD, { page_size: 0 });
      expect(fetcher.mock.calls.length).toBe(50);
      expect(result.items.length).toBe(50);
      expect(warn).toHaveBeenCalledOnce();
    } finally {
      warn.mockRestore();
    }
  });
});
