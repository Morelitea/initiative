/**
 * THE index page a tool's entities are browsed from — one initiative's shelf of
 * wikis, galleries, queues, counter groups or dashboards.
 *
 * Each of those pages carried its own copy of the same thing: the archive
 * toggle, the filter panel, the create button and its dialog, the loading,
 * error, narrowed and empty states, the card grid, and bulk selection. What a
 * tool actually contributes is narrow — which list it reads, what a row looks
 * like, and the handful of keys it spells its own way — and that is what
 * {@link TOOL_INDEX} carries. It is a `Record<Tool, …>`, so a new tool cannot
 * arrive without saying either how it lists or what it does instead.
 *
 * Everything else is derived rather than declared per tool, the way
 * `lib/tools.ts` asks: the import action reads the registry's exportable set,
 * the marketplace button reads its listing kinds, the archive toggle reads its
 * icons, and the field ids and routes come from the tool's own spelling rules.
 */

import { useRouter, useSearch } from "@tanstack/react-router";
import type { FlatNamespace } from "i18next";
import { Plus } from "lucide-react";
import { type ComponentType, type ReactNode, useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import type { BulkAccessItem } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { CounterGroupCard } from "@/components/initiativeTools/counters/CounterGroupCard";
import { CreateCounterGroupDialog } from "@/components/initiativeTools/counters/CreateCounterGroupDialog";
import { CreateDashboardDialog } from "@/components/initiativeTools/dashboards/CreateDashboardDialog";
import { DashboardCard } from "@/components/initiativeTools/dashboards/DashboardCard";
import { CreateGalleryDialog } from "@/components/initiativeTools/galleries/CreateGalleryDialog";
import { GalleryCard } from "@/components/initiativeTools/galleries/GalleryCard";
import { CreateQueueDialog } from "@/components/initiativeTools/queues/CreateQueueDialog";
import { QueueCard } from "@/components/initiativeTools/queues/QueueCard";
import {
  archivedParam,
  ToolArchiveFilter,
  type ToolArchiveState,
} from "@/components/initiativeTools/shared/ToolArchiveFilter";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { CreateWikiDialog } from "@/components/initiativeTools/wikis/CreateWikiDialog";
import { WikiCard } from "@/components/initiativeTools/wikis/WikiCard";
import { BrowseMarketplaceButton } from "@/components/marketplace/BrowseMarketplaceButton";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { PaginationBar } from "@/components/PaginationBar";
import { CardGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDashboardsList } from "@/hooks/useDashboards";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGalleriesList } from "@/hooks/useGalleries";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useQueuesList } from "@/hooks/useQueues";
import { useWikisList } from "@/hooks/useWikis";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute, toolKebabSingular } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

// ---------------------------------------------------------------------------
// What a tool contributes
// ---------------------------------------------------------------------------

/**
 * One row, as the shared page needs it: enough to key it, label it, select it
 * and share it — plus the card its own tool drew for it.
 *
 * Drawing happens inside the tool's list hook, where the row's real type is
 * known, so no tool's schema has to travel through this file.
 */
export type ToolIndexRow = BulkAccessItem & {
  name: string;
  my_permission_level?: string | null;
  card: ReactNode;
};

/** How the shared page has narrowed the list, handed to the tool's list hook. */
export type ToolIndexFilters = {
  /**
   * The search box after a beat's pause — for a tool whose endpoint does the
   * matching, so a keystroke is not a request.
   */
  search: string;
  /**
   * The search box as typed — for a tool that matches the loaded page in the
   * browser, where waiting would only make the list lag the cursor.
   */
  searchQuery: string;
  /** Tags to narrow by, for a tool whose endpoint takes them. */
  tagIds: number[];
  /** `true` on the archive view, omitted on the live one. */
  archived: true | undefined;
  /** The page and its size, for a tool whose list is paged. */
  page: number;
  pageSize: number;
};

/** What a tool's list hook hands back. */
export type ToolIndexList = {
  rows: ToolIndexRow[];
  isLoading: boolean;
  isError: boolean;
  /** Rows the server holds for this archive state — what the pager counts. */
  totalCount: number;
  hasNext: boolean;
  /**
   * A filter only this tool has, e.g. a queue's active/inactive select. It
   * sits beside the shared search box, counts towards the filter button's
   * badge, and clears with "Clear all".
   */
  extraFilter?: { field: ReactNode; active: boolean; clear: () => void };
};

/**
 * A tool's create dialog as this page uses it. Every tool's dialog resolves a
 * richer entity than `{ id }`; naming only the id here keeps this file free of
 * nine schemas, and a dialog that returns more still satisfies it.
 */
type ToolCreateDialog = ComponentType<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initiativeId?: number;
  onSuccess?: (created: { id: number }) => void;
}>;

/** Everything one tool adds to the shared page. */
export type ToolIndexEntry = {
  /** Reads this tool's list and draws its cards. */
  useList: (initiativeId: number, filters: ToolIndexFilters) => ToolIndexList;
  CreateDialog: ToolCreateDialog;
  /**
   * The keys this tool spells its own way. Kept per tool rather than folded
   * into one generic string: "No counter groups match your filters" is written
   * in four locales already, and a shared wording would be a fifth thing to
   * translate that says less.
   */
  text: {
    ns: FlatNamespace;
    /** Title of the create button, the bottom-nav action, and the dialog. */
    create: string;
    searchPlaceholder: string;
    noMatches: string;
    emptyTitle: string;
    emptyBody: string;
  };
  /** Every tool list takes `tag_ids`; the flag exists so an entry can opt out. */
  tagFilter?: boolean;
  /** Its list arrives a page at a time, and the page is carried in the URL. */
  paginated?: boolean;
  /** Makes this tool's lists stale after a bulk sharing change. */
  invalidate: () => void;
};

/** A tool that is not browsed as a grid of cards, and what it is instead. */
type ToolIndexOwnPage = { ownPage: string };

const isOwnPage = (entry: ToolIndexEntry | ToolIndexOwnPage): entry is ToolIndexOwnPage =>
  "ownPage" in entry;

/** This page's entry for a tool, or null when the tool has a page of its own. */
export const toolIndexEntry = (tool: Tool): ToolIndexEntry | null => {
  const entry = TOOL_INDEX[tool];
  return isOwnPage(entry) ? null : entry;
};

// ---------------------------------------------------------------------------
// Each tool's list
// ---------------------------------------------------------------------------

const useWikiRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const search = filters.search.trim();
  const query = useWikisList({
    initiative_id: initiativeId,
    archived: filters.archived,
    ...(search ? { search } : {}),
    ...(filters.tagIds.length > 0 ? { tag_ids: filters.tagIds } : {}),
  });

  const rows = useMemo(
    () => (query.data?.items ?? []).map((wiki) => ({ ...wiki, card: <WikiCard wiki={wiki} /> })),
    [query.data]
  );

  return {
    rows,
    isLoading: query.isLoading,
    isError: query.isError,
    totalCount: query.data?.total_count ?? 0,
    hasNext: query.data?.has_next ?? false,
  };
};

const useGalleryRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const search = filters.search.trim();
  const query = useGalleriesList({
    initiative_id: initiativeId,
    archived: filters.archived,
    ...(search ? { search } : {}),
    ...(filters.tagIds.length > 0 ? { tag_ids: filters.tagIds } : {}),
  });

  const rows = useMemo(
    () =>
      (query.data?.items ?? []).map((gallery) => ({
        ...gallery,
        card: <GalleryCard gallery={gallery} />,
      })),
    [query.data]
  );

  return {
    rows,
    isLoading: query.isLoading,
    isError: query.isError,
    totalCount: query.data?.total_count ?? 0,
    hasNext: query.data?.has_next ?? false,
  };
};

/** What a queue list is showing: everything, or only what is running. */
type QueueStatusFilter = "all" | "active" | "inactive";

const useQueueRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const { t } = useTranslation("queues");
  const [statusFilter, setStatusFilter] = useState<QueueStatusFilter>("all");

  const query = useQueuesList({
    initiative_id: initiativeId,
    archived: filters.archived,
    page: filters.page,
    page_size: filters.pageSize,
    ...(filters.tagIds.length > 0 ? { tag_ids: filters.tagIds } : {}),
  });

  const rows = useMemo(() => {
    const search = filters.searchQuery.trim().toLowerCase();
    return (query.data?.items ?? [])
      .filter((queue) => {
        const matchesSearch = !search || queue.name.toLowerCase().includes(search);
        const matchesStatus =
          statusFilter === "all" ||
          (statusFilter === "active" && queue.is_active) ||
          (statusFilter === "inactive" && !queue.is_active);
        return matchesSearch && matchesStatus;
      })
      .map((queue) => ({ ...queue, card: <QueueCard queue={queue} /> }));
  }, [query.data, filters.searchQuery, statusFilter]);

  return {
    rows,
    isLoading: query.isLoading,
    isError: query.isError,
    totalCount: query.data?.total_count ?? 0,
    hasNext: query.data?.has_next ?? false,
    extraFilter: {
      active: statusFilter !== "all",
      clear: () => setStatusFilter("all"),
      field: (
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="queue-status-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("filters.status")}
          </Label>
          <Select
            value={statusFilter}
            onValueChange={(value) => setStatusFilter(value as QueueStatusFilter)}
          >
            <SelectTrigger id="queue-status-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("filters.allStatuses")}</SelectItem>
              <SelectItem value="active">{t("filters.activeOnly")}</SelectItem>
              <SelectItem value="inactive">{t("filters.inactiveOnly")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      ),
    },
  };
};

/**
 * Rows a whole shelf at a time. Counter groups and dashboards ask for fifty and
 * match names in the browser, which is why neither shows a pager.
 */
const WHOLE_SHELF = { page: 1, page_size: 50 } as const;

const useCounterGroupRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useCounterGroupsList({
    initiative_id: initiativeId,
    archived: filters.archived,
    ...WHOLE_SHELF,
    ...(filters.tagIds.length > 0 ? { tag_ids: filters.tagIds } : {}),
  });

  const rows = useMemo(() => {
    const search = filters.searchQuery.trim().toLowerCase();
    return (query.data?.items ?? [])
      .filter((group) => !search || group.name.toLowerCase().includes(search))
      .map((group) => ({ ...group, card: <CounterGroupCard group={group} /> }));
  }, [query.data, filters.searchQuery]);

  return {
    rows,
    isLoading: query.isLoading,
    isError: query.isError,
    totalCount: query.data?.total_count ?? 0,
    hasNext: query.data?.has_next ?? false,
  };
};

const useDashboardRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useDashboardsList({
    initiative_id: initiativeId,
    archived: filters.archived,
    ...WHOLE_SHELF,
    ...(filters.tagIds.length > 0 ? { tag_ids: filters.tagIds } : {}),
  });

  const rows = useMemo(() => {
    const search = filters.searchQuery.trim().toLowerCase();
    return (query.data?.items ?? [])
      .filter((dashboard) => !search || dashboard.name.toLowerCase().includes(search))
      .map((dashboard) => ({ ...dashboard, card: <DashboardCard dashboard={dashboard} /> }));
  }, [query.data, filters.searchQuery]);

  return {
    rows,
    isLoading: query.isLoading,
    isError: query.isError,
    totalCount: query.data?.total_count ?? 0,
    hasNext: query.data?.has_next ?? false,
  };
};

// ---------------------------------------------------------------------------
// The table
// ---------------------------------------------------------------------------

/**
 * Every tool, and how one initiative's entities of it are browsed. A tool with
 * a page of its own names it here rather than being left out, so a new tool has
 * to state which of the two it is.
 */
export const TOOL_INDEX: Record<Tool, ToolIndexEntry | ToolIndexOwnPage> = {
  [Tool.project]: { ownPage: "ProjectsPage — board and table views, and its own status filters" },
  [Tool.document]: { ownPage: "DocumentsPage — folders, and a tree beside the list" },
  [Tool.calendar]: { ownPage: "CalendarsPage — a month grid, not a shelf of cards" },
  [Tool.post]: { ownPage: "PostsPage — a virtualized feed with a timeline rail" },

  [Tool.queue]: {
    useList: useQueueRows,
    tagFilter: true,
    CreateDialog: CreateQueueDialog,
    text: {
      ns: "queues",
      create: "createQueue",
      searchPlaceholder: "filters.searchQueues",
      noMatches: "filters.noMatchingQueues",
      emptyTitle: "noQueues",
      emptyBody: "noQueuesDescription",
    },
    paginated: true,
    invalidate: () => invalidate(q.allQueues()),
  },

  [Tool.counter_group]: {
    useList: useCounterGroupRows,
    tagFilter: true,
    CreateDialog: CreateCounterGroupDialog,
    text: {
      ns: "counterGroups",
      create: "createGroup",
      searchPlaceholder: "filters.searchGroups",
      noMatches: "filters.noMatchingGroups",
      emptyTitle: "noGroups",
      emptyBody: "noGroupsDescription",
    },
    invalidate: () => invalidate(q.allCounterGroups()),
  },

  [Tool.dashboard]: {
    useList: useDashboardRows,
    tagFilter: true,
    CreateDialog: CreateDashboardDialog,
    text: {
      ns: "dashboards",
      create: "createDashboard",
      searchPlaceholder: "filters.searchDashboards",
      noMatches: "filters.noMatchingDashboards",
      emptyTitle: "noDashboards",
      emptyBody: "noDashboardsDescription",
    },
    invalidate: () => invalidate(q.allDashboards()),
  },

  [Tool.gallery]: {
    useList: useGalleryRows,
    tagFilter: true,
    CreateDialog: CreateGalleryDialog,
    text: {
      ns: "galleries",
      create: "createGallery",
      searchPlaceholder: "filters.searchGalleries",
      noMatches: "filters.noMatchingGalleries",
      emptyTitle: "noGalleries",
      emptyBody: "noGalleriesDescription",
    },
    invalidate: () => invalidate(q.allGalleries()),
  },

  [Tool.wiki]: {
    useList: useWikiRows,
    CreateDialog: CreateWikiDialog,
    text: {
      ns: "wikis",
      create: "createWiki",
      searchPlaceholder: "filters.searchWikis",
      noMatches: "filters.noMatchingWikis",
      emptyTitle: "noWikis",
      emptyBody: "noWikisDescription",
    },
    tagFilter: true,
    invalidate: () => invalidate(q.allWikis()),
  },
};

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

/**
 * Which page of the list is showing, kept in the URL so a deep link lands on it
 * and the back button walks through the pages that were read. Inert for a tool
 * whose whole shelf arrives at once — the URL keeps no page it cannot turn.
 */
const useListPage = (paginated: boolean) => {
  const router = useRouter();
  const search = useSearch({ strict: false }) as { create?: string; page?: number };

  // Read from the click handler, so the newest URL is the one written back to.
  const searchRef = useRef(search);
  searchRef.current = search;

  const [page, setPageState] = useState(() => search.page ?? 1);
  const [pageSize, setPageSize] = useState(20);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
      if (!paginated) return;
      setPageState((prev) => {
        const next = typeof updater === "function" ? updater(prev) : updater;
        void router.navigate({
          to: ".",
          search: { ...searchRef.current, page: next <= 1 ? undefined : next },
          replace: true,
        });
        return next;
      });
    },
    [router, paginated]
  );

  return { page, pageSize, setPage, setPageSize };
};

export type ToolIndexPageProps = {
  tool: Tool;
  /** The initiative this list belongs to. Required: a tool's entities are only
   *  ever browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

type ToolIndexBodyProps = ToolIndexPageProps & { entry: ToolIndexEntry };

const ToolIndexBody = ({ tool, entry, fixedInitiativeId, canCreate }: ToolIndexBodyProps) => {
  // The namespace and most of the keys come from the table, so the loose
  // translate signature rather than the statically-typed one.
  const { t: translate } = useTranslation([entry.text.ns, "common", "tags"]);
  const t = translate as TranslateFn;
  const router = useRouter();
  const gp = useGuildPath();

  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilters, setTagFilters] = useState<TagSummary[]>([]);
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(searchQuery, 300);

  // Which of the tool's two states the list is showing. Archived rows are off
  // the live list, so this is the only place they can be reached.
  const [archiveState, setArchiveState] = useState<ToolArchiveState>("active");

  const { page, pageSize, setPage, setPageSize } = useListPage(Boolean(entry.paginated));

  const list = entry.useList(fixedInitiativeId, {
    search,
    searchQuery,
    tagIds: tagFilters.map((tag) => tag.id),
    archived: archivedParam(archiveState),
    page,
    pageSize,
  });

  // Canonical create answer: this initiative's server-computed create flag. An
  // explicit canCreate prop (e.g. from InitiativeDetailPage) wins.
  const { canCreate: canCreateDerived } = useToolCreateAccess(tool, {
    initiativeId: fixedInitiativeId,
  });
  const canCreateHere = canCreate ?? canCreateDerived;

  const {
    open: createOpen,
    setOpen: setCreateOpen,
    onOpenChange: handleCreateOpenChange,
  } = useCreateFromSearchParam();

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateHere ? { run: () => setCreateOpen(true), label: t(entry.text.create) } : null
  );

  const selection = useGridSelection<ToolIndexRow>(list.rows);
  const importAction = useToolImportAction({
    tool,
    canImport: canCreateHere,
    fixedInitiativeId,
  });

  // Counted from the box as typed rather than from the debounced value, so the
  // badge and "Clear all" answer the keystroke instead of trailing it by a beat.
  const activeFilterCount =
    (searchQuery.trim() ? 1 : 0) +
    (tagFilters.length > 0 ? 1 : 0) +
    (list.extraFilter?.active ? 1 : 0);

  const clearFilters = () => {
    setSearchQuery("");
    setTagFilters([]);
    list.extraFilter?.clear();
  };

  const CreateDialog = entry.CreateDialog;
  const searchId = `${toolKebabSingular(tool)}-search`;
  const tagsId = `${toolKebabSingular(tool)}-tags`;

  return (
    <div className="space-y-6">
      <ToolListToolbar
        leading={
          <ToolArchiveFilter
            tool={tool}
            value={archiveState}
            onChange={(next) => {
              setArchiveState(next);
              // The other state's cursor means nothing in this one: switching
              // from page 3 of the live list into a one-page archive would
              // land on an empty page with the archive sitting on page 1.
              setPage(1);
            }}
          />
        }
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        actions={
          canCreateHere ? (
            <Button variant="outline" size="sm" className="h-9" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t(entry.text.create)}
            </Button>
          ) : null
        }
        trailing={canCreateHere ? <BrowseMarketplaceButton tool={tool} /> : null}
        menuItems={importAction.menuItem}
        onEnterSelection={!selection.active && list.rows.length > 0 ? selection.enter : undefined}
      />
      {importAction.dialog}

      <ToolFilterPanel
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        title={t("filters.heading")}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      >
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-full space-y-2 lg:flex-1">
            <Label htmlFor={searchId} className="block font-medium text-muted-foreground text-xs">
              {t("filters.searchLabel")}
            </Label>
            <Input
              id={searchId}
              placeholder={t(entry.text.searchPlaceholder)}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="min-w-60"
            />
          </div>
          {entry.tagFilter ? (
            <div className="w-full space-y-2 sm:w-64">
              <Label htmlFor={tagsId} className="block font-medium text-muted-foreground text-xs">
                {t("tags:picker.filterLabel")}
              </Label>
              <TagPicker
                id={tagsId}
                variant="filter"
                selectedTags={tagFilters}
                onChange={setTagFilters}
                placeholder={t("tags:picker.anyTag")}
              />
            </div>
          ) : null}
          {list.extraFilter?.field}
        </div>
      </ToolFilterPanel>

      {list.isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <CardGridSkeleton />
        </SkeletonRegion>
      ) : list.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : list.rows.length > 0 ? (
        <>
          <BulkAccessSection selection={selection} tool={tool} invalidate={entry.invalidate} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {list.rows.map((row) => (
              <SelectableGridItem
                key={row.id}
                active={selection.active}
                selected={selection.selectedIds.has(row.id)}
                onToggle={(options) => selection.toggle(row, options)}
                label={row.name}
              >
                {row.card}
              </SelectableGridItem>
            ))}
          </div>

          {entry.paginated ? (
            <PaginationBar
              page={page}
              pageSize={pageSize}
              totalCount={list.totalCount}
              hasNext={list.hasNext}
              onPageChange={setPage}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(1);
              }}
            />
          ) : null}
        </>
      ) : activeFilterCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t(entry.text.noMatches)}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t(entry.text.emptyTitle)}</CardTitle>
            <CardDescription>{t(entry.text.emptyBody)}</CardDescription>
          </CardHeader>
          {/* The other ways to end up with one, said where the answer is
              needed: an initiative with none of them yet. Each reads the
              registry and shows nothing for a tool it does not apply to. */}
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={() => setCreateOpen(true)} disabled={!canCreateHere}>
              <Plus className="h-4 w-4" />
              {t("createFirst")}
            </Button>
            <ToolImportAction
              tool={tool}
              canImport={canCreateHere}
              fixedInitiativeId={fixedInitiativeId}
              variant="button"
            />
            {canCreateHere ? <BrowseMarketplaceButton tool={tool} size="default" /> : null}
          </CardContent>
        </Card>
      )}

      <CreateDialog
        open={createOpen}
        onOpenChange={handleCreateOpenChange}
        initiativeId={fixedInitiativeId}
        onSuccess={(created) => {
          void router.navigate({
            to: gp(toolDetailRoute(tool, fixedInitiativeId, created.id)),
          });
        }}
      />
    </div>
  );
};

export const ToolIndexPage = ({ tool, ...rest }: ToolIndexPageProps) => {
  const entry = TOOL_INDEX[tool];
  // A tool with a page of its own is never routed here; the table names which
  // those are.
  if (isOwnPage(entry)) return null;

  // Keyed on the tool: the table supplies the list hook, so a different tool is
  // a different set of hooks. Remounting is what makes that sound — and it is
  // also what somebody switching tabs expects, filters and all.
  return <ToolIndexBody key={tool} tool={tool} entry={entry} {...rest} />;
};
