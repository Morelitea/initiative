import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { keepPreviousData } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { ChevronDown, Filter, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatDistanceToNow } from "date-fns";
import { useDateLocale } from "@/hooks/useDateLocale";

import { invalidateAllProjects } from "@/api/query-keys";
import { useGlobalProjects, usePrefetchGlobalProjects } from "@/hooks/useProjects";
import { getItem, setItem } from "@/lib/storage";
import { guildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useGuilds } from "@/hooks/useGuilds";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DataTable } from "@/components/ui/data-table";
import { SortIcon } from "@/components/SortIcon";
import { PullToRefresh } from "@/components/PullToRefresh";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { TagBadge } from "@/components/tags/TagBadge";
import type {
  ListGlobalProjectsApiV1ProjectsGlobalGetParams,
  ProjectRead,
} from "@/api/generated/initiativeAPI.schemas";

const MY_PROJECTS_FILTERS_KEY = "initiative-my-projects-filters";
const FILTER_DEFAULTS = {
  guildFilters: [] as number[],
};

/** Map DataTable column IDs to backend sort field names */
const SORT_FIELD_MAP: Record<string, string> = {
  name: "name",
  updated: "updated_at",
};

const readStoredFilters = () => {
  try {
    const raw = getItem(MY_PROJECTS_FILTERS_KEY);
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

const PAGE_SIZE = 20;

export const MyProjectsPage = () => {
  const { t } = useTranslation(["projects", "common"]);
  const { guilds } = useGuilds();
  const prefetchGlobalProjects = usePrefetchGlobalProjects();
  const dateLocale = useDateLocale();
  const router = useRouter();
  const searchParams = useSearch({ strict: false }) as { page?: number };
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;

  const handleRefresh = useCallback(async () => {
    await invalidateAllProjects();
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

  // Debounce search input
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1);
  }, [guildFilters, debouncedSearch, setPage]);

  // Persist filters to localStorage
  useEffect(() => {
    const payload = { guildFilters };
    setItem(MY_PROJECTS_FILTERS_KEY, JSON.stringify(payload));
  }, [guildFilters]);

  // Build guild lookup for display
  const guildsById = useMemo(() => {
    const map: Record<number, { name: string }> = {};
    guilds.forEach((guild) => {
      map[guild.id] = { name: guild.name };
    });
    return map;
  }, [guilds]);

  const projectsGlobalParams = useMemo(() => {
    const params: ListGlobalProjectsApiV1ProjectsGlobalGetParams = {};
    if (guildFilters.length > 0) params.guild_ids = guildFilters;
    if (debouncedSearch) params.search = debouncedSearch;
    if (sortBy) params.sort_by = sortBy;
    if (sortDir) params.sort_dir = sortDir;
    params.page = page;
    params.page_size = pageSize;
    return params;
  }, [guildFilters, debouncedSearch, sortBy, sortDir, page, pageSize]);

  const projectsQuery = useGlobalProjects(projectsGlobalParams, {
    placeholderData: keepPreviousData,
  });

  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams = { ...projectsGlobalParams, page: targetPage };
      void prefetchGlobalProjects(prefetchParams);
    },
    [projectsGlobalParams, prefetchGlobalProjects]
  );

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);

  const getGuildName = useCallback(
    (project: ProjectRead): string => {
      const guildId = project.initiative?.guild_id;
      if (guildId && guildsById[guildId]) {
        return guildsById[guildId].name;
      }
      return "";
    },
    [guildsById]
  );

  const getProjectGuildId = useCallback((project: ProjectRead): number | null => {
    return project.initiative?.guild_id ?? null;
  }, []);

  const columns: ColumnDef<ProjectRead>[] = useMemo(
    () => [
      {
        id: "guild",
        accessorFn: (project) => getGuildName(project),
        header: () => <span className="font-medium">{t("myProjects.columns.guild")}</span>,
        cell: ({ getValue }) => (
          <span className="text-muted-foreground text-sm">{getValue<string>()}</span>
        ),
        enableSorting: false,
      },
      {
        id: "name",
        accessorFn: (project) => project.name,
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("myProjects.columns.project")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        enableSorting: true,
        cell: ({ row }) => {
          const project = row.original;
          const guildId = getProjectGuildId(project);
          const href = guildId
            ? guildPath(guildId, `/projects/${project.id}`)
            : `/projects/${project.id}`;
          return (
            <Link
              to={href}
              className="text-foreground flex items-center gap-2 font-medium hover:underline"
            >
              {project.icon ? (
                <span className="text-base" aria-hidden="true">
                  {project.icon}
                </span>
              ) : null}
              {project.name}
            </Link>
          );
        },
      },
      {
        id: "initiative",
        accessorFn: (project) => project.initiative?.name ?? "",
        header: () => <span className="font-medium">{t("myProjects.columns.initiative")}</span>,
        cell: ({ row }) => {
          const project = row.original;
          const initiative = project.initiative;
          if (!initiative) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          const guildId = getProjectGuildId(project);
          const href = guildId
            ? guildPath(guildId, `/initiatives/${initiative.id}`)
            : `/initiatives/${initiative.id}`;
          return (
            <Link
              to={href}
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
        id: "tasks",
        header: () => <span className="font-medium">{t("myProjects.columns.tasks")}</span>,
        cell: ({ row }) => {
          const summary = row.original.task_summary;
          if (!summary || summary.total === 0) {
            return <span className="text-muted-foreground text-sm">{t("myProjects.noTasks")}</span>;
          }
          return (
            <span className="text-sm">
              {t("myProjects.tasksDone", {
                completed: summary.completed,
                total: summary.total,
              })}
            </span>
          );
        },
        enableSorting: false,
      },
      {
        id: "tags",
        header: () => <span className="font-medium">{t("myProjects.columns.tags")}</span>,
        cell: ({ row }) => {
          const project = row.original;
          const projectTags = project.tags ?? [];
          if (projectTags.length === 0) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          const guildId = getProjectGuildId(project);
          return (
            <div className="flex flex-wrap gap-1">
              {projectTags.slice(0, 3).map((tag) => (
                <TagBadge
                  key={tag.id}
                  tag={tag}
                  size="sm"
                  to={guildId ? guildPath(guildId, `/tags/${tag.id}`) : `/tags/${tag.id}`}
                />
              ))}
              {projectTags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{projectTags.length - 3}</span>
              )}
            </div>
          );
        },
        enableSorting: false,
      },
      {
        id: "updated",
        accessorFn: (project) => project.updated_at,
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
                {t("myProjects.columns.updated")}
                <SortIcon isSorted={isSorted} />
              </Button>
            </div>
          );
        },
        enableSorting: true,
        cell: ({ row }) => {
          const updatedAt = row.original.updated_at;
          if (!updatedAt) {
            return <span className="text-muted-foreground text-sm">&mdash;</span>;
          }
          return (
            <span className="text-muted-foreground text-sm">
              {formatDistanceToNow(new Date(updatedAt), { addSuffix: true, locale: dateLocale })}
            </span>
          );
        },
      },
    ],
    [t, getGuildName, getProjectGuildId, dateLocale]
  );

  // Responsive filter collapsible
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

  const isInitialLoad = projectsQuery.isLoading && !projectsQuery.data;
  const isRefetching = projectsQuery.isFetching && !isInitialLoad;
  const hasError = projectsQuery.isError;

  const totalCount = projectsQuery.data?.total_count ?? 0;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("myProjects.title")}</h1>
          <p className="text-muted-foreground">{t("myProjects.subtitle")}</p>
        </div>

        <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
          <div className="flex items-center justify-between sm:hidden">
            <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
              <Filter className="h-4 w-4" />
              {t("projects:filters.heading")}
            </div>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 px-3">
                {filtersOpen ? t("projects:filters.hide") : t("projects:filters.show")}
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
                  htmlFor="project-guild-filter"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("myProjects.filterByGuild")}
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
                  placeholder={t("myProjects.allGuilds")}
                  emptyMessage={t("myProjects.noGuilds")}
                />
              </div>
              <div className="w-full sm:w-60 lg:flex-1">
                <Label
                  htmlFor="project-search"
                  className="text-muted-foreground mb-2 block text-xs font-medium"
                >
                  {t("myProjects.searchPlaceholder")}
                </Label>
                <div className="relative">
                  <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="project-search"
                    type="search"
                    placeholder={t("myProjects.searchPlaceholder")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
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
                <span className="text-muted-foreground text-sm">{t("common:loading")}</span>
              </div>
            </div>
          ) : null}
          {isInitialLoad ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : hasError ? (
            <p className="text-destructive py-8 text-center text-sm">{t("myProjects.loadError")}</p>
          ) : projects.length === 0 && !debouncedSearch && guildFilters.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {t("myProjects.empty")}
            </p>
          ) : (
            <DataTable
              columns={columns}
              data={projects}
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
