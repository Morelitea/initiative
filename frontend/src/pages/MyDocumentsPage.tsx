import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { ChevronDown, Filter, Loader2, Search } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { invalidateAllDocuments } from "@/api/query-keys";
import { getItem, setItem } from "@/lib/storage";
import { guildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SortIcon } from "@/components/SortIcon";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useGuilds } from "@/hooks/useGuilds";
import { useDateLocale } from "@/hooks/useDateLocale";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import { PullToRefresh } from "@/components/PullToRefresh";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { TagBadge } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import type { DocumentListResponse, DocumentSummary } from "@/types/api";

const MY_DOCUMENTS_FILTERS_KEY = "initiative-my-documents-filters";
const FILTER_DEFAULTS = {
  guildFilters: [] as number[],
};
const PAGE_SIZE = 20;

/** Map DataTable column IDs to backend sort field names */
const SORT_FIELD_MAP: Record<string, string> = {
  title: "title",
  updatedAt: "updated_at",
};

const readStoredFilters = () => {
  try {
    const raw = getItem(MY_DOCUMENTS_FILTERS_KEY);
    if (!raw) {
      return FILTER_DEFAULTS;
    }
    const parsed = JSON.parse(raw);
    return {
      guildFilters: Array.isArray(parsed?.guildFilters)
        ? parsed.guildFilters
        : FILTER_DEFAULTS.guildFilters,
    };
  } catch {
    return FILTER_DEFAULTS;
  }
};

const getDefaultFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

export const MyDocumentsPage = () => {
  const { t } = useTranslation(["documents", "common"]);
  const { guilds, activeGuildId } = useGuilds();
  const localQueryClient = useQueryClient();
  const router = useRouter();
  const dateLocale = useDateLocale();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const handleRefresh = useCallback(async () => {
    await invalidateAllDocuments();
  }, []);

  const [guildFilters, setGuildFilters] = useState<number[]>(
    () => readStoredFilters().guildFilters
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultFiltersVisibility);

  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [sortBy, setSortBy] = useState<string | undefined>(undefined);
  const [sortDir, setSortDir] = useState<string | undefined>(undefined);

  const handleSortingChange = useCallback((sorting: SortingState) => {
    if (sorting.length > 0) {
      const field = SORT_FIELD_MAP[sorting[0].id];
      if (field) {
        setSortBy(field);
        setSortDir(sorting[0].desc ? "desc" : "asc");
      }
    } else {
      setSortBy(undefined);
      setSortDir(undefined);
    }
  }, []);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        void router.navigate({
          to: ".",
          search: {
            ...searchParamsRef.current,
            page: next <= 1 ? undefined : next,
          },
          replace: true,
        });
        return next;
      });
    },
    [router]
  );

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [guildFilters, debouncedSearch, setPage]);

  // Persist filters to localStorage
  useEffect(() => {
    const payload = { guildFilters };
    setItem(MY_DOCUMENTS_FILTERS_KEY, JSON.stringify(payload));
  }, [guildFilters]);

  const documentsGlobalParams = useMemo(() => {
    const params: Record<string, string | string[] | number | number[]> = {
      scope: "global",
    };
    if (guildFilters.length > 0) params.guild_ids = guildFilters;
    if (debouncedSearch.trim()) params.search = debouncedSearch.trim();
    if (sortBy) params.sort_by = sortBy;
    if (sortDir) params.sort_dir = sortDir;
    params.page = page;
    params.page_size = pageSize;
    return params;
  }, [guildFilters, debouncedSearch, sortBy, sortDir, page, pageSize]);

  const documentsQuery = useQuery<DocumentListResponse>({
    queryKey: ["/api/v1/documents/", documentsGlobalParams],
    queryFn: async () => {
      const response = await apiClient.get<DocumentListResponse>("/documents/", {
        params: documentsGlobalParams,
      });
      return response.data;
    },
    placeholderData: keepPreviousData,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams = { ...documentsGlobalParams, page: targetPage };

      void localQueryClient.prefetchQuery({
        queryKey: ["/api/v1/documents/", prefetchParams],
        queryFn: async () => {
          const response = await apiClient.get<DocumentListResponse>("/documents/", {
            params: prefetchParams,
          });
          return response.data;
        },
        staleTime: 30_000,
      });
    },
    [documentsGlobalParams, localQueryClient]
  );

  // Helper to create guild-scoped paths for a document
  const docGuildPath = useCallback(
    (doc: DocumentSummary, path: string) => {
      const guildId = doc.initiative?.guild_id ?? activeGuildId;
      return guildId ? guildPath(guildId, path) : path;
    },
    [activeGuildId]
  );

  const documents = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data]);

  const columns: ColumnDef<DocumentSummary>[] = useMemo(
    () => [
      {
        id: "guild",
        accessorFn: (doc) => doc.initiative?.guild_id,
        header: () => <span className="font-medium">{t("columns.guild")}</span>,
        cell: ({ row }) => {
          const doc = row.original;
          const guild = guilds.find((g) => g.id === doc.initiative?.guild_id);
          const guildName = guild?.name ?? t("myDocuments.noGuild");
          return <span className="text-muted-foreground text-sm">{guildName}</span>;
        },
        enableSorting: false,
      },
      {
        accessorKey: "title",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("columns.title")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const doc = row.original;
          return (
            <Link
              to={docGuildPath(doc, `/documents/${doc.id}`)}
              className="text-foreground flex items-center gap-2 font-medium hover:underline"
            >
              {doc.title}
              {doc.is_template && (
                <Badge variant="secondary" className="text-xs">
                  {t("type.template")}
                </Badge>
              )}
            </Link>
          );
        },
        enableSorting: true,
      },
      {
        id: "initiative",
        accessorFn: (doc) => doc.initiative?.name,
        header: () => <span className="font-medium">{t("columns.initiative")}</span>,
        cell: ({ row }) => {
          const doc = row.original;
          const initiative = doc.initiative;
          if (!initiative) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          return (
            <Link
              to={docGuildPath(doc, `/initiatives/${initiative.id}`)}
              className="text-muted-foreground flex items-center gap-2 text-sm hover:underline"
            >
              <InitiativeColorDot color={initiative.color} />
              {initiative.name}
            </Link>
          );
        },
        enableSorting: false,
      },
      {
        id: "tags",
        header: () => <span className="font-medium">{t("columns.tags")}</span>,
        cell: ({ row }) => {
          const doc = row.original;
          const docTags = doc.tags ?? [];
          if (docTags.length === 0) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          return (
            <div className="flex flex-wrap gap-1">
              {docTags.slice(0, 3).map((tag) => (
                <TagBadge
                  key={tag.id}
                  tag={tag}
                  size="sm"
                  to={docGuildPath(doc, `/tags/${tag.id}`)}
                />
              ))}
              {docTags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{docTags.length - 3}</span>
              )}
            </div>
          );
        },
        enableSorting: false,
      },
      {
        id: "updatedAt",
        accessorKey: "updated_at",
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("columns.lastUpdated")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        cell: ({ row }) => {
          const doc = row.original;
          const updatedAt = doc.updated_at ? new Date(doc.updated_at) : null;
          if (!updatedAt || isNaN(updatedAt.getTime())) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          return (
            <span className="text-muted-foreground text-sm">
              {formatDistanceToNow(updatedAt, { addSuffix: true, locale: dateLocale })}
            </span>
          );
        },
        enableSorting: true,
      },
    ],
    [t, guilds, docGuildPath, dateLocale]
  );

  // Responsive filter visibility
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const mediaQuery = window.matchMedia("(min-width: 640px)");
    const handleChange = (event: MediaQueryListEvent) => {
      setFiltersOpen(event.matches);
    };
    setFiltersOpen(mediaQuery.matches);
    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }
    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  const isInitialLoad = documentsQuery.isLoading && !documentsQuery.data;
  const isRefetching = documentsQuery.isFetching && !isInitialLoad;
  const hasError = documentsQuery.isError;

  const totalCount = documentsQuery.data?.total_count ?? 0;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("myDocuments.title")}</h1>
          <p className="text-muted-foreground">{t("myDocuments.subtitle")}</p>
        </div>

        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
          <div className="flex items-center justify-between sm:hidden">
            <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
              <Filter className="h-4 w-4" />
              {t("myDocuments.filters")}
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {filtersOpen ? t("myDocuments.hideFilters") : t("myDocuments.showFilters")}
                <ChevronDown
                  className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
                />
              </Button>
            </CollapsibleTrigger>
          </div>
          <CollapsibleContent forceMount className="data-[state=closed]:hidden">
            <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="doc-guild-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("myDocuments.filterByGuild")}
                </Label>
                <MultiSelect
                  selectedValues={guildFilters.map(String)}
                  options={guilds.map((guild) => ({
                    value: String(guild.id),
                    label: guild.name,
                  }))}
                  onChange={(values) => {
                    const numericValues = values.map(Number).filter(Number.isFinite);
                    setGuildFilters(numericValues);
                  }}
                  placeholder={t("myDocuments.allGuilds")}
                  emptyMessage={t("myDocuments.noGuilds")}
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="doc-search"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("myDocuments.searchPlaceholder")}
                </Label>
                <div className="relative">
                  <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="doc-search"
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t("myDocuments.searchPlaceholder")}
                    className="pl-9"
                  />
                </div>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        <div className="relative">
          {isRefetching ? (
            <div className="bg-background/60 absolute inset-0 z-10 flex items-start justify-center pt-4">
              <div className="bg-background border-border flex items-center gap-2 rounded-md border px-4 py-2 shadow-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-muted-foreground text-sm">{t("myDocuments.updating")}</span>
              </div>
            </div>
          ) : null}
          {isInitialLoad ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : hasError ? (
            <p className="text-destructive py-8 text-center text-sm">
              {t("myDocuments.loadError")}
            </p>
          ) : documents.length === 0 && !debouncedSearch && guildFilters.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {t("myDocuments.empty")}
            </p>
          ) : (
            <DataTable
              columns={columns}
              data={documents}
              enablePagination
              manualPagination
              manualSorting
              onSortingChange={handleSortingChange}
              pageCount={totalPages}
              rowCount={totalCount}
              onPaginationChange={(pag) => {
                if (pag.pageSize !== pageSize) {
                  setPageSize(pag.pageSize);
                  setPage(1);
                } else {
                  setPage(pag.pageIndex + 1);
                }
              }}
              onPrefetchPage={(pageIndex) => prefetchPage(pageIndex + 1)}
            />
          )}
        </div>
      </div>
    </PullToRefresh>
  );
};
