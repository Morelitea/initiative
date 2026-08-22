/**
 * Shared `validateSearch` parsers for the route search params that were
 * previously copy-pasted across route files.
 */

/** Search shape for routes whose only param is a page number. Keep the key
 * OPTIONAL — a required-but-undefined key would force `search` onto every
 * navigation targeting the route. */
export type PageSearch = { page?: number };

/**
 * Coerce a `page` search param: a number >= 1 passes through, a numeric string
 * >= 1 is coerced to a number, and anything else becomes `undefined`.
 */
export function validatePage(value: unknown): number | undefined {
  if (typeof value === "number" && value >= 1) return value;
  if (typeof value === "string" && Number(value) >= 1) return Number(value);
  return undefined;
}

/**
 * Search shared by the six initiative tool tabs: open the create dialog, the
 * page cursor for the tools that paginate, and which state of a list is shown
 * (projects: templates / archived).
 *
 * There is no `initiativeId` any more — the path carries it. Because all six
 * tabs are now routes under one initiative rather than six separate list
 * routes, `page` is SHARED between them; a tab link must clear it (`search={{}}`)
 * so a cursor from one tool doesn't follow the reader into the next.
 */
export function validateInitiativeToolSearch(search: Record<string, unknown>): {
  create?: string;
  page?: number;
  status?: string;
} {
  return {
    create: typeof search.create === "string" ? search.create : undefined,
    page: validatePage(search.page),
    status: typeof search.status === "string" ? search.status : undefined,
  };
}
