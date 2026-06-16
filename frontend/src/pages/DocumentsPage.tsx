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
import { BulkEditAccessDialog } from "@/components/documents/BulkEditAccessDialog";
import { BulkEditTagsDialog } from "@/components/documents/BulkEditTagsDialog";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { DocumentsFilterBar } from "@/components/documents/DocumentsFilterBar";
import { DocumentsListView } from "@/components/documents/DocumentsListView";
import { DocumentsTagsView } from "@/components/documents/DocumentsTagsView";
import { PaginationBar } from "@/components/documents/PaginationBar";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { UNTAGGED_PATH } from "@/components/tags/TagTreeView";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import {
  useCopyDocument,
  useDeleteDocument,
  useDocumentCounts,
  useDocumentsList,
  usePrefetchDocumentsList,
} from "@/hooks/useDocuments";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import {
  canCreate as canCreatePermission,
  useMyInitiativePermissions,
} from "@/hooks/useInitiativeRoles";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useTags } from "@/hooks/useTags";
import { useViewPreference } from "@/hooks/useViewPreference";
import { useGuildPath } from "@/lib/guildUrl";
import { buildTagTree, collectDescendantTagIds, findNodeByPath } from "@/lib/tagTree";

const INITIATIVE_FILTER_ALL = "all";
const DOCUMENT_VIEW_KEY = "documents:view-mode";

/** Map DataTable column IDs to backend sort field names */
const SORT_FIELD_MAP: Record<string, string> = {
  title: "title",
  "last updated": "updated_at",
};
const DOCUMENT_TAG_FILTERS_KEY = "documents:tag-filters";
const getDefaultDocumentFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

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
  const { t } = useTranslation(["documents", "common"]);
  const router = useRouter();
  const prefetchDocuments = usePrefetchDocumentsList();
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  // Shared access helper — honors guild-admin / PAM / membership so this page
  // never re-derives access from raw membership flags.
  const { filterVisible, permissionsFor, isGuildAdmin, isGrantGuild } = useInitiativeAccess();
  const gp = useGuildPath();
  const searchParams = useSearch({ strict: false }) as {
    initiativeId?: string;
    create?: string;
    page?: number;
  };
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;
  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : INITIATIVE_FILTER_ALL
  );
  // Parse the filtered initiative ID for permission checks
  const filteredInitiativeId =
    initiativeFilter !== INITIATIVE_FILTER_ALL ? Number(initiativeFilter) : null;
  const { data: filteredInitiativePermissions } = useMyInitiativePermissions(
    !lockedInitiativeId && filteredInitiativeId ? filteredInitiativeId : null
  );
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;
  const lastConsumedParams = useRef<string>("");
  const prevGuildIdRef = useRef<number | null>(activeGuildId);
  const isClosingCreateDialog = useRef(false);

  // Check for query params to filter by initiative (consume once)
  useEffect(() => {
    const urlInitiativeId = searchParams.initiativeId;
    const paramKey = urlInitiativeId || "";

    if (urlInitiativeId && !lockedInitiativeId && paramKey !== lastConsumedParams.current) {
      lastConsumedParams.current = paramKey;
      setInitiativeFilter(urlInitiativeId);
    }
  }, [searchParams, lockedInitiativeId]);
  const [searchQuery, setSearchQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultDocumentFiltersVisibility);

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

  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
    }
  }, [lockedInitiativeId]);

  // Reset initiative filter when guild changes (initiative IDs are guild-specific)
  useEffect(() => {
    const prevGuildId = prevGuildIdRef.current;
    prevGuildIdRef.current = activeGuildId;
    // Only reset if guild actually changed (not on initial mount)
    if (prevGuildId !== null && prevGuildId !== activeGuildId && !lockedInitiativeId) {
      setInitiativeFilter(INITIATIVE_FILTER_ALL);
      lastConsumedParams.current = "";
    }
  }, [activeGuildId, lockedInitiativeId]);

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
    ...(initiativeFilter !== INITIATIVE_FILTER_ALL
      ? { initiative_id: Number(initiativeFilter) }
      : {}),
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
    ...(initiativeFilter !== INITIATIVE_FILTER_ALL
      ? { initiative_id: Number(initiativeFilter) }
      : {}),
    ...(searchQuery.trim() ? { search: searchQuery.trim() } : {}),
  };

  const countsQuery = useDocumentCounts(countsQueryParams, { enabled: viewMode === "tags" });

  // Prefetch adjacent page on hover
  const prefetchPage = useCallback(
    (targetPage: number) => {
      if (targetPage < 1) return;
      const prefetchParams: ListDocumentsApiV1GGuildIdDocumentsGetParams = {
        ...(initiativeFilter !== INITIATIVE_FILTER_ALL
          ? { initiative_id: Number(initiativeFilter) }
          : {}),
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
      initiativeFilter,
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

  // Initiatives the user can create documents in — resolved through the shared
  // access helper so guild admins are included regardless of any membership row.
  const creatableInitiatives = useMemo(() => {
    if (!initiativesQuery.data || !user) {
      return [];
    }
    return filterVisible(initiativesQuery.data).filter(
      (initiative) => permissionsFor(initiative).canCreateDocs
    );
  }, [initiativesQuery.data, user, filterVisible, permissionsFor]);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createDialogInitiativeId, setCreateDialogInitiativeId] = useState<number | undefined>(
    lockedInitiativeId ?? undefined
  );
  const [selectedDocuments, setSelectedDocuments] = useState<DocumentSummary[]>([]);

  // Check if user owns all selected documents (required for delete)
  const canDeleteSelectedDocuments = useMemo(() => {
    if (!user || selectedDocuments.length === 0) {
      return false;
    }
    return selectedDocuments.every((doc) => {
      const permission = (doc.permissions ?? []).find((p) => p.user_id === user.id);
      return permission?.level === "owner";
    });
  }, [selectedDocuments, user]);

  // Check if user has write access on all selected documents (required for duplicate and bulk edit)
  const canDuplicateSelectedDocuments = useMemo(() => {
    if (!user || selectedDocuments.length === 0) {
      return false;
    }
    return selectedDocuments.every((doc) => {
      const permission = (doc.permissions ?? []).find((p) => p.user_id === user.id);
      return permission?.level === "owner" || permission?.level === "write";
    });
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
    // If no specific initiative is filtered, user can view the page
    const effectiveInitiativeId = lockedInitiativeId ?? filteredInitiativeId;
    if (!effectiveInitiativeId || !user) {
      return true;
    }
    const initiative = initiativesQuery.data?.find((i) => i.id === effectiveInitiativeId);
    if (!initiative) {
      return true; // Initiative not loaded yet, assume access
    }
    const membership = initiative.members.find((m) => m.user.id === user.id);
    if (!membership) {
      return true; // Not a member, let the backend handle access control
    }
    return membership.can_view_docs !== false;
  }, [
    lockedInitiativeId,
    filteredInitiativeId,
    user,
    initiativesQuery.data,
    isGuildAdmin,
    isGrantGuild,
  ]);

  // Use explicit canCreate prop if provided (from role permissions), otherwise check filtered initiative permissions
  const canCreateDocuments = useMemo(() => {
    // If explicit prop provided (e.g., from InitiativeDetailPage), use it
    if (canCreate !== undefined) {
      return canCreate;
    }
    // If a specific initiative is filtered, check permissions for that initiative
    if (filteredInitiativeId && filteredInitiativePermissions) {
      return canCreatePermission(filteredInitiativePermissions, "docs");
    }
    // Fall back to legacy check (user is PM in any initiative)
    if (lockedInitiativeId) {
      return creatableInitiatives.some((initiative) => initiative.id === lockedInitiativeId);
    }
    return creatableInitiatives.length > 0;
  }, [
    canCreate,
    filteredInitiativeId,
    filteredInitiativePermissions,
    lockedInitiativeId,
    creatableInitiatives,
  ]);

  // Open create dialog when ?create=true is in URL
  useEffect(() => {
    const shouldCreate = searchParams.create === "true";
    const urlInitiativeId = searchParams.initiativeId;

    if (shouldCreate && !createDialogOpen && !isClosingCreateDialog.current) {
      setCreateDialogOpen(true);
      if (urlInitiativeId && !lockedInitiativeId) {
        setCreateDialogInitiativeId(Number(urlInitiativeId));
      }
    }
    // Reset the closing flag once URL no longer has create=true
    if (!shouldCreate) {
      isClosingCreateDialog.current = false;
    }
  }, [searchParams, lockedInitiativeId, createDialogOpen]);

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

  const handleDocumentCreated = (document: { id: number }) => {
    router.navigate({
      to: gp(`/documents/${document.id}`),
    });
  };

  const handleCreateDialogOpenChange = (open: boolean) => {
    setCreateDialogOpen(open);
    // Clear ?create from URL when dialog closes
    if (!open && searchParams.create) {
      isClosingCreateDialog.current = true;
      router.navigate({
        to: gp("/documents"),
        search: { initiativeId: searchParams.initiativeId },
        replace: true,
      });
    }
  };

  const deleteDocuments = useDeleteDocument({
    onSuccess: () => setSelectedDocuments([]),
  });

  const duplicateDocuments = useCopyDocument({
    onSuccess: () => setSelectedDocuments([]),
  });

  const initiatives = initiativesQuery.data ?? [];
  // Filter initiatives where user can view docs (for the dropdown)
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
      return membership.can_view_docs !== false;
    });
  }, [initiativesQuery.data, user, isGuildAdmin, isGrantGuild]);
  const lockedInitiative = lockedInitiativeId
    ? (initiatives.find((initiative) => initiative.id === lockedInitiativeId) ?? null)
    : null;

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
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="font-semibold text-3xl tracking-tight">{t("page.title")}</h1>
              {canCreateDocuments ? (
                <Button size="sm" variant="outline" onClick={() => setCreateDialogOpen(true)}>
                  <Plus className="h-4 w-4" />
                  {t("page.newDocument")}
                </Button>
              ) : null}
            </div>
            <p className="text-muted-foreground text-sm">{t("page.subtitle")}</p>
          </div>
          <Tabs
            value={viewMode}
            onValueChange={(value) => setViewMode(value as "grid" | "list" | "tags")}
            className="w-auto"
          >
            <TabsList className="grid grid-cols-3">
              <TabsTrigger value="tags" className="inline-flex items-center gap-2">
                <Tags className="h-4 w-4" />
                {t("page.viewTags")}
              </TabsTrigger>
              <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                <LayoutGrid className="h-4 w-4" />
                {t("page.viewGrid")}
              </TabsTrigger>
              <TabsTrigger value="list" className="inline-flex items-center gap-2">
                <Table className="h-4 w-4" />
                {t("page.viewList")}
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      )}

      {lockedInitiativeId && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          {canCreateDocuments && (
            <Button variant="outline" onClick={() => setCreateDialogOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("page.newDocument")}
            </Button>
          )}
          <Tabs
            value={viewMode}
            onValueChange={(value) => setViewMode(value as "grid" | "list" | "tags")}
            className="w-auto"
          >
            <TabsList className="grid grid-cols-3">
              <TabsTrigger value="tags" className="inline-flex items-center gap-2">
                <Tags className="h-4 w-4" />
                {t("page.viewTags")}
              </TabsTrigger>
              <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                <LayoutGrid className="h-4 w-4" />
                {t("page.viewGrid")}
              </TabsTrigger>
              <TabsTrigger value="list" className="inline-flex items-center gap-2">
                <Table className="h-4 w-4" />
                {t("page.viewList")}
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      )}

      <DocumentsFilterBar
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        initiativeFilter={initiativeFilter}
        onInitiativeFilterChange={setInitiativeFilter}
        lockedInitiativeId={lockedInitiativeId}
        lockedInitiativeName={lockedInitiative?.name ?? null}
        viewableInitiatives={viewableInitiatives}
        initiativesLoading={initiativesQuery.isLoading}
        filtersOpen={filtersOpen}
        onFiltersOpenChange={setFiltersOpen}
        viewMode={viewMode}
        tagFilters={selectedTagsForFilter}
        onTagFiltersChange={handleTagFiltersChange}
        fixedTagIds={fixedTagIds}
        propertyFilters={propertyFilters}
        onPropertyFiltersChange={setPropertyFilters}
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
        />
      ) : totalCount > 0 ? (
        viewMode === "grid" ? (
          <>
            <div className="animate grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {documents.map((document) => (
                <DocumentCard key={document.id} document={document} hideInitiative />
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
          <CardContent>
            <Button onClick={() => setCreateDialogOpen(true)} disabled={!canCreateDocuments}>
              {t("page.startWriting")}
            </Button>
          </CardContent>
        </Card>
      )}

      <CreateDocumentDialog
        open={createDialogOpen}
        onOpenChange={handleCreateDialogOpenChange}
        initiativeId={lockedInitiativeId ?? undefined}
        defaultInitiativeId={
          initiativeFilter !== INITIATIVE_FILTER_ALL
            ? Number(initiativeFilter)
            : createDialogInitiativeId
        }
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
        documents={selectedDocuments}
        onSuccess={() => {}}
      />

      {canCreateDocuments ? (
        <Button
          type="button"
          className="fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg shadow-primary/40"
          onClick={() => setCreateDialogOpen(true)}
        >
          <Plus className="h-4 w-4" />
          {t("page.newDocument")}
        </Button>
      ) : null}
    </div>
  );
};

export const DocumentsPage = () => <DocumentsView />;
