import { useEffect, useMemo, useRef, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { Link, useRouter, useSearch } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  ChevronDown,
  FileText,
  FileSpreadsheet,
  Filter,
  LayoutGrid,
  Loader2,
  Plus,
  Presentation,
  Table,
  Copy,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { CreateDocumentDialog } from "@/components/documents/CreateDocumentDialog";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  useMyInitiativePermissions,
  canCreate as canCreatePermission,
} from "@/hooks/useInitiativeRoles";
import type { DocumentRead, DocumentSummary, Initiative, Tag, TagSummary } from "@/types/api";
import { getFileTypeLabel } from "@/lib/fileUtils";
import { SortIcon } from "@/components/SortIcon";
import { dateSortingFn } from "@/lib/sorting";
import { TagPicker } from "@/components/tags/TagPicker";
import { useTags } from "@/hooks/useTags";

const INITIATIVE_FILTER_ALL = "all";
const DOCUMENT_VIEW_KEY = "documents:view-mode";
const DOCUMENT_TAG_FILTERS_KEY = "documents:tag-filters";
const getDefaultDocumentFiltersVisibility = () => {
  if (typeof window === "undefined") {
    return true;
  }
  return window.matchMedia("(min-width: 640px)").matches;
};

const documentColumns: ColumnDef<DocumentSummary>[] = [
  {
    accessorKey: "title",
    header: ({ column }) => {
      const isSorted = column.getIsSorted();
      return (
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
            Title
            <SortIcon isSorted={isSorted} />
          </Button>
        </div>
      );
    },
    cell: ({ row }) => {
      const document = row.original;
      return (
        <div className="min-w-[220px] sm:min-w-0">
          <Link
            to="/documents/$documentId"
            params={{ documentId: String(document.id) }}
            className="text-primary font-medium hover:underline"
          >
            {document.title}
          </Link>
        </div>
      );
    },
    enableSorting: true,
    sortingFn: "alphanumeric",
    enableHiding: false,
  },
  {
    id: "last updated",
    accessorKey: "updated_at",
    header: ({ column }) => {
      const isSorted = column.getIsSorted();
      return (
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => column.toggleSorting(isSorted === "asc")}>
            Last updated
            <SortIcon isSorted={isSorted} />
          </Button>
        </div>
      );
    },
    cell: ({ row }) => {
      const updatedAt = new Date(row.original.updated_at);
      return (
        <div className="min-w-[100px] sm:min-w-0">
          <span className="text-muted-foreground">
            {formatDistanceToNow(updatedAt, { addSuffix: true })}
          </span>
        </div>
      );
    },
    sortingFn: dateSortingFn,
  },
  {
    accessorKey: "projects",
    header: "Projects",
    cell: ({ row }) => {
      const count = row.original.projects.length;
      return <span>{count}</span>;
    },
  },
  {
    id: "owner",
    header: "Owner",
    cell: ({ row }) => {
      const ownerPermission = (row.original.permissions ?? []).find((p) => p.level === "owner");
      if (!ownerPermission) {
        return <span className="text-muted-foreground">—</span>;
      }
      const ownerMember = row.original.initiative?.members?.find(
        (m) => m.user.id === ownerPermission.user_id
      );
      const ownerName = ownerMember?.user?.full_name || ownerMember?.user?.email;
      return <span>{ownerName || `User ${ownerPermission.user_id}`}</span>;
    },
  },
  {
    id: "type",
    accessorKey: "is_template",
    header: "Type",
    cell: ({ row }) => {
      const doc = row.original;
      const isFile = doc.document_type === "file";
      const fileTypeLabel = isFile
        ? getFileTypeLabel(doc.file_content_type, doc.original_filename)
        : null;

      return (
        <div className="flex items-center gap-2">
          {isFile ? (
            <Badge variant="secondary" className="flex items-center gap-1">
              {fileTypeLabel === "Excel" ? (
                <FileSpreadsheet className="h-3 w-3" />
              ) : fileTypeLabel === "PowerPoint" ? (
                <Presentation className="h-3 w-3" />
              ) : (
                <FileText className="h-3 w-3" />
              )}
              {fileTypeLabel}
            </Badge>
          ) : doc.is_template ? (
            <Badge variant="outline">Template</Badge>
          ) : (
            <span className="text-muted-foreground">Document</span>
          )}
        </div>
      );
    },
  },
];

type DocumentsViewProps = {
  fixedInitiativeId?: number;
  canCreate?: boolean;
};

export const DocumentsView = ({ fixedInitiativeId, canCreate }: DocumentsViewProps) => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { activeGuildId } = useGuilds();
  const searchParams = useSearch({ strict: false }) as { initiativeId?: string; create?: string };
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
  const [viewMode, setViewMode] = useState<"grid" | "table">(() => {
    if (typeof window === "undefined") {
      return "grid";
    }
    const stored = localStorage.getItem(DOCUMENT_VIEW_KEY);
    return stored === "table" || stored === "grid" ? stored : "grid";
  });
  const [tagFilters, setTagFilters] = useState<number[]>(() => {
    if (typeof window === "undefined") return [];
    const stored = localStorage.getItem(DOCUMENT_TAG_FILTERS_KEY);
    if (!stored) return [];
    try {
      const parsed = JSON.parse(stored);
      return Array.isArray(parsed) ? parsed.filter(Number.isFinite) : [];
    } catch {
      return [];
    }
  });
  const { data: allTags = [] } = useTags();

  // Convert tag IDs to Tag objects for TagPicker
  const selectedTagsForFilter = useMemo(() => {
    const tagMap = new Map(allTags.map((t) => [t.id, t]));
    return tagFilters.map((id) => tagMap.get(id)).filter((t): t is Tag => t !== undefined);
  }, [allTags, tagFilters]);

  const handleTagFiltersChange = (newTags: TagSummary[]) => {
    setTagFilters(newTags.map((t) => t.id));
  };

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

  const documentsQuery = useQuery<DocumentSummary[]>({
    queryKey: [
      "documents",
      { guildId: activeGuildId, initiative: initiativeFilter, search: searchQuery, tagFilters },
    ],
    queryFn: async () => {
      const params: Record<string, string | string[]> = {};
      if (initiativeFilter !== INITIATIVE_FILTER_ALL) {
        params.initiative_id = initiativeFilter;
      }
      if (searchQuery.trim()) {
        params.search = searchQuery.trim();
      }
      if (tagFilters.length > 0) {
        params.tag_ids = tagFilters.map(String);
      }
      const response = await apiClient.get<DocumentSummary[]>("/documents/", { params });
      return response.data;
    },
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives", { guildId: activeGuildId }],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  // Filter initiatives where user can create documents
  const creatableInitiatives = useMemo(() => {
    const initiatives = initiativesQuery.data ?? [];
    if (!user) {
      return [];
    }
    return initiatives.filter((initiative) =>
      initiative.members.some((member) => member.user.id === user.id && member.can_create_docs)
    );
  }, [initiativesQuery.data, user]);

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

  // Check if user has write access on all selected documents (required for duplicate)
  const canDuplicateSelectedDocuments = useMemo(() => {
    if (!user || selectedDocuments.length === 0) {
      return false;
    }
    return selectedDocuments.every((doc) => {
      const permission = (doc.permissions ?? []).find((p) => p.user_id === user.id);
      return permission?.level === "owner" || permission?.level === "write";
    });
  }, [selectedDocuments, user]);

  // Check if user can view docs for the filtered initiative
  const canViewDocs = useMemo(() => {
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
  }, [lockedInitiativeId, filteredInitiativeId, user, initiativesQuery.data]);

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
    localStorage.setItem(DOCUMENT_VIEW_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    localStorage.setItem(DOCUMENT_TAG_FILTERS_KEY, JSON.stringify(tagFilters));
  }, [tagFilters]);

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
      to: "/documents/$documentId",
      params: { documentId: String(document.id) },
    });
  };

  const handleCreateDialogOpenChange = (open: boolean) => {
    setCreateDialogOpen(open);
    // Clear ?create from URL when dialog closes
    if (!open && searchParams.create) {
      isClosingCreateDialog.current = true;
      router.navigate({
        to: "/documents",
        search: { initiativeId: searchParams.initiativeId },
        replace: true,
      });
    }
  };

  const deleteDocuments = useMutation({
    mutationFn: async (documentIds: number[]) => {
      await Promise.all(documentIds.map((id) => apiClient.delete(`/documents/${id}`)));
    },
    onSuccess: (_data, documentIds) => {
      const count = documentIds.length;
      toast.success(`${count} document${count === 1 ? "" : "s"} deleted`);
      setSelectedDocuments([]);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to delete documents right now.";
      toast.error(message);
    },
  });

  const duplicateDocuments = useMutation({
    mutationFn: async (documentsToClone: DocumentSummary[]) => {
      const results = await Promise.all(
        documentsToClone.map((doc) => {
          const payload = {
            target_initiative_id: doc.initiative?.id,
            title: `${doc.title} (copy)`,
          };
          return apiClient.post<DocumentRead>(`/documents/${doc.id}/copy`, payload);
        })
      );
      return results.map((r) => r.data);
    },
    onSuccess: (data) => {
      const count = data.length;
      toast.success(`${count} document${count === 1 ? "" : "s"} duplicated`);
      setSelectedDocuments([]);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to duplicate documents right now.";
      toast.error(message);
    },
  });

  const initiatives = initiativesQuery.data ?? [];
  // Filter initiatives where user can view docs (for the dropdown)
  const viewableInitiatives = useMemo(() => {
    const allInitiatives = initiativesQuery.data ?? [];
    if (!user) return allInitiatives;
    return allInitiatives.filter((initiative) => {
      const membership = initiative.members.find((m) => m.user.id === user.id);
      // If not a member, include it (backend will handle access control)
      if (!membership) return true;
      return membership.can_view_docs !== false;
    });
  }, [initiativesQuery.data, user]);
  const lockedInitiative = lockedInitiativeId
    ? (initiatives.find((initiative) => initiative.id === lockedInitiativeId) ?? null)
    : null;

  // Get IDs of initiatives where user can view docs
  const viewableInitiativeIds = useMemo(() => {
    return new Set(viewableInitiatives.map((i) => i.id));
  }, [viewableInitiatives]);

  // Filter documents to only show those from viewable initiatives
  const documents = useMemo(() => {
    const allDocs = documentsQuery.data ?? [];
    if (!user) return allDocs;
    return allDocs.filter((doc) => viewableInitiativeIds.has(doc.initiative_id));
  }, [documentsQuery.data, user, viewableInitiativeIds]);

  return (
    <div className="space-y-6">
      {!lockedInitiativeId && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-baseline gap-4">
              <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
              {canCreateDocuments ? (
                <Button size="sm" variant="outline" onClick={() => setCreateDialogOpen(true)}>
                  <Plus className="h-4 w-4" />
                  New document
                </Button>
              ) : null}
            </div>
            <p className="text-muted-foreground text-sm">
              Keep initiative knowledge organized and attach docs to projects.
            </p>
          </div>
          <Tabs
            value={viewMode}
            onValueChange={(value) => setViewMode(value as "grid" | "table")}
            className="w-auto"
          >
            <TabsList className="grid grid-cols-2">
              <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                <LayoutGrid className="h-4 w-4" />
                Grid
              </TabsTrigger>
              <TabsTrigger value="list" className="inline-flex items-center gap-2">
                <Table className="h-4 w-4" />
                Table
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
              New document
            </Button>
          )}
          <Tabs
            value={viewMode}
            onValueChange={(value) => setViewMode(value as "grid" | "table")}
            className="w-auto"
          >
            <TabsList className="grid grid-cols-2">
              <TabsTrigger value="grid" className="inline-flex items-center gap-2">
                <LayoutGrid className="h-4 w-4" />
                Grid
              </TabsTrigger>
              <TabsTrigger value="list" className="inline-flex items-center gap-2">
                <Table className="h-4 w-4" />
                Table
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      )}

      <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen} className="space-y-2">
        <div className="flex items-center justify-between sm:hidden">
          <div className="text-muted-foreground inline-flex items-center gap-2 text-sm font-medium">
            <Filter className="h-4 w-4" />
            Filters
          </div>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-8 px-3">
              {filtersOpen ? "Hide" : "Show"} filters
              <ChevronDown
                className={`ml-1 h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
              />
            </Button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent forceMount className="data-[state=closed]:hidden">
          <div className="border-muted bg-background/40 mt-2 flex flex-wrap items-end gap-4 rounded-md border p-3 sm:mt-0">
            <div className="w-full space-y-2 sm:flex-1">
              <Label
                htmlFor="document-search"
                className="text-muted-foreground text-xs font-medium"
              >
                Search
              </Label>
              <Input
                id="document-search"
                type="search"
                placeholder="Search documents"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
            {lockedInitiativeId ? (
              <div className="w-full space-y-2 sm:w-60">
                <Label className="text-muted-foreground text-xs font-medium">Initiative</Label>
                <p className="text-sm font-medium">
                  {lockedInitiative?.name ?? "Selected initiative"}
                </p>
              </div>
            ) : (
              <div className="w-full space-y-2 sm:w-60">
                <Label
                  htmlFor="document-initiative-filter"
                  className="text-muted-foreground text-xs font-medium"
                >
                  Initiative
                </Label>
                <Select
                  value={initiativeFilter}
                  onValueChange={(value) => setInitiativeFilter(value)}
                  disabled={initiativesQuery.isLoading}
                >
                  <SelectTrigger id="document-initiative-filter">
                    <SelectValue placeholder="All initiatives" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={INITIATIVE_FILTER_ALL}>All initiatives</SelectItem>
                    {viewableInitiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="w-full space-y-2 sm:w-48">
              <Label
                htmlFor="document-tag-filter"
                className="text-muted-foreground text-xs font-medium"
              >
                Filter by tag
              </Label>
              <TagPicker
                selectedTags={selectedTagsForFilter}
                onChange={handleTagFiltersChange}
                placeholder="All tags"
                variant="filter"
              />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {!canViewDocs ? (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardHeader>
            <CardTitle className="text-destructive">Access Restricted</CardTitle>
            <CardDescription>
              You don&apos;t have permission to view documents in this initiative. Contact an
              administrator if you believe this is an error.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : documentsQuery.isLoading ? (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading documents…
        </div>
      ) : documentsQuery.isError ? (
        <p className="text-destructive text-sm">Unable to load documents right now.</p>
      ) : documents.length > 0 ? (
        viewMode === "grid" ? (
          <div className="animate grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
            {documents.map((document) => (
              <DocumentCard key={document.id} document={document} hideInitiative />
            ))}
          </div>
        ) : (
          <>
            {selectedDocuments.length > 0 && (
              <div className="border-primary bg-primary/5 flex items-center justify-between rounded-md border p-4">
                <div className="text-sm font-medium">
                  {selectedDocuments.length} document{selectedDocuments.length === 1 ? "" : "s"}{" "}
                  selected
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      duplicateDocuments.mutate(selectedDocuments);
                    }}
                    disabled={duplicateDocuments.isPending || !canDuplicateSelectedDocuments}
                    title={
                      canDuplicateSelectedDocuments
                        ? undefined
                        : "You need edit access to duplicate documents"
                    }
                  >
                    {duplicateDocuments.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Duplicating…
                      </>
                    ) : (
                      <>
                        <Copy className="mr-2 h-4 w-4" />
                        Duplicate
                      </>
                    )}
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      if (
                        confirm(
                          `Delete ${selectedDocuments.length} document${selectedDocuments.length === 1 ? "" : "s"}?`
                        )
                      ) {
                        deleteDocuments.mutate(selectedDocuments.map((doc) => doc.id));
                      }
                    }}
                    disabled={deleteDocuments.isPending || !canDeleteSelectedDocuments}
                    title={
                      canDeleteSelectedDocuments
                        ? undefined
                        : "You can only delete documents you own"
                    }
                  >
                    {deleteDocuments.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Deleting…
                      </>
                    ) : (
                      <>
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
            <DataTable
              columns={documentColumns}
              data={documents}
              enableFilterInput
              filterInputColumnKey="title"
              filterInputPlaceholder="Filter by title..."
              enableColumnVisibilityDropdown
              enablePagination
              enableResetSorting
              enableRowSelection
              onRowSelectionChange={setSelectedDocuments}
              getRowId={(row) => String(row.id)}
              onExitSelection={() => setSelectedDocuments([])}
            />
          </>
        )
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>No documents yet</CardTitle>
            <CardDescription>
              Create your first initiative document to share briefs, decisions, or guides.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setCreateDialogOpen(true)} disabled={!canCreateDocuments}>
              Start writing
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

      {canCreateDocuments ? (
        <Button
          type="button"
          className="shadow-primary/40 fixed right-6 bottom-6 z-40 h-12 rounded-full px-6 shadow-lg"
          onClick={() => setCreateDialogOpen(true)}
        >
          <Plus className="h-4 w-4" />
          New document
        </Button>
      ) : null}
    </div>
  );
};

export const DocumentsPage = () => <DocumentsView />;
