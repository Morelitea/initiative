import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, FilePlus, Unlink, ChevronDown, ChevronUp } from "lucide-react";
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
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { DocumentCard } from "@/components/documents/DocumentCard";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import type { DocumentSummary, ProjectDocumentLink } from "@/types/api";

type ProjectDocumentsSectionProps = {
  projectId: number;
  initiativeId: number;
  documents: ProjectDocumentLink[];
  canEdit: boolean;
};

export const ProjectDocumentsSection = ({
  projectId,
  initiativeId,
  documents,
  canEdit,
}: ProjectDocumentsSectionProps) => {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>("");
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
      void queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
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
      void queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", "initiative", initiativeId] });
    },
    onError: () => {
      toast.error("Unable to detach document.");
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
        {canEdit ? (
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button type="button" size="sm" variant="outline">
                <FilePlus className="mr-2 h-4 w-4" />
                Attach document
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-card w-full max-w-lg rounded-2xl border shadow-2xl">
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
                    Need a new one? Create it from the Documents tab and return here to attach it.
                  </p>
                </div>
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  onClick={() => attachMutation.mutate()}
                  disabled={
                    attachMutation.isPending || !selectedDocumentId || availableDocs.length === 0
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
        ) : null}
      </div>
      <CollapsibleContent className="space-y-4 data-[state=closed]:hidden">
        {documents.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No documents attached yet. {canEdit ? "Attach one to highlight relevant briefs." : ""}
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
                        {canEdit ? (
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
