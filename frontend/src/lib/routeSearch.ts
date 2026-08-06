/**
 * Shared `validateSearch` parsers for the tool-list route search params that
 * were previously copy-pasted across route files. Each returns exactly the
 * shape the routes validated inline, so route search types are unchanged.
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

/** The `create` + `initiativeId` string params shared by tool-list routes. */
export function validateToolListSearch(search: Record<string, unknown>): {
  create?: string;
  initiativeId?: string;
} {
  return {
    create: typeof search.create === "string" ? search.create : undefined,
    initiativeId: typeof search.initiativeId === "string" ? search.initiativeId : undefined,
  };
}

/** `create` + `initiativeId` plus a coerced `page`, for paginated tool-list routes. */
export function validateToolListSearchWithPage(search: Record<string, unknown>): {
  create?: string;
  initiativeId?: string;
  page?: number;
} {
  return {
    ...validateToolListSearch(search),
    page: validatePage(search.page),
  };
}
