import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Link, Unlink, ChevronDown, ChevronUp, FilePlus, X } from "lucide-react";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { DocumentCard } from "@/components/documents/DocumentCard";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import { useAuth } from "@/hooks/useAuth";
import type { DocumentRead, DocumentSummary, ProjectDocumentLink } from "@/types/api";

type ProjectDocumentsSectionProps = {
  projectId: number;
  initiativeId: number;
  documents: ProjectDocumentLink[];
  canCreate: boolean;
  canAttach: boolean;
};

export const ProjectDocumentsSection = ({
  projectId,
  initiativeId,
  documents,
  canCreate,
  canAttach,
}: ProjectDocumentsSectionProps) => {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("");
  const [newDocumentTitle, setNewDocumentTitle] = useState("");
  const [isTemplateDocument, setIsTemplateDocument] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const storageKey = `project:${projectId}:documentsCollapsed`;
  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") {
      return false;
    }
    const stored = localStorage.getItem(storageKey);
    return stored === "true";
  });

  const initiativeDocsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "initiative", initiativeId],
    queryFn: async () => {
      const response = await apiClient.get<DocumentSummary[]>("/documents/", {
        params: { initiative_id: initiativeId },
      });
      return response.data;
    },
  });

  const templateDocumentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<DocumentSummary[]>("/documents/");
      return response.data;
    },
    enabled: canCreate,
  });

  // Pure DAC: user can use templates they have any permission on
  const manageableTemplates = useMemo(() => {
    if (!templateDocumentsQuery.data || !user) {
      return [];
    }
    return templateDocumentsQuery.data.filter((document) => {
      if (!document.is_template) {
        return false;
      }
      // User can use template if they have any permission on it
      const permission = (document.permissions ?? []).find((p) => p.user_id === user.id);
      return Boolean(permission);
    });
  }, [templateDocumentsQuery.data, user]);

  const attachedDocumentIds = useMemo(
    () => new Set(documents.map((doc) => doc.document_id)),
    [documents]
  );

  const attachMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDocumentId) {
        throw new Error("Select a document to attach.");
      }
      const response = await apiClient.post(
        `/projects/${projectId}/documents/${selectedDocumentId}`,
        {}
      );
      return response.data;
    },
    onSuccess: () => {
      toast.success("Document attached.");
      setDialogOpen(false);
      setSelectedDocumentId("");
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "initiative", initiativeId] });
    },
    onError: () => {
      toast.error("Unable to attach document.");
    },
  });

  const detachMutation = useMutation({
    mutationFn: async (documentId: number) => {
      await apiClient.delete(`/projects/${projectId}/documents/${documentId}`);
      return documentId;
    },
    onSuccess: () => {
      toast.success("Document detached.");
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "initiative", initiativeId] });
    },
    onError: () => {
      toast.error("Unable to detach document.");
    },
  });

  const createDocumentMutation = useMutation({
    mutationFn: async () => {
      const trimmedTitle = newDocumentTitle.trim();
      if (!trimmedTitle) {
        throw new Error("Document title is required");
      }

      let newDocument: DocumentRead;

      // If copying from template
      if (selectedTemplateId) {
        const payload = {
          target_initiative_id: initiativeId,
          title: trimmedTitle,
        };
        const response = await apiClient.post<DocumentRead>(
          `/documents/${selectedTemplateId}/copy`,
          payload
        );
        newDocument = response.data;
      } else {
        // Create new document
        const createResponse = await apiClient.post<DocumentRead>("/documents/", {
          title: trimmedTitle,
          initiative_id: initiativeId,
          is_template: isTemplateDocument,
        });
        newDocument = createResponse.data;
      }

      // Attach it to the project
      await apiClient.post(`/projects/${projectId}/documents/${newDocument.id}`, {});

      return newDocument;
    },
    onSuccess: () => {
      toast.success("Document created and attached.");
      setCreateDialogOpen(false);
      setNewDocumentTitle("");
      setIsTemplateDocument(false);
      setSelectedTemplateId("");
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "initiative", initiativeId] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to create document.";
      toast.error(message);
    },
  });

  const initiativeDocuments = useMemo(
    () => initiativeDocsQuery.data ?? [],
    [initiativeDocsQuery.data]
  );

  const documentsById = useMemo(() => {
    const map = new Map<number, DocumentSummary>();
    initiativeDocuments.forEach((doc) => map.set(doc.id, doc));
    return map;
  }, [initiativeDocuments]);

  const availableDocs = useMemo(() => {
    return initiativeDocuments.filter((doc) => !attachedDocumentIds.has(doc.id));
  }, [initiativeDocuments, attachedDocumentIds]);

  const comboboxItems = useMemo(
    () =>
      availableDocs.map((doc) => ({
        value: String(doc.id),
        label: doc.title,
      })),
    [availableDocs]
  );

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

  return (
    <Collapsible
      open={!isCollapsed}
      onOpenChange={(open) => {
        setIsCollapsed(!open);
        if (typeof window !== "undefined") {
          localStorage.setItem(storageKey, (!open).toString());
        }
      }}
      className="bg-card space-y-4 rounded-2xl border p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="inline-flex items-center gap-2">
            <h2 className="text-xl font-semibold">Documents</h2>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-full"
              onClick={() => {
                setIsCollapsed((prev) => {
                  const next = !prev;
                  if (typeof window !== "undefined") {
                    localStorage.setItem(storageKey, next.toString());
                  }
                  return next;
                });
              }}
              aria-label={isCollapsed ? "Expand documents" : "Collapse documents"}
            >
              {isCollapsed ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronUp className="h-4 w-4" />
              )}
            </Button>
          </div>
          <p className="text-muted-foreground text-sm">
            Attach initiative documents to keep context close to project work.
          </p>
        </div>
        {(canCreate || canAttach) && (
          <div className="flex items-center gap-2">
            {canCreate && (
              <Button type="button" size="sm" onClick={() => setCreateDialogOpen(true)}>
                <FilePlus className="mr-2 h-4 w-4" />
                New document
              </Button>
            )}
            {canAttach && (
              <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogTrigger asChild>
                  <Button type="button" size="sm" variant="outline">
                    <Link className="mr-2 h-4 w-4" />
                    Attach existing
                  </Button>
                </DialogTrigger>
                <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
                  <DialogHeader>
                    <DialogTitle>Attach document</DialogTitle>
                    <DialogDescription>
                      Only documents created under this initiative are available.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <SearchableCombobox
                        items={comboboxItems}
                        value={selectedDocumentId}
                        onValueChange={(value) => setSelectedDocumentId(value)}
                        placeholder={
                          initiativeDocsQuery.isLoading ? "Loading documents…" : "Choose document"
                        }
                        emptyMessage={
                          availableDocs.length === 0
                            ? "All initiative documents are already attached."
                            : "No matches found."
                        }
                        buttonClassName="justify-between"
                      />
                      <p className="text-muted-foreground text-xs">
                        Need a new one? Open My Initiatives and use the initiative&apos;s Documents
                        tab to create it, then return here to attach it.
                      </p>
                    </div>
                  </div>
                  <DialogFooter>
                    <Button
                      type="button"
                      onClick={() => attachMutation.mutate()}
                      disabled={
                        attachMutation.isPending ||
                        !selectedDocumentId ||
                        availableDocs.length === 0
                      }
                    >
                      {attachMutation.isPending ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Attaching…
                        </>
                      ) : (
                        "Attach"
                      )}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
          </div>
        )}
      </div>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
          <DialogHeader>
            <DialogTitle>New document</DialogTitle>
            <DialogDescription>
              Create a new document in the project&apos;s initiative and automatically attach it to
              this project.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="new-project-document-title">Title</Label>
              <Input
                id="new-project-document-title"
                value={newDocumentTitle}
                onChange={(event) => setNewDocumentTitle(event.target.value)}
                placeholder="Project requirements"
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="new-project-document-template-selector">Start from template</Label>
                {selectedTemplateId && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-auto px-2 py-1 text-xs"
                    onClick={() => setSelectedTemplateId("")}
                  >
                    <X className="mr-1 h-3 w-3" />
                    Clear
                  </Button>
                )}
              </div>
              <Select
                value={selectedTemplateId || undefined}
                onValueChange={(value) => setSelectedTemplateId(value)}
                disabled={
                  templateDocumentsQuery.isLoading ||
                  manageableTemplates.length === 0 ||
                  isTemplateDocument
                }
              >
                <SelectTrigger id="new-project-document-template-selector">
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
                id="new-project-document-template"
                checked={isTemplateDocument}
                onCheckedChange={setIsTemplateDocument}
                aria-label="Toggle template status for the new document"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              onClick={() => createDocumentMutation.mutate()}
              disabled={createDocumentMutation.isPending || !newDocumentTitle.trim()}
            >
              {createDocumentMutation.isPending ? (
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

      <CollapsibleContent className="space-y-4 data-[state=closed]:hidden">
        {documents.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No documents attached yet. {canAttach ? "Attach one to highlight relevant briefs." : ""}
          </p>
        ) : (
          <Carousel className="relative">
            <CarouselContent className="-ml-4">
              {documents.map((doc) => {
                const summary =
                  documentsById.get(doc.document_id) ?? createFallbackSummary(doc, initiativeId);
                return (
                  <CarouselItem
                    key={doc.document_id}
                    className="pl-4 sm:basis-1/2 lg:basis-1/3 xl:basis-1/4 2xl:basis-1/5"
                  >
                    <div className="space-y-2">
                      <div className="relative">
                        <DocumentCard document={summary} hideInitiative />
                        {canAttach ? (
                          <Button
                            variant="secondary"
                            size="icon"
                            className="bg-background/90 text-foreground absolute top-3 right-3 z-10 rounded-full shadow-md"
                            onClick={(event) => {
                              event.preventDefault();
                              event.stopPropagation();
                              detachMutation.mutate(doc.document_id);
                            }}
                            disabled={detachMutation.isPending}
                            aria-label="Detach document"
                          >
                            {detachMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Unlink className="h-4 w-4" />
                            )}
                          </Button>
                        ) : null}
                      </div>
                      <div className="text-muted-foreground text-xs">
                        Attached{" "}
                        {formatDistanceToNow(new Date(doc.attached_at), { addSuffix: true })}
                      </div>
                    </div>
                  </CarouselItem>
                );
              })}
            </CarouselContent>
            <CarouselPrevious className="left-0 -translate-x-1/2" />
            <CarouselNext className="right-0 translate-x-1/2" />
          </Carousel>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
};

const createFallbackSummary = (
  doc: ProjectDocumentLink,
  initiativeId: number
): DocumentSummary => ({
  id: doc.document_id,
  initiative_id: initiativeId,
  title: doc.title,
  featured_image_url: null,
  created_by_id: 0,
  updated_by_id: 0,
  created_at: doc.updated_at,
  updated_at: doc.updated_at,
  initiative: null,
  projects: [],
  is_template: false,
});
