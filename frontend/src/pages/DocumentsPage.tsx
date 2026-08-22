import { useRouter, useSearch } from "@tanstack/react-router";
import type { SortingState } from "@tanstack/react-table";
import { LayoutGrid, Loader2, Plus, Table, Tags } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  DocumentSummary,
  ListDocumentsApiV1GGuildIdDocumentsGetParams,
  TagRead,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidateAllDocuments } from "@/api/query-keys";
import { BulkEditAccessDialog } from "@/components/access/BulkEditAccessDialog";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { BulkEditTagsDialog } from "@/components/documents/BulkEditTagsDialog";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { DocumentsBulkBar } from "@/components/documents/DocumentsBulkBar";
import { DocumentsFilterBar } from "@/components/documents/DocumentsFilterBar";
import { DocumentsListView } from "@/components/documents/DocumentsListView";
import { DocumentsTagsView } from "@/components/documents/DocumentsTagsView";
import { PaginationBar } from "@/components/documents/PaginationBar";
import { ToolImportAction, useToolImportAction } from "@/components/imports/ToolImportAction";
import {
  ToolListToolbar,
  type ToolViewOption,
} from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { UNTAGGED_PATH } from "@/components/tags/TagTreeView";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import {
  useCopyDocument,
  useDeleteDocuments,
  useDocumentCounts,
  useDocumentsList,
  usePrefetchDocumentsList,
} from "@/hooks/useDocuments";
import { useInitiativeAccess, useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useTags } from "@/hooks/useTags";
import { useViewPreference } from "@/hooks/useViewPreference";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { buildTagTree, collectDescendantTagIds, findNodeByPath } from "@/lib/tagTree";
import { toolDetailRoute } from "@/lib/tools";

const DOCUMENT_VIEW_KEY = "documents:view-mode";

/** Map DataTable column IDs to backend sort field names */
const SORT_FIELD_MAP: Record<string, string> = {
  name: "name",
  "last updated": "updated_at",
};
const DOCUMENT_TAG_FILTERS_KEY = "documents:tag-filters";

type DocumentsViewProps = {
  fixedInitiativeId?: number;
  fixedTagIds?: number[];
  canCreate?: boolean;
};

export const DocumentsView = ({
  fixedInitiativeId,
  fixedTagIds,
  canCreate,
}: DocumentsViewProps) => {
  const { t } = useTranslation(["documents", "common", "access"]);
  const router = useRouter();
  const prefetchDocuments = usePrefetchDocumentsList();
  const { user } = useAuth();
  // Shared access helper — honors guild-admin / PAM / membership so this page
  // never re-derives access from raw membership flags.
  const { isGuildAdmin, isGrantGuild } = useInitiativeAccess();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as {
    create?: string;
    page?: number;
  };
  // The initiative comes from the path. It is absent only on the tag browse,
  // which is deliberately cross-initiative.
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;
  const [searchQuery, setSearchQuery] = useState("");
  // Closed until asked for. The filter button carries a count of what's set, so
  // a narrowed list still says so with the panel shut — and the fields no
  // longer take the top of the page before the list itself.
  const [filtersOpen, setFiltersOpen] = useState(false);

  // View mode and tag filters are server-persisted in the normal case.
  // When fixedTagIds is provided (tag detail page), the view is forced
  // to "list" and tagFilters mirrors the prop — writes are discarded so
  // we don't pollute the persisted "regular" preferences with the
  // ephemeral fixed-page values.
  const [persistedViewMode, setPersistedViewMode] = useViewPreference<string>(
    DOCUMENT_VIEW_KEY,
    "tags"
  );
  const viewMode: "grid" | "list" | "tags" = fixedTagIds
    ? "list"
    : persistedViewMode === "list" || persistedViewMode === "grid" || persistedViewMode === "tags"
      ? persistedViewMode
      : "tags";
  const setViewMode = useCallback(
    (next: "grid" | "list" | "tags") => {
      if (fixedTagIds) return;
      setPersistedViewMode(next);
    },
    [fixedTagIds, setPersistedViewMode]
  );

  const [persistedTagFilters, setPersistedTagFilters] = useViewPreference<number[]>(
    DOCUMENT_TAG_FILTERS_KEY,
    []
  );
  const tagFilters = fixedTagIds
    ? fixedTagIds
    : Array.isArray(persistedTagFilters)
      ? persistedTagFilters.filter((n): n is number => typeof n === "number" && Number.isFinite(n))
      : [];
  const setTagFilters = useCallback(
    (next: number[] | ((prev: number[]) => number[])) => {
      if (fixedTagIds) return;
      setPersistedTagFilters((prev) => {
        const safe = Array.isArray(prev) ? prev : [];
        return typeof next === "function" ? next(safe) : next;
      });
    },
    [fixedTagIds, setPersistedTagFilters]
  );

  const [treeSelectedPaths, setTreeSelectedPaths] = useState<Set<string>>(new Set());

  const [propertyFilters, setPropertyFilters] = useState<PropertyFilterCondition[]>([]);

  const [page, setPageState] = useState(() => searchParams.page ?? 1);
  const [pageSize, setPageSizeState] = useState(20);
  const [sortBy, setSortBy] = useState<string | undefined>("updated_at");
  const [sortDir, setSortDir] = useState<string | undefined>("desc");

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

  const handlePageSizeChange = useCallback(
    (size: number) => {
      setPageSizeState(size);
      setPage(1);
    },
    [setPage]
  );

  const handleSortingChange = useCallback(
    (sorting: SortingState) => {
      if (sorting.length > 0) {
        const col = sorting[0];
        const field = SORT_FIELD_MAP[col.id];
        if (field) {
          setSortBy(field);
          setSortDir(col.desc ? "desc" : "asc");
        } else {
          setSortBy(undefined);
          setSortDir(undefined);
        }
      } else {
        setSortBy(undefined);
        setSortDir(undefined);
      }
      setPage(1);
    },
    [setPage]
  );

  const { data: allTags = [] } = useTags();

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTagsForFilter = useMemo(() => {
    const tagMap = new Map(allTags.map((tg) => [tg.id, tg]));
    return tagFilters.map((id) => tagMap.get(id)).filter((tg): tg is TagRead => tg !== undefined);
  }, [allTags, tagFilters]);

  const handleTagFiltersChange = (newTags: TagSummary[]) => {
    setTagFilters(newTags.map((tg) => tg.id));
  };

  const handleTreeTagToggle = (fullPath: string, ctrlKey: boolean) => {
    setTreeSelectedPaths((prev) => {
      const next = new Set(prev);
      if (ctrlKey) {
        // Ctrl/Cmd+Click: toggle in selection
        if (next.has(fullPath)) {
          next.delete(fullPath);
        } else {
          next.add(fullPath);
        }
      } else {
        // Plain click: replace selection, or deselect if already the only selection
        if (next.size === 1 && next.has(fullPath)) {
          next.clear();
        } else {
          next.clear();
          next.add(fullPath);
        }
      }
      return next;
    });
  };

  // Reset tree selection when switching away from tags view
  useEffect(() => {
    if (viewMode !== "tags") {
      setTreeSelectedPaths(new Set());
    }
  }, [viewMode]);

  // In tags view, the tree does its own client-side filtering, so skip backend tag filters
  // When fixedTagIds is provided, always use them regardless of view mode
  const effectiveTagFilters = fixedTagIds ? fixedTagIds : viewMode === "tags" ? [] : tagFilters;

  // For tags view, derive tag_ids from tree selection for server-side filtering
  const treeTagIds = useMemo(() => {
    if (viewMode !== "tags" || treeSelectedPaths.size === 0) return [];
    const tagPaths = new Set(treeSelectedPaths);
    tagPaths.delete(UNTAGGED_PATH);
    const tree = buildTagTree(allTags);
    const ids: number[] = [];
    for (const path of tagPaths) {
      const node = findNodeByPath(tree, path);
      if (node) {
        for (const id of collectDescendantTagIds(node)) {
          ids.push(id);
        }
      }
    }
    return ids;
  }, [viewMode, treeSelectedPaths, allTags]);

  // Whether "untagged" is selected in tags view
  const treeWantsUntagged = viewMode === "tags" && treeSelectedPaths.has(UNTAGGED_PATH);

  // Effective tag_ids sent to the server for the document list query
  // In tags view: use tree-derived tag IDs; in other views: use filter bar tag IDs
  const queryTagIds = viewMode === "tags" ? treeTagIds : effectiveTagFilters;

  // Reset to page 1 when filters or view mode change
  const _queryTagIdsKey = JSON.stringify(queryTagIds);
  const propertyFiltersKey = JSON.stringify(propertyFilters);
  useEffect(() => {
    setPage(1);
  }, [setPage]);

  // Serialize property filters for the backend query string. The backend
  // expects a JSON-encoded array on ``property_filters`` and we pre-encode
  // it just before passing to the hook so the react-query key stays a
  // primitive string (same serialization => same cache key).
  const encodedPropertyFilters = propertyFilters.length > 0 ? propertyFiltersKey : null;

  const documentsQueryParams: ListDocumentsApiV1GGuildIdDocumentsGetParams = {
    ...(lockedInitiativeId ? { initiative_id: lockedInitiativeId } : {}),
    ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
    ...(queryTagIds.length > 0 ? { tag_ids: queryTagIds } : {}),
    ...(treeWantsUntagged ? { untagged: true } : {}),
    ...(encodedPropertyFilters ? { property_filters: encodedPropertyFilters } : {}),
    page,
    page_size: pageSize,
    ...(sortBy ? { sort_by: sortBy } : {}),
    ...(sortDir ? { sort_dir: sortDir } : {}),
  };

  const documentsQuery = useDocumentsList(documentsQueryParams);

  // Counts query for tags view sidebar
  const countsQueryParams = {
    ...(lockedInitiativeId ? { initiative_id: lockedInitiativeId } : {}),
    ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
  };

  const countsQuery = useDocumentCounts(countsQueryParams, { enabled: viewMode === "tags" });

  // Prefetch adjacent page on hover
  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListDocumentsApiV1GGuildIdDocumentsGetParams = {
        ...(lockedInitiativeId ? { initiative_id: lockedInitiativeId } : {}),
        ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
        ...(queryTagIds.length > 0 ? { tag_ids: queryTagIds } : {}),
        ...(treeWantsUntagged ? { untagged: true } : {}),
        ...(encodedPropertyFilters ? { property_filters: encodedPropertyFilters } : {}),
        page: targetPage,
        page_size: pageSize,
        ...(sortBy ? { sort_by: sortBy } : {}),
        ...(sortDir ? { sort_dir: sortDir } : {}),
      };
      void prefetchDocuments(prefetchParams);
    },
    [
      lockedInitiativeId,
      searchQuery,
      queryTagIds,
      treeWantsUntagged,
      encodedPropertyFilters,
      pageSize,
      sortBy,
      sortDir,
      prefetchDocuments,
    ]
  );

  const initiativesQuery = useInitiatives();

  // Canonical create answer: the locked/filtered initiative's server-computed
  // create flag, or (in the "All" view) whether any visible initiative grants
  // it. `creatableInitiatives` feeds the create dialog's initiative picker.
  const { canCreate: canCreateDerived, creatableInitiatives } = useToolCreateAccess(Tool.document, {
    initiativeId: lockedInitiativeId,
  });

  const [createDialogInitiativeId, _setCreateDialogInitiativeId] = useState<number | undefined>(
    lockedInitiativeId ?? undefined
  );
  const {
    open: createDialogOpen,
    setOpen: setCreateDialogOpen,
    onOpenChange: handleCreateDialogOpenChange,
  } = useCreateFromSearchParam();
  const [selectedDocuments, setSelectedDocuments] = useState<DocumentSummary[]>([]);

  // Grid/tags selection mode (the table view has its own row checkboxes and
  // shares the same selectedDocuments state). Entering turns cards into
  // checkboxes, exactly like the queues/counters lists.
  const [cardSelectionActive, setCardSelectionActive] = useState(false);
  const selectedDocumentIds = useMemo(
    () => new Set(selectedDocuments.map((doc) => doc.id)),
    [selectedDocuments]
  );
  const toggleDocumentSelection = useCallback((document: DocumentSummary) => {
    setSelectedDocuments((prev) =>
      prev.some((doc) => doc.id === document.id)
        ? prev.filter((doc) => doc.id !== document.id)
        : [...prev, document]
    );
  }, []);
  const exitCardSelection = useCallback(() => {
    setCardSelectionActive(false);
    setSelectedDocuments([]);
  }, []);
  // Switching views must not strand a hidden selection behind another view's
  // bulk actions — every view change starts unselected.
  useEffect(() => {
    setCardSelectionActive(false);
    setSelectedDocuments([]);
  }, [viewMode]);

  // Check if user owns all selected documents (required for delete)
  const canDeleteSelectedDocuments = useMemo(() => {
    if (!user || selectedDocuments.length === 0) {
      return false;
    }
    return selectedDocuments.every((doc) => doc.my_permission_level === "owner");
  }, [selectedDocuments, user]);

  // Check if user has write access on all selected documents (required for duplicate and bulk edit)
  const canDuplicateSelectedDocuments = useMemo(() => {
    if (!user || selectedDocuments.length === 0) {
      return false;
    }
    return selectedDocuments.every((doc) => hasWriteAccess(doc.my_permission_level));
  }, [selectedDocuments, user]);

  const canEditSelectedDocuments = canDuplicateSelectedDocuments;

  const [bulkEditTagsOpen, setBulkEditTagsOpen] = useState(false);
  const [bulkEditAccessOpen, setBulkEditAccessOpen] = useState(false);

  // Check if user can view docs for the filtered initiative
  const canViewDocs = useMemo(() => {
    // Guild admins / PAM grantees always have access — a membership row must
    // never downgrade them.
    if (isGuildAdmin || isGrantGuild) {
      return true;
    }
    // The cross-initiative tag browse has no one initiative to check.
    if (!lockedInitiativeId || !user) {
      return true;
    }
    const initiative = initiativesQuery.data?.find((i) => i.id === lockedInitiativeId);
    if (!initiative) {
      return true; // Initiative not loaded yet, assume access
    }
    const membership = initiative.members.find((m) => m.user.id === user.id);
    if (!membership) {
      return true; // Not a member, let the backend handle access control
    }
    return membership.can_view_documents !== false;
  }, [lockedInitiativeId, user, initiativesQuery.data, isGuildAdmin, isGrantGuild]);

  // An explicit canCreate prop (e.g. from InitiativeDetailPage) wins; otherwise
  // use the canonical derivation above.
  const canCreateDocuments = canCreate ?? canCreateDerived;

  // Inside an initiative tab the import entry rides in the toolbar's shared
  // overflow menu; the unscoped page keeps its own kebab beside the heading.
  const documentImport = useToolImportAction({
    tool: Tool.document,
    canImport: canCreateDocuments && lockedInitiativeId !== null,
    fixedInitiativeId: lockedInitiativeId ?? undefined,
  });

  const viewOptions: ToolViewOption<"grid" | "list" | "tags">[] = [
    { value: "tags", label: t("page.viewTags"), icon: Tags },
    { value: "grid", label: t("page.viewGrid"), icon: LayoutGrid },
    { value: "list", label: t("page.viewList"), icon: Table },
  ];

  // Badges the filter button while the panel is closed. The tag *view* browses
  // by tag through its own tree, so its tag selection isn't counted here.
  const activeFilterCount =
    (searchQuery.trim() ? 1 : 0) +
    (fixedTagIds || viewMode === "tags" ? 0 : tagFilters.length) +
    propertyFilters.length;

  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setTagFilters([]);
    setPropertyFilters([]);
  }, [setTagFilters]);

  // Drive the app-wide bottom-nav add button for this route.
  useRegisterPrimaryCreateAction(
    canCreateDocuments
      ? { run: () => setCreateDialogOpen(true), label: t("page.newDocument") }
      : null
  );

  const handleDocumentCreated = (document: { id: number; initiative_id?: number }) => {
    // The dialog can only create inside a scope this view already has: the
    // locked initiative, or the one it picked when there is none.
    const initiativeId = lockedInitiativeId ?? document.initiative_id ?? null;
    router.navigate({ to: gp(toolDetailRoute(Tool.document, initiativeId, document.id)) });
  };

  const deleteDocuments = useDeleteDocuments({
    onSuccess: () => setSelectedDocuments([]),
  });

  const duplicateDocuments = useCopyDocument({
    onSuccess: () => setSelectedDocuments([]),
  });

  // Initiatives whose documents this reader may see. Still needed on the
  // cross-initiative tag browse, which lists documents from several at once.
  const viewableInitiatives = useMemo(() => {
    const allInitiatives = initiativesQuery.data ?? [];
    if (!user) return allInitiatives;
    // Guild admins / PAM grantees see every initiative regardless of any
    // membership row.
    if (isGuildAdmin || isGrantGuild) return allInitiatives;
    return allInitiatives.filter((initiative) => {
      const membership = initiative.members.find((m) => m.user.id === user.id);
      // If not a member, include it (backend will handle access control)
      if (!membership) return true;
      return membership.can_view_documents !== false;
    });
  }, [initiativesQuery.data, user, isGuildAdmin, isGrantGuild]);
  // Get IDs of initiatives where user can view docs
  const viewableInitiativeIds = useMemo(() => {
    return new Set(viewableInitiatives.map((i) => i.id));
  }, [viewableInitiatives]);

  // Filter documents to only show those from viewable initiatives
  const documents = useMemo(() => {
    const allDocs = documentsQuery.data?.items ?? [];
    if (!user) return allDocs;
    return allDocs.filter((doc) => viewableInitiativeIds.has(doc.initiative_id));
  }, [documentsQuery.data, user, viewableInitiativeIds]);

  const totalCount = documentsQuery.data?.total_count ?? 0;
  const hasNext = documentsQuery.data?.has_next ?? false;
  const totalPages = pageSize > 0 ? Math.ceil(totalCount / pageSize) : 1;

  // Server handles untagged filtering via ?untagged=true param
  const displayDocuments = documents;

  return (
    <div className="space-y-6">
      {!lockedInitiativeId && !fixedTagIds && (
        <div>
          <div className="flex items-baseline gap-4">
            <h1 className="font-semibold text-3xl tracking-tight">{t("page.title")}</h1>
            {canCreateDocuments ? (
              <Button size="sm" variant="outline" onClick={() => setCreateDialogOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("page.newDocument")}
              </Button>
            ) : null}
            <ToolImportAction tool={Tool.document} canImport={canCreateDocuments} />
          </div>
          <p className="text-muted-foreground text-sm">{t("page.subtitle")}</p>
        </div>
      )}

      <ToolListToolbar
        filters={{
          open: filtersOpen,
          onOpenChange: setFiltersOpen,
          activeCount: activeFilterCount,
        }}
        view={
          // The tag-detail browse pins the list view, so it has nothing to pick.
          fixedTagIds
            ? undefined
            : {
                value: viewMode,
                onChange: setViewMode,
                options: viewOptions,
                label: t("common:toolbar.view"),
              }
        }
        actions={
          canCreateDocuments && lockedInitiativeId ? (
            <Button
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="h-4 w-4" />
              {t("page.newDocument")}
            </Button>
          ) : null
        }
        menuItems={documentImport.menuItem}
        onEnterSelection={
          // The list view carries its own row selection in the table header.
          !cardSelectionActive && viewMode !== "list"
            ? () => setCardSelectionActive(true)
            : undefined
        }
      />
      {documentImport.dialog}

      <DocumentsFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
        viewMode={viewMode}
        tagFilters={selectedTagsForFilter}
        onTagFiltersChange={handleTagFiltersChange}
        fixedTagIds={fixedTagIds}
        propertyFilters={propertyFilters}
        onPropertyFiltersChange={setPropertyFilters}
        onClear={clearFilters}
        activeCount={activeFilterCount}
      />

      {!canViewDocs ? (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardHeader>
            <CardTitle className="text-destructive">{t("page.accessRestrictedTitle")}</CardTitle>
            <CardDescription>{t("page.accessRestrictedDescription")}</CardDescription>
          </CardHeader>
        </Card>
      ) : documentsQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("page.loading")}
        </div>
      ) : documentsQuery.isError ? (
        <p className="text-destructive text-sm">{t("page.loadError")}</p>
      ) : viewMode === "tags" ? (
        <>
          {cardSelectionActive ? (
            <DocumentsBulkBar
              selectedDocuments={selectedDocuments}
              canEditSelectedDocuments={canEditSelectedDocuments}
              canDuplicateSelectedDocuments={canDuplicateSelectedDocuments}
              canDeleteSelectedDocuments={canDeleteSelectedDocuments}
              onBulkEditTags={() => setBulkEditTagsOpen(true)}
              onBulkEditAccess={() => setBulkEditAccessOpen(true)}
              onBulkDuplicate={() => duplicateDocuments.mutate(selectedDocuments)}
              isBulkDuplicating={duplicateDocuments.isPending}
              onBulkDelete={() => {
                if (confirm(t("bulk.deleteConfirm", { count: selectedDocuments.length }))) {
                  deleteDocuments.mutate(selectedDocuments.map((doc) => doc.id));
                }
              }}
              isBulkDeleting={deleteDocuments.isPending}
              onExit={exitCardSelection}
            />
          ) : null}
          <DocumentsTagsView
            documents={displayDocuments}
            allTags={allTags}
            tagCounts={countsQuery.data?.tag_counts ?? {}}
            untaggedCount={countsQuery.data?.untagged_count ?? 0}
            treeSelectedPaths={treeSelectedPaths}
            onToggleTag={handleTreeTagToggle}
            page={page}
            pageSize={pageSize}
            totalCount={totalCount}
            hasNext={hasNext}
            onPageChange={setPage}
            onPageSizeChange={handlePageSizeChange}
            onPrefetchPage={prefetchPage}
            selectionActive={cardSelectionActive}
            selectedDocumentIds={selectedDocumentIds}
            onToggleDocument={toggleDocumentSelection}
          />
        </>
      ) : totalCount > 0 ? (
        viewMode === "grid" ? (
          <>
            {cardSelectionActive ? (
              <DocumentsBulkBar
                selectedDocuments={selectedDocuments}
                canEditSelectedDocuments={canEditSelectedDocuments}
                canDuplicateSelectedDocuments={canDuplicateSelectedDocuments}
                canDeleteSelectedDocuments={canDeleteSelectedDocuments}
                onBulkEditTags={() => setBulkEditTagsOpen(true)}
                onBulkEditAccess={() => setBulkEditAccessOpen(true)}
                onBulkDuplicate={() => duplicateDocuments.mutate(selectedDocuments)}
                isBulkDuplicating={duplicateDocuments.isPending}
                onBulkDelete={() => {
                  if (confirm(t("bulk.deleteConfirm", { count: selectedDocuments.length }))) {
                    deleteDocuments.mutate(selectedDocuments.map((doc) => doc.id));
                  }
                }}
                isBulkDeleting={deleteDocuments.isPending}
                onExit={exitCardSelection}
              />
            ) : null}
            <div className="animate grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {documents.map((document) => (
                <SelectableGridItem
                  key={document.id}
                  active={cardSelectionActive}
                  selected={selectedDocumentIds.has(document.id)}
                  onToggle={() => toggleDocumentSelection(document)}
                  label={document.name}
                >
                  <DocumentCard document={document} />
                </SelectableGridItem>
              ))}
            </div>
            {totalCount > 0 && (
              <PaginationBar
                page={page}
                pageSize={pageSize}
                totalCount={totalCount}
                hasNext={hasNext}
                onPageChange={setPage}
                onPageSizeChange={handlePageSizeChange}
                onPrefetchPage={prefetchPage}
              />
            )}
          </>
        ) : (
          <DocumentsListView
            documents={documents}
            selectedDocuments={selectedDocuments}
            onSelectedDocumentsChange={setSelectedDocuments}
            canEditSelectedDocuments={canEditSelectedDocuments}
            canDuplicateSelectedDocuments={canDuplicateSelectedDocuments}
            canDeleteSelectedDocuments={canDeleteSelectedDocuments}
            onBulkEditTags={() => setBulkEditTagsOpen(true)}
            onBulkEditAccess={() => setBulkEditAccessOpen(true)}
            onBulkDuplicate={() => duplicateDocuments.mutate(selectedDocuments)}
            isBulkDuplicating={duplicateDocuments.isPending}
            onBulkDelete={() => {
              if (confirm(t("bulk.deleteConfirm", { count: selectedDocuments.length }))) {
                deleteDocuments.mutate(selectedDocuments.map((doc) => doc.id));
              }
            }}
            isBulkDeleting={deleteDocuments.isPending}
            totalPages={totalPages}
            totalCount={totalCount}
            pageSize={pageSize}
            page={page}
            onPageSizeChange={handlePageSizeChange}
            onPageChange={setPage}
            onPrefetchPage={prefetchPage}
            onSortingChange={handleSortingChange}
          />
        )
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("page.noDocumentsTitle")}</CardTitle>
            <CardDescription>{t("page.noDocumentsDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button onClick={() => setCreateDialogOpen(true)} disabled={!canCreateDocuments}>
              {t("page.startWriting")}
            </Button>
            <ToolImportAction
              tool={Tool.document}
              canImport={canCreateDocuments}
              fixedInitiativeId={lockedInitiativeId ?? undefined}
              variant="button"
            />
          </CardContent>
        </Card>
      )}

      <CreateDocumentDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        initiativeId={lockedInitiativeId ?? undefined}
        defaultInitiativeId={lockedInitiativeId ?? createDialogInitiativeId}
        initiatives={creatableInitiatives}
        onSuccess={handleDocumentCreated}
      />

      <BulkEditTagsDialog
        open={bulkEditTagsOpen}
        onOpenChange={setBulkEditTagsOpen}
        documents={selectedDocuments}
        onSuccess={() => {}}
      />

      <BulkEditAccessDialog
        open={bulkEditAccessOpen}
        onOpenChange={setBulkEditAccessOpen}
        items={selectedDocuments}
        resourceType={Tool.document}
        invalidate={invalidateAllDocuments}
        onSuccess={() => {}}
      />
    </div>
  );
};
