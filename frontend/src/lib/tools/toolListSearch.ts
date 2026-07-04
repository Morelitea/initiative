/**
 * Shared `validateSearch` parsing for a tool's list route.
 *
 * Every tool list route (`/projects`, `/documents`, `/queues`, `/counter-groups`,
 * `/events`) accepts the same `?create` / `?initiativeId` params — and the
 * paginated ones also `?page`. This centralizes that parsing so the routes can't
 * drift in how they coerce those params (the create/initiativeId convention is
 * the cross-surface "open create dialog" protocol).
 */

export interface ToolListSearch {
  create?: string;
  initiativeId?: string;
}

export interface PagedToolListSearch extends ToolListSearch {
  page?: number;
}

const parseString = (value: unknown): string | undefined =>
  typeof value === "string" ? value : undefined;

const parsePage = (value: unknown): number | undefined => {
  if (typeof value === "number" && value >= 1) return value;
  if (typeof value === "string" && Number(value) >= 1) return Number(value);
  return undefined;
};

export function toolListSearch(search: Record<string, unknown>): ToolListSearch;
export function toolListSearch(
  search: Record<string, unknown>,
  opts: { page: true }
): PagedToolListSearch;
export function toolListSearch(
  search: Record<string, unknown>,
  opts?: { page: true }
): ToolListSearch | PagedToolListSearch {
  const base: ToolListSearch = {
    create: parseString(search.create),
    initiativeId: parseString(search.initiativeId),
  };
  return opts?.page ? { ...base, page: parsePage(search.page) } : base;
}
