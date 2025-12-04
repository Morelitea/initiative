import { useEffect, useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ChevronDown, Filter, LayoutGrid, Loader2, Plus, Table } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { useAuth } from "@/hooks/useAuth";
import type { DocumentRead, DocumentSummary, Initiative } from "@/types/api";
import { SortIcon } from "@/components/SortIcon";

const INITIATIVE_FILTER_ALL = "all";
const DOCUMENT_VIEW_KEY = "documents:view-mode";
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
          Title
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => column.toggleSorting(isSorted === "asc")}
          >
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
            to={`/documents/${document.id}`}
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
          Last updated
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => column.toggleSorting(isSorted === "asc")}
          >
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
    sortingFn: "datetime",
  },
  {
    accessorKey: "initiative",
    header: "Initiative",
    cell: ({ row }) => {
      const initiative = row.original.initiative;
      if (!initiative) {
        return <span className="text-muted-foreground">—</span>;
      }
      return (
        <span className="inline-flex min-w-[140px] items-center gap-2">
          <InitiativeColorDot color={initiative.color} />
          {initiative.name}
        </span>
      );
    },
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
    id: "type",
    accessorKey: "is_template",
    header: "Type",
    cell: ({ row }) =>
      row.original.is_template ? (
        <Badge variant="outline">Template</Badge>
      ) : (
        <span className="text-muted-foreground">Document</span>
      ),
  },
];

type DocumentsViewProps = {
  fixedInitiativeId?: number;
};

export const DocumentsView = ({ fixedInitiativeId }: DocumentsViewProps) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const lockedInitiativeId = typeof fixedInitiativeId === "number" ? fixedInitiativeId : null;
  const [initiativeFilter, setInitiativeFilter] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : INITIATIVE_FILTER_ALL
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(getDefaultDocumentFiltersVisibility);
  const [viewMode, setViewMode] = useState<"grid" | "table">(() => {
    if (typeof window === "undefined") {
      return "grid";
    }
    const stored = localStorage.getItem(DOCUMENT_VIEW_KEY);
    return stored === "table" || stored === "grid" ? stored : "grid";
  });

  useEffect(() => {
    if (lockedInitiativeId) {
      const lockedValue = String(lockedInitiativeId);
      setInitiativeFilter((prev) => (prev === lockedValue ? prev : lockedValue));
    }
  }, [lockedInitiativeId]);

  const documentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", { initiative: initiativeFilter, search: searchQuery }],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (initiativeFilter !== INITIATIVE_FILTER_ALL) {
        params.initiative_id = initiativeFilter;
      }
      if (searchQuery.trim()) {
        params.search = searchQuery.trim();
      }
      const response = await apiClient.get<DocumentSummary[]>("/documents/", { params });
      return response.data;
    },
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  const manageableInitiatives = useMemo(() => {
    const initiatives = initiativesQuery.data ?? [];
    if (!user) {
      return [];
    }
    if (user.role === "admin") {
      return initiatives;
    }
    return initiatives.filter((initiative) =>
      initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiativesQuery.data, user]);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newInitiativeId, setNewInitiativeId] = useState<string>(
    lockedInitiativeId ? String(lockedInitiativeId) : ""
  );
  const [isTemplateDocument, setIsTemplateDocument] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const canCreateDocuments = lockedInitiativeId
    ? manageableInitiatives.some((initiative) => initiative.id === lockedInitiativeId)
    : manageableInitiatives.length > 0;

  const templateDocumentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<DocumentSummary[]>("/documents/");
      return response.data;
    },
    enabled: canCreateDocuments,
  });

  const manageableTemplates = useMemo(() => {
    if (!templateDocumentsQuery.data || !user) {
      return [];
    }
    if (user.role === "admin") {
      return templateDocumentsQuery.data.filter((document) => document.is_template);
    }
    return templateDocumentsQuery.data.filter((document) => {
      if (!document.is_template) {
        return false;
      }
      const initiativeMembers = document.initiative?.members ?? [];
      return initiativeMembers.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      );
    });
  }, [templateDocumentsQuery.data, user]);

  useEffect(() => {
    localStorage.setItem(DOCUMENT_VIEW_KEY, viewMode);
  }, [viewMode]);

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

  useEffect(() => {
    if (!createDialogOpen) {
      setIsTemplateDocument(false);
      setSelectedTemplateId("");
      return;
    }
    if (lockedInitiativeId) {
      setNewInitiativeId(String(lockedInitiativeId));
      return;
    }
    if (!newInitiativeId && manageableInitiatives.length > 0) {
      setNewInitiativeId(String(manageableInitiatives[0].id));
    }
  }, [createDialogOpen, manageableInitiatives, newInitiativeId, lockedInitiativeId]);

  useEffect(() => {
    if (isTemplateDocument && selectedTemplateId) {
      setSelectedTemplateId("");
    }
  }, [isTemplateDocument, selectedTemplateId]);

  useEffect(() => {
    if (!selectedTemplateId) {
      return;
    }
    const isValid = manageableTemplates.some(
      (document) => String(document.id) === selectedTemplateId
    );
    if (!isValid) {
      setSelectedTemplateId("");
    }
  }, [manageableTemplates, selectedTemplateId]);

  const createDocument = useMutation({
    mutationFn: async () => {
      const trimmedTitle = newTitle.trim();
      if (!trimmedTitle) {
        throw new Error("Document title is required");
      }
      const resolvedInitiativeId =
        newInitiativeId || (lockedInitiativeId ? String(lockedInitiativeId) : "");
      if (!resolvedInitiativeId) {
        throw new Error("Select an initiative");
      }
      if (selectedTemplateId) {
        const payload = {
          target_initiative_id: Number(resolvedInitiativeId),
          title: trimmedTitle,
        };
        const response = await apiClient.post<DocumentRead>(
          `/documents/${selectedTemplateId}/copy`,
          payload
        );
        return response.data;
      }
      const payload = {
        title: trimmedTitle,
        initiative_id: Number(resolvedInitiativeId),
        is_template: isTemplateDocument,
      };
      const response = await apiClient.post<DocumentRead>("/documents/", payload);
      return response.data;
    },
    onSuccess: (document) => {
      toast.success("Document created");
      setCreateDialogOpen(false);
      setNewTitle("");
      setIsTemplateDocument(false);
      setSelectedTemplateId("");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      navigate(`/documents/${document.id}`);
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to create document right now.";
      toast.error(message);
    },
  });

  const initiatives = initiativesQuery.data ?? [];
  const lockedInitiative = lockedInitiativeId
    ? (initiatives.find((initiative) => initiative.id === lockedInitiativeId) ?? null)
    : null;
  const documents = documentsQuery.data ?? [];

  return (
    <div className="space-y-6">
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
                    {initiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>

      {documentsQuery.isLoading ? (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading documents…
        </div>
      ) : null}

      {documentsQuery.isError ? (
        <p className="text-destructive text-sm">Unable to load documents right now.</p>
      ) : null}

      {!documentsQuery.isLoading && !documentsQuery.isError ? (
        documents.length > 0 ? (
          viewMode === "grid" ? (
            <div className="flex flex-wrap gap-4">
              {documents.map((document) => (
                <DocumentCard
                  key={document.id}
                  document={document}
                  className="w-full sm:w-[calc(50%-0.5rem)] lg:w-[calc(33.333%-0.75rem)] xl:w-[calc(25%-0.75rem)] 2xl:w-[calc(20%-0.8rem)]"
                />
              ))}
            </div>
          ) : (
            <DataTable
              columns={documentColumns}
              data={documents}
              enableFilterInput
              filterInputColumnKey="title"
              filterInputPlaceholder="Filter by title..."
              enableColumnVisibilityDropdown
              enablePagination
              enableResetSorting
            />
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
        )
      ) : null}

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
          <DialogHeader>
            <DialogTitle>New document</DialogTitle>
            <DialogDescription>
              Documents live inside an initiative and can be attached to projects later.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="new-document-title">Title</Label>
              <Input
                id="new-document-title"
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder="Product launch brief"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-document-initiative">Initiative</Label>
              {lockedInitiativeId ? (
                <div className="rounded-md border px-3 py-2 text-sm">
                  {lockedInitiative?.name ?? "Selected initiative"}
                </div>
              ) : (
                <Select
                  value={newInitiativeId}
                  onValueChange={(value) => setNewInitiativeId(value)}
                  disabled={!canCreateDocuments}
                >
                  <SelectTrigger id="new-document-initiative">
                    <SelectValue placeholder="Select initiative" />
                  </SelectTrigger>
                  <SelectContent>
                    {manageableInitiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-document-template-selector">Start from template</Label>
              <Select
                value={selectedTemplateId || undefined}
                onValueChange={(value) => setSelectedTemplateId(value)}
                disabled={
                  templateDocumentsQuery.isLoading ||
                  manageableTemplates.length === 0 ||
                  isTemplateDocument
                }
              >
                <SelectTrigger id="new-document-template-selector">
                  <SelectValue
                    placeholder={
                      templateDocumentsQuery.isLoading
                        ? "Loading templates…"
                        : manageableTemplates.length > 0
                          ? "Select template (optional)"
                          : "No templates available"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {manageableTemplates.map((template) => (
                    <SelectItem key={template.id} value={String(template.id)}>
                      {template.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="bg-muted/40 flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-medium">Save as template</p>
                <p className="text-muted-foreground text-xs">
                  Template documents are best duplicated or copied into other initiatives.
                </p>
              </div>
              <Switch
                id="new-document-template"
                checked={isTemplateDocument}
                onCheckedChange={setIsTemplateDocument}
                aria-label="Toggle template status for the new document"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              onClick={() => createDocument.mutate()}
              disabled={
                createDocument.isPending ||
                !newTitle.trim() ||
                (!newInitiativeId && !lockedInitiativeId)
              }
            >
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating…
                </>
              ) : (
                "Create document"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
