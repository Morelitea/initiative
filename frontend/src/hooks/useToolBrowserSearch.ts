import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  isToolSortField,
  TOOL_SORT_FIELDS,
  type ToolSortField,
} from "@/components/toolBrowser/ToolTable";
import { toolForRouteSegment } from "@/lib/tools";

const DEFAULT_PAGE_SIZE = 20;

interface ToolBrowserParams {
  tool?: string;
  page?: number;
  q?: string;
  sort?: string;
  dir?: string;
}

/**
 * The address-bar state of a tool browser — the rail's tool, the table's page,
 * search and order — for the community front page and My Tools. Everything
 * but the page size is in the address, so a narrowed table is a link someone
 * can send. `Extra` names the page's own params, which ride along untouched.
 *
 * `table` is what `ToolTable` takes of it.
 */
export function useToolBrowserSearch<Extra extends object = object>(
  sortFields: readonly ToolSortField[] = TOOL_SORT_FIELDS
) {
  const navigate = useNavigate();
  const params = useSearch({ strict: false });
  const search = params as ToolBrowserParams & Extra;

  const setSearch = useCallback(
    (next: Record<string, string | number | undefined>) => {
      void navigate({ to: ".", search: { ...search, ...next }, replace: true });
    },
    [navigate, search]
  );

  const requested = search.tool ? toolForRouteSegment(search.tool) : null;
  /** An unknown or unreachable `?tool=` falls back to the first of `tools`
   *  rather than rendering a table the reader has no business seeing. */
  const selectTool = (tools: readonly Tool[]): Tool =>
    requested && tools.includes(requested) ? requested : (tools[0] ?? Tool.project);

  const page = search.page ?? 1;
  const query = search.q ?? "";
  // The default order is left out of the address — most-recently-updated is
  // what the endpoints do unasked, so spelling it in every URL is only noise.
  const sortBy: ToolSortField = isToolSortField(search.sort, sortFields)
    ? search.sort
    : "updated_at";
  const sortDir: "asc" | "desc" =
    search.dir === "asc" || search.dir === "desc"
      ? search.dir
      : sortBy === "updated_at"
        ? "desc"
        : "asc";

  // What is typed goes into the box at once and to the server a beat later, so
  // a search is one request rather than one per keystroke.
  const [draftQuery, setDraftQuery] = useState(query);
  const lastPushedQuery = useRef(query);
  useEffect(() => {
    // A query that changed elsewhere — the back button, a pasted link — wins
    // over a draft nobody is typing into.
    if (query !== lastPushedQuery.current) {
      lastPushedQuery.current = query;
      setDraftQuery(query);
    }
  }, [query]);
  // Switching tools is a fresh list: the rail's link carries no `q`, so the box
  // empties with it and a keystroke still waiting from the last tool is dropped
  // rather than landing on the new one.
  const lastTool = useRef(search.tool);
  useEffect(() => {
    if (lastTool.current === search.tool) return;
    lastTool.current = search.tool;
    lastPushedQuery.current = query;
    setDraftQuery(query);
  }, [search.tool, query]);
  useEffect(() => {
    if (draftQuery === query) return;
    const timer = setTimeout(() => {
      lastPushedQuery.current = draftQuery;
      setSearch({ q: draftQuery || undefined, page: undefined });
    }, 300);
    return () => clearTimeout(timer);
  }, [draftQuery, query, setSearch]);

  const onSortChange = useCallback(
    (field: ToolSortField, direction: "asc" | "desc") => {
      const isDefault = field === "updated_at" && direction === "desc";
      setSearch({
        sort: isDefault ? undefined : field,
        dir: isDefault ? undefined : direction,
        page: undefined,
      });
    },
    [setSearch]
  );

  const onPageChange = useCallback(
    (next: number) => setSearch({ page: next <= 1 ? undefined : next }),
    [setSearch]
  );

  // Page size is a view preference, not a URL concern — the page stays
  // shareable while the size stays local, as on the other list pages.
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const onPageSizeChange = useCallback(
    (size: number) => {
      setPageSize(size);
      onPageChange(1);
    },
    [onPageChange]
  );

  return {
    search,
    setSearch,
    selectTool,
    /** The search as the address has it — what the server is asked for. */
    query,
    table: {
      page,
      pageSize,
      onPageChange,
      onPageSizeChange,
      search: draftQuery,
      onSearchChange: setDraftQuery,
      sortBy,
      sortDir,
      onSortChange,
      sortFields,
    },
  };
}
