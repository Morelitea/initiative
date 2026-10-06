/**
 * Client half of the backend's `page_size=0` window protocol.
 *
 * A "fetch all" list request is served in bounded, server-sized windows:
 * `page` selects the window and `has_next` reports whether more remain, so
 * the complete set is retrieved by walking pages until `has_next` is false.
 * No single response is ever unbounded, and nothing is silently truncated.
 *
 * Takes any list fetcher bound to its path, inline as the queryFn:
 *
 *   queryFn: () => fetchAllPages((p) => listTasks(communityId, p), params)
 *
 * A positive `page_size` passes straight through as a single request, so the
 * same line serves paginated and fetch-all callers alike; only
 * `page_size: 0` triggers the window walk, and the merged result comes back
 * response-shaped so cached data looks exactly like a single-page response
 * to every consumer: `has_next: false` once every window is in, and still
 * true where the walk stopped at its bound.
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

/**
 * Every page of a list, walked from page 1 at the page size `params` asks for
 * until `has_next` is false (at most {@link MAX_PAGES} pages), merged into one
 * response-shaped result whose `has_next` says whether pages remain. For a
 * list whose server has no `page_size=0` window of its own.
 */
export const walkPages = async <
  TParams extends ListWindowParams,
  TResponse extends WindowedListResponse,
>(
  fetcher: (params: TParams) => Promise<TResponse>,
  params: TParams
): Promise<TResponse> => {
  let page = 1;
  let response = await fetcher({ ...params, page });
  if (!response.has_next) return response;

  const merged = [...response.items];
  // Windows are offset-based, so a concurrent insert/delete between requests
  // can repeat a row across window boundaries — dedupe by id when present.
  const seen = new Set(merged.map(idOf).filter((id) => id !== undefined));

  while (response.has_next && page < MAX_PAGES) {
    page += 1;
    response = await fetcher({ ...params, page });
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

  return { ...response, items: merged, has_prev: false, page: 1 } as TResponse;
};

/** `page_size: 0` walks the server's windows; any other size is one request. */
export const fetchAllPages = <
  TParams extends ListWindowParams,
  TResponse extends WindowedListResponse,
>(
  fetcher: (params: TParams) => Promise<TResponse>,
  params: TParams
): Promise<TResponse> => (params.page_size === 0 ? walkPages(fetcher, params) : fetcher(params));
