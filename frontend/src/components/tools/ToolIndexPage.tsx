/**
 * THE index page a tool's entities are browsed from — one initiative's shelf of
 * documents, wikis, galleries, queues, counter groups or dashboards.
 *
 * Each of those pages carried its own copy of the same thing: the view toggle,
 * the filter panel, the create button and its dialog, the loading, error,
 * narrowed and empty states, the card grid, and bulk selection. What a tool
 * actually contributes is narrow — which list it reads, what a row looks like,
 * the handful of keys it spells its own way, and the few things only some
 * tools do (a dialog of their own, files dropped on the list, a table) — and
 * that is what {@link TOOL_INDEX} carries. It is a `Record<Tool, …>`, so a new
 * tool cannot arrive without saying either how it lists or what it does
 * instead.
 *
 * Everything else is derived rather than declared per tool, the way
 * `lib/tools.ts` asks: the views read the registry's view specs, the import
 * action its exportable set, the marketplace button its listing kinds, the
 * bulk actions its hooks, and the field ids and routes come from the tool's own
 * spelling rules.
 */

import { Link, useRouter, useSearch } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import type { FlatNamespace } from "i18next";
import { LayoutGrid, List, Plus, Tags } from "lucide-react";
import {
  type ComponentType,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { type PropertySummary, type TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { BulkAccessSection } from "@/components/access/BulkAccessSection";
import type { BulkAccessItem } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { useDocumentColumns } from "@/components/documents/documentColumns";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import { CounterGroupCard } from "@/components/initiativeTools/counters/CounterGroupCard";
import { DashboardCard } from "@/components/initiativeTools/dashboards/DashboardCard";
import { GalleryCard } from "@/components/initiativeTools/galleries/GalleryCard";
import { QueueCard } from "@/components/initiativeTools/queues/QueueCard";
import { CreateToolDialog } from "@/components/initiativeTools/shared/CreateToolDialog";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { ToolViewFilter } from "@/components/initiativeTools/shared/ToolViewFilter";
import { WikiCard } from "@/components/initiativeTools/wikis/WikiCard";
import {
  BrowseMarketplaceButton,
  BrowseMarketplaceMenuItem,
} from "@/components/marketplace/BrowseMarketplaceButton";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { PaginationBar } from "@/components/PaginationBar";
import { parsePropertyFilters } from "@/components/properties/PropertyFilter";
import { CardGridSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TagBrowseLayout } from "@/components/tags/TagBrowseLayout";
import { ToolFilterFields, type ToolListFilters } from "@/components/tools/ToolFilterFields";
import {
  TABLE_SORT_FIELDS,
  ToolIndexTable,
  toolTableStorageKey,
} from "@/components/tools/ToolIndexTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DropOverlay } from "@/components/ui/file-drop";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCounterGroupsList } from "@/hooks/useCounters";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDashboardsList } from "@/hooks/useDashboards";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useDocumentsList } from "@/hooks/useDocuments";
import { useFileDrop } from "@/hooks/useFileDrop";
import { useGalleriesList } from "@/hooks/useGalleries";
import { useGridSelection } from "@/hooks/useGridSelection";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { usePersistedTableState } from "@/hooks/usePersistedTableState";
import { useQueuesList } from "@/hooks/useQueues";
import { useTagTreeSelection } from "@/hooks/useTagTreeSelection";
import { useToolCounts } from "@/hooks/useToolCounts";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useViewPreference } from "@/hooks/useViewPreference";
import { useWikisList } from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { DOCUMENT_UPLOAD_ACCEPT } from "@/lib/fileUtils";
import type { AppColumnDef } from "@/lib/table";
import {
  isToolView,
  TOOL_ICONS,
  type ToolView,
  type ToolViewParams,
  toolDetailRoute,
  toolListingKind,
  toolViewParams,
  toolViews,
} from "@/lib/tools";
import type { DialogProps } from "@/types/dialog";
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
  updated_at: string;
  /** Drawn on the row in the list view; every listed tool's rows carry them. */
  tags?: TagSummary[];
  /** The initiative's properties, as the table's property columns read them. */
  properties?: PropertySummary[];
  card: ReactNode;
};

type ToolIndexLayout = "grid" | "list" | "tags";
const isLayout = (value: unknown): value is ToolIndexLayout =>
  value === "grid" || value === "list" || value === "tags";

/** How the shared page has narrowed the list, handed to the tool's list hook. */
export type ToolIndexFilters = {
  /**
   * The tool's filter fields, as its list endpoint takes them: the search
   * after a beat's pause, so a keystroke is not a request, and nothing for a
   * field left empty. `untagged` only for a tool whose entry says it has it.
   */
  list: ToolListFilters & { untagged?: true };
  /** What the view being shown asks the list for (`toolViewParams`). */
  view: ToolViewParams;
  /** The order the reader picked in a tool's table; empty for the others. */
  sort: { sort_by?: string; sort_dir?: "asc" | "desc" };
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
};

/** Everything one tool adds to the shared page. */
export type ToolIndexEntry = {
  /** Reads this tool's list and draws its cards. */
  useList: (initiativeId: number, filters: ToolIndexFilters) => ToolIndexList;
  /**
   * The keys this tool spells its own way — the page's and its create
   * dialog's. Kept per tool rather than folded into one generic string: "No
   * counter groups match your filters" is written in four locales already, and
   * a shared wording would be a fifth thing to translate that says less.
   */
  text: {
    ns: FlatNamespace;
    /** Title of the create button, the bottom-nav action, and the dialog. */
    create: string;
    /** The line under the shared create dialog's title. */
    createDescription?: string;
    noMatches: string;
    emptyTitle: string;
    emptyBody: string;
  };
  /** The layout a reader starts on, before they pick one. Cards otherwise. */
  defaultLayout?: ToolIndexLayout;
  /** Cards are small tiles, several to a row, rather than three across. */
  tiles?: true;
  /** A create dialog of the tool's own, for a tool made from more than a name. */
  CreateDialog?: ComponentType<ToolIndexCreateDialogProps>;
  /** Files dropped anywhere on the list open the create dialog holding the
   *  first; `label` is the overlay's key in the tool's namespace. */
  fileDrop?: { accept: string; label: string };
  /** The list layout as a sortable table, with these columns after the shared
   *  ones. Without it the list layout is one line a row. */
  table?: { useColumns: () => AppColumnDef<ToolIndexRow>[] };
  /** The list can be narrowed to rows with no tag, which the tag tree offers. */
  untagged?: true;
};

/** What a tool's own create dialog is handed. */
export type ToolIndexCreateDialogProps = DialogProps & {
  initiativeId: number;
  onSuccess: (created: { id: number }) => void;
  /** A file dropped on the list; the dialog opens holding it. */
  initialFile: File | null;
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

const useDocumentRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useDocumentsList({
    ...filters.list,
    initiative_id: initiativeId,
    ...filters.view,
    ...filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
  });

  const rows = useMemo(
    () =>
      (query.data?.items ?? []).map((document) => ({
        ...document,
        card: <DocumentCard document={document} />,
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

const useWikiRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useWikisList({
    ...filters.list,
    initiative_id: initiativeId,
    ...filters.view,
    ...filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
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
  const query = useGalleriesList({
    ...filters.list,
    initiative_id: initiativeId,
    ...filters.view,
    ...filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
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

const useQueueRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useQueuesList({
    ...filters.list,
    initiative_id: initiativeId,
    ...filters.view,
    ...filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
    // What each card shows of what is inside it, read with the page.
    include_preview: true,
  });

  const rows = useMemo(
    () =>
      (query.data?.items ?? []).map((queue) => ({ ...queue, card: <QueueCard queue={queue} /> })),
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

const useCounterGroupRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useCounterGroupsList({
    ...filters.list,
    initiative_id: initiativeId,
    ...filters.view,
    ...filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
    // What each card shows of what is inside it, read with the page.
    include_preview: true,
  });

  const rows = useMemo(
    () =>
      (query.data?.items ?? []).map((group) => ({
        ...group,
        card: <CounterGroupCard group={group} />,
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

const useDashboardRows = (initiativeId: number, filters: ToolIndexFilters): ToolIndexList => {
  const query = useDashboardsList({
    ...filters.list,
    initiative_id: initiativeId,
    ...filters.view,
    ...filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
    // What each card shows of what is inside it, read with the page.
    include_preview: true,
  });

  const rows = useMemo(
    () =>
      (query.data?.items ?? []).map((dashboard) => ({
        ...dashboard,
        card: <DashboardCard dashboard={dashboard} />,
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

// ---------------------------------------------------------------------------
// The table
// ---------------------------------------------------------------------------

/**
 * Every tool, and how one initiative's entities of it are browsed. A tool with
 * a page of its own names it here rather than being left out, so a new tool has
 * to state which of the two it is.
 */
const TOOL_INDEX: Record<Tool, ToolIndexEntry | ToolIndexOwnPage> = {
  [Tool.project]: { ownPage: "ProjectsPage — board and table views, and its own status filters" },
  [Tool.calendar]: { ownPage: "CalendarsPage — a month grid, not a shelf of cards" },
  [Tool.post]: { ownPage: "PostsPage — a virtualized feed with a timeline rail" },

  [Tool.document]: {
    useList: useDocumentRows,
    text: {
      ns: "documents",
      create: "newDocument",
      noMatches: "filters.noMatchingDocuments",
      emptyTitle: "noDocuments",
      emptyBody: "noDocumentsDescription",
    },
    defaultLayout: "tags",
    tiles: true,
    // Made from a type, an upload, a link or a template, not just a name.
    CreateDialog: CreateDocumentDialog,
    fileDrop: { accept: DOCUMENT_UPLOAD_ACCEPT, label: "dropToUpload" },
    // The rows are documents, which is what these columns read.
    table: { useColumns: useDocumentColumns as unknown as () => AppColumnDef<ToolIndexRow>[] },
    untagged: true,
  },

  [Tool.queue]: {
    useList: useQueueRows,
    text: {
      ns: "queues",
      create: "createQueue",
      createDescription: "noQueuesDescription",
      noMatches: "filters.noMatchingQueues",
      emptyTitle: "noQueues",
      emptyBody: "noQueuesDescription",
    },
  },

  [Tool.counter_group]: {
    useList: useCounterGroupRows,
    text: {
      ns: "counterGroups",
      create: "createGroup",
      createDescription: "noGroupsDescription",
      noMatches: "filters.noMatchingGroups",
      emptyTitle: "noGroups",
      emptyBody: "noGroupsDescription",
    },
  },

  [Tool.dashboard]: {
    useList: useDashboardRows,
    text: {
      ns: "dashboards",
      create: "createDashboard",
      createDescription: "noDashboardsDescription",
      noMatches: "filters.noMatchingDashboards",
      emptyTitle: "noDashboards",
      emptyBody: "noDashboardsDescription",
    },
  },

  [Tool.gallery]: {
    useList: useGalleryRows,
    text: {
      ns: "galleries",
      create: "createGallery",
      createDescription: "createGalleryDescription",
      noMatches: "filters.noMatchingGalleries",
      emptyTitle: "noGalleries",
      emptyBody: "noGalleriesDescription",
    },
  },

  [Tool.wiki]: {
    useList: useWikiRows,
    text: {
      ns: "wikis",
      create: "createWiki",
      createDescription: "createWikiDescription",
      noMatches: "filters.noMatchingWikis",
      emptyTitle: "noWikis",
      emptyBody: "noWikisDescription",
    },
  },
};

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

/**
 * Which view and which page of the list is showing, kept in the URL so a deep
 * link lands on them and the back button walks through the ones that were read.
 */
const useListPage = (tool: Tool) => {
  const router = useRouter();
  const search = useSearch({ strict: false }) as { page?: number; status?: string };

  // Read from the click handler, so the newest URL is the one written back to.
  const searchRef = useRef(search);
  searchRef.current = search;

  // Archived rows are off the live list (and templates off it too, for a tool
  // that has them), so the view is the only place they can be reached.
  const view: ToolView =
    isToolView(search.status) && toolViews(tool).includes(search.status) ? search.status : "active";

  const [page, setPageState] = useState(() => search.page ?? 1);
  const [pageSize, setPageSize] = useState(20);

  // The cursor lives in the URL as well as in state, so a history move (Back
  // out of the archive, say) carries the list with it.
  useEffect(() => {
    const urlPage = search.page ?? 1;
    setPageState((prev) => (prev === urlPage ? prev : urlPage));
  }, [search.page]);

  const setPage = useCallback(
    (updater: number | ((prev: number) => number)) => {
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
    [router]
  );

  const setView = useCallback(
    (next: ToolView) => {
      // Pushed, not replaced: a view is somewhere the reader went, so Back
      // takes them out of it. The other view's cursor means nothing in this one.
      void router.navigate({
        to: ".",
        search: {
          ...searchRef.current,
          status: next === "active" ? undefined : next,
          page: undefined,
        },
      });
      setPageState(1);
    },
    [router]
  );

  return { view, setView, page, pageSize, setPage, setPageSize };
};

/** Newest first, the way a table opens until its reader picks an order. */
const NEWEST_FIRST: SortingState = [{ id: "updated_at", desc: true }];

/** The list's own narrowing, as the counts endpoint takes it for the tag tree:
 *  tags aside, since the tree counts every one. */
const countFilters = ({ tag_ids: _tags, ...narrowing }: ToolIndexFilters["list"]) => {
  const set = Object.entries(narrowing).filter(
    ([, value]) => value != null && value !== "" && !(Array.isArray(value) && value.length === 0)
  );
  return set.length > 0 ? JSON.stringify(Object.fromEntries(set)) : undefined;
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
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const unread = useUnreadTree();

  const [filters, setFilters] = useState<ToolListFilters>({});
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(filters.search ?? "", 300).trim();

  const { view, setView, page, pageSize, setPage, setPageSize } = useListPage(tool);
  // How the list is drawn — cards, rows or by tag — remembered per tool.
  const defaultLayout = entry.defaultLayout ?? "grid";
  const [savedLayout, setLayout] = useViewPreference<string>(`${tool}:view-mode`, defaultLayout);
  const layout: ToolIndexLayout = isLayout(savedLayout) ? savedLayout : defaultLayout;
  const tagTree = useTagTreeSelection(layout === "tags");

  // The order a reader picks in a tool's table outlives the visit, and is the
  // list's order in every layout.
  const [tableState, { setSorting }] = usePersistedTableState(toolTableStorageKey(tool, "order"), {
    sorting: NEWEST_FIRST,
  });
  const [sorted] = tableState.sorting;
  const sort =
    entry.table && sorted && TABLE_SORT_FIELDS.has(sorted.id)
      ? { sort_by: sorted.id, sort_dir: sorted.desc ? ("desc" as const) : ("asc" as const) }
      : {};

  const listFilters: ToolIndexFilters["list"] = {
    ...filters,
    search: search || undefined,
    // A tag picked in the tree narrows by it; with none picked, the
    // filter panel's tags still apply.
    tag_ids: tagTree.tagIds.length
      ? tagTree.tagIds
      : filters.tag_ids?.length
        ? filters.tag_ids
        : undefined,
    ...(entry.untagged && tagTree.wantsUntagged ? { untagged: true as const } : {}),
  };
  const list = entry.useList(fixedInitiativeId, {
    list: listFilters,
    view: toolViewParams(tool, view),
    sort,
    page,
    pageSize,
  });

  // How much sits in each view, whatever the filters say; and in the tags
  // view, how much carries each tag under the list's own filters, so the tree
  // and the list beside it agree.
  const tagCountFilters = layout === "tags" ? countFilters(listFilters) : undefined;
  const countsQuery = useToolCounts(tool, {
    initiative_id: fixedInitiativeId,
    ...(layout === "tags"
      ? { view, include_tags: true, ...(tagCountFilters ? { filters: tagCountFilters } : {}) }
      : {}),
  });

  // A page past the end (its rows deleted, a link to one that is gone) has
  // nothing on it and no pager to leave by, so the list moves to its last page.
  // A failed read says nothing about where the end is, so it moves nothing.
  const lastPage = Math.max(1, Math.ceil(list.totalCount / pageSize));
  useEffect(() => {
    if (!list.isLoading && !list.isError && list.rows.length === 0 && page > lastPage) {
      setPage(lastPage);
    }
  }, [list.isLoading, list.isError, list.rows.length, page, lastPage, setPage]);

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
  // Another view or layout must not strand a hidden selection behind the bulk
  // actions — every change starts unselected.
  const exitSelection = selection.exit;
  useEffect(() => {
    exitSelection();
  }, [view, layout, exitSelection]);

  const importAction = useToolImportAction({
    tool,
    canImport: canCreateHere,
    fixedInitiativeId,
  });

  // A file dragged in from the desktop lands wherever the cursor is, in any
  // layout, and opens the create dialog holding it. Off while a dialog is up:
  // those are portalled, and React would carry a drop on one back up to here.
  const { maxUploadBytes } = useAppConfig();
  const [droppedFile, setDroppedFile] = useState<File | null>(null);
  const drop = useFileDrop(
    Boolean(entry.fileDrop) && canCreateHere && !createOpen && !selection.active,
    ([first]) => {
      if (!first) return;
      setDroppedFile(first);
      setCreateOpen(true);
    },
    { accept: entry.fileDrop?.accept, maxBytes: maxUploadBytes }
  );
  const onCreateOpenChange = (open: boolean) => {
    if (!open) setDroppedFile(null);
    handleCreateOpenChange(open);
  };
  const openCreated = (created: { id: number }) => {
    void router.navigate({ to: gp(toolDetailRoute(tool, fixedInitiativeId, created.id)) });
  };

  // Counted from the fields as set rather than from the debounced search, so
  // the badge and "Clear all" answer the keystroke instead of trailing it.
  // Each property condition counts as a filter of its own.
  const { property_filters: propertyFilters, ...fields } = filters;
  const activeFilterCount =
    Object.values(fields).filter((value) =>
      Array.isArray(value)
        ? value.length > 0
        : typeof value === "string"
          ? value.trim()
          : value != null
    ).length + parsePropertyFilters(propertyFilters).length;

  const ToolIcon = TOOL_ICONS[tool];
  // The cards, as the grid and the tags view both draw them.
  const cards = (
    <div
      className={
        entry.tiles
          ? layout === "tags"
            ? "grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4"
            : "grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
          : layout === "tags"
            ? "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
            : "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      }
    >
      {list.rows.map((row) => (
        <SelectableGridItem
          key={row.id}
          active={selection.active}
          selected={selection.selectedIds.has(row.id)}
          onToggle={(options) => selection.toggle(row, options)}
          label={row.name}
        >
          <div className="relative">
            {row.card}
            {unread.hasResource(communityId, tool, row.id) ? (
              <UnreadDot className="absolute top-3 right-3" />
            ) : null}
          </div>
        </SelectableGridItem>
      ))}
    </div>
  );

  // A narrower list may not reach the page being read.
  const changeFilters = (next: ToolListFilters) => {
    setFilters(next);
    if (page !== 1) setPage(1);
  };

  return (
    <div className="relative space-y-6" {...drop.handlers}>
      {drop.dragging && entry.fileDrop ? (
        <DropOverlay label={t(entry.fileDrop.label)} tall />
      ) : null}
      <ToolListToolbar
        leading={
          <ToolViewFilter
            tool={tool}
            value={view}
            counts={countsQuery.data?.views}
            onChange={setView}
          />
        }
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        actions={
          canCreateHere ? (
            <Button size="sm" className="h-9" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t(entry.text.create)}
            </Button>
          ) : null
        }
        view={{
          value: layout,
          onChange: (next) => {
            setLayout(next);
            setPage(1);
          },
          options: [
            { value: "grid", label: t("common:toolbar.viewGrid"), icon: LayoutGrid },
            { value: "list", label: t("common:toolbar.viewList"), icon: List },
            { value: "tags", label: t("common:toolbar.viewTags"), icon: Tags },
          ],
          label: t("common:toolbar.view"),
        }}
        menuItems={
          (canCreateHere && toolListingKind(tool)) || importAction.menuItem ? (
            <>
              {canCreateHere ? <BrowseMarketplaceMenuItem tool={tool} /> : null}
              {importAction.menuItem}
            </>
          ) : null
        }
        onEnterSelection={!selection.active && list.rows.length > 0 ? selection.enter : undefined}
      />
      {importAction.dialog}

      <ToolFilterPanel
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        title={t("filters.heading")}
        onClear={() => changeFilters({})}
        activeCount={activeFilterCount}
      >
        <ToolFilterFields
          tool={tool}
          value={filters}
          onChange={changeFilters}
          initiativeId={fixedInitiativeId}
        />
      </ToolFilterPanel>

      {list.isLoading ? (
        <SkeletonRegion label={t("loading")}>
          <CardGridSkeleton />
        </SkeletonRegion>
      ) : list.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : list.rows.length > 0 ||
        (layout === "tags" && (tagTree.selectedPaths.size > 0 || activeFilterCount > 0)) ? (
        // In the tags view a narrowed list that matches nothing keeps the tree
        // on screen, so another tag can be picked or the pick undone.
        <>
          <BulkAccessSection
            selection={selection}
            tool={tool}
            invalidate={() => invalidate(q.toolList(tool))}
          />
          {layout === "tags" ? (
            <TagBrowseLayout
              allTags={tagTree.allTags}
              tagCounts={countsQuery.data?.tag_counts ?? {}}
              untaggedCount={entry.untagged ? (countsQuery.data?.untagged_count ?? 0) : undefined}
              selectedPaths={tagTree.selectedPaths}
              onToggleTag={(path, ctrlKey) => {
                tagTree.toggle(path, ctrlKey);
                setPage(1);
              }}
            >
              {list.rows.length > 0 ? (
                cards
              ) : (
                <p className="py-8 text-center text-muted-foreground text-sm">
                  {t(entry.text.noMatches)}
                </p>
              )}
            </TagBrowseLayout>
          ) : layout === "list" && entry.table ? (
            <ToolIndexTable
              tool={tool}
              initiativeId={fixedInitiativeId}
              rows={list.rows}
              useColumns={entry.table.useColumns}
              selection={selection}
              sorting={tableState.sorting}
              onSortingChange={(next) => {
                setSorting(next);
                setPage(1);
              }}
            />
          ) : layout === "list" ? (
            <ul className="divide-y rounded-lg border">
              {list.rows.map((row) => (
                <li key={row.id}>
                  <SelectableGridItem
                    active={selection.active}
                    selected={selection.selectedIds.has(row.id)}
                    onToggle={(options) => selection.toggle(row, options)}
                    label={row.name}
                  >
                    <Link
                      to={gp(toolDetailRoute(tool, row.initiative_id, row.id))}
                      className="flex min-w-0 items-center gap-3 px-3 py-2.5 hover:bg-accent/50"
                    >
                      <ToolIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="min-w-0 truncate font-medium text-sm">{row.name}</span>
                      {unread.hasResource(communityId, tool, row.id) ? <UnreadDot /> : null}
                      <span className="flex-1" />
                      {row.tags?.length ? (
                        <TagBadgeList tags={row.tags} limit={3} nested className="shrink-0" />
                      ) : null}
                    </Link>
                  </SelectableGridItem>
                </li>
              ))}
            </ul>
          ) : (
            cards
          )}

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
        </>
      ) : activeFilterCount > 0 ? (
        <p className="text-muted-foreground text-sm">{t(entry.text.noMatches)}</p>
      ) : view !== "active" ? (
        // Nothing is made here: rows arrive in the archive when they are put
        // away, and a template is made by marking an existing one as one.
        <Card>
          <CardHeader>
            <CardTitle>
              {t(
                view === "archived"
                  ? "common:toolIndex.emptyArchivedTitle"
                  : "common:toolIndex.emptyTemplatesTitle"
              )}
            </CardTitle>
            <CardDescription>
              {t(
                view === "archived"
                  ? "common:toolIndex.emptyArchivedBody"
                  : "common:toolIndex.emptyTemplatesBody"
              )}
            </CardDescription>
          </CardHeader>
        </Card>
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
            {canCreateHere ? <BrowseMarketplaceButton tool={tool} /> : null}
          </CardContent>
        </Card>
      )}

      {entry.CreateDialog ? (
        <entry.CreateDialog
          open={createOpen}
          onOpenChange={onCreateOpenChange}
          initiativeId={fixedInitiativeId}
          onSuccess={openCreated}
          initialFile={droppedFile}
        />
      ) : (
        <CreateToolDialog
          open={createOpen}
          onOpenChange={handleCreateOpenChange}
          tool={tool}
          text={entry.text}
          initiativeId={fixedInitiativeId}
          onSuccess={openCreated}
        />
      )}
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
