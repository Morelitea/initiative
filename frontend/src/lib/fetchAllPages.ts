/**
 * Client half of the backend's `page_size=0` window protocol.
 *
 * A "fetch all" list request is served in bounded, server-sized windows:
 * `page` selects the window and `has_next` reports whether more remain, so
 * the complete set is retrieved by walking pages until `has_next` is false.
 * No single response is ever unbounded, and nothing is silently truncated.
 *
 * Works with any Orval-generated list fetcher — pass it inline as the
 * queryFn, no per-resource wrapper needed:
 *
 *   queryFn: () => fetchAllPages(listTasksApiV1GGuildIdTasksGet, guildId, params)
 *
 * A positive `page_size` passes straight through as a single request, so the
 * same line serves paginated and fetch-all callers alike; only
 * `page_size: 0` triggers the window walk, and the merged result comes back
 * response-shaped (`has_next: false`) so cached data looks exactly like a
 * complete single-page response to every consumer.
 */

type WindowedListResponse = {
  items: unknown[];
  has_next?: boolean | null;
};

type ListWindowParams = {
  page?: number;
  page_size?: number;
};

/** Safety bound on the walk (50 windows × 1000-row server window = 50k rows). */
const MAX_PAGES = 50;

const idOf = (item: unknown): number | string | undefined =>
  (item as { id?: number | string } | null)?.id;

export const fetchAllPages = async <
  TParams extends ListWindowParams,
  TResponse extends WindowedListResponse,
>(
  fetcher: (guildId: number, params?: TParams) => Promise<TResponse>,
  guildId: number,
  params: TParams
): Promise<TResponse> => {
  if (params.page_size !== 0) return fetcher(guildId, params);

  let page = 1;
  let response = await fetcher(guildId, { ...params, page });
  if (!response.has_next) return response;

  const merged = [...response.items];
  // Windows are offset-based, so a concurrent insert/delete between requests
  // can repeat a row across window boundaries — dedupe by id when present.
  const seen = new Set(merged.map(idOf).filter((id) => id !== undefined));

  while (response.has_next && page < MAX_PAGES) {
    page += 1;
    response = await fetcher(guildId, { ...params, page });
    for (const item of response.items) {
      const id = idOf(item);
      if (id !== undefined) {
        if (seen.has(id)) continue;
        seen.add(id);
      }
      merged.push(item);
    }
  }

  if (response.has_next) {
    // Never expected in practice; surface it rather than loop forever.
    console.warn(`fetchAllPages: stopped after ${MAX_PAGES} pages with has_next still true`);
  }

  return { ...response, items: merged, has_next: false, page: 1 } as TResponse;
};
