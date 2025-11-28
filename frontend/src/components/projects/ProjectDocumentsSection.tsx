import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Loader2, Paperclip, Plus, Unlink } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
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

  const availableDocsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "initiative", initiativeId],
    queryFn: async () => {
      const response = await apiClient.get<DocumentSummary[]>("/documents/", {
        params: { initiative_id: initiativeId },
      });
      return response.data;
    },
    enabled: dialogOpen,
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
      const response = await apiClient.post(`/projects/${projectId}/documents/${selectedDocumentId}`, {});
      return response.data;
    },
    onSuccess: () => {
      toast.success("Document attached.");
      setDialogOpen(false);
      setSelectedDocumentId("");
      void queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
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
    },
    onError: () => {
      toast.error("Unable to detach document.");
    },
  });

  const availableDocs = useMemo(() => {
    const items = availableDocsQuery.data ?? [];
    return items.filter((doc) => !attachedDocumentIds.has(doc.id));
  }, [availableDocsQuery.data, attachedDocumentIds]);

  return (
    <div className="space-y-4 rounded-2xl border bg-card p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Documents</h2>
          <p className="text-sm text-muted-foreground">
            Attach initiative documents to keep context close to project work.
          </p>
        </div>
        {canEdit ? (
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button type="button" size="sm" variant="outline">
                <Plus className="mr-2 h-4 w-4" />
                Attach document
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Select document</DialogTitle>
                <DialogDescription>
                  Only documents created under this initiative are available.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <Select
                  value={selectedDocumentId}
                  onValueChange={(value) => setSelectedDocumentId(value)}
                  disabled={availableDocsQuery.isLoading}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose document" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableDocs.length === 0 ? (
                      <SelectItem value="none" disabled>
                        No documents available
                      </SelectItem>
                    ) : (
                      availableDocs.map((doc) => (
                        <SelectItem key={doc.id} value={String(doc.id)}>
                          {doc.title}
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Need a new one? Create it from the Documents tab and return here to attach it.
                </p>
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
        ) : null}
      </div>
      {documents.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No documents attached yet. {canEdit ? "Attach one to highlight relevant briefs." : ""}
        </p>
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => (
            <div
              key={doc.document_id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3"
            >
              <div className="space-y-1">
                <Link
                  to={`/documents/${doc.document_id}`}
                  className="inline-flex items-center gap-2 font-medium hover:text-primary"
                >
                  <Paperclip className="h-4 w-4 text-muted-foreground" />
                  {doc.title}
                </Link>
                <p className="text-xs text-muted-foreground">
                  Updated {formatDistanceToNow(new Date(doc.updated_at), { addSuffix: true })}
                </p>
                <Badge variant="secondary">
                  Attached {formatDistanceToNow(new Date(doc.attached_at), { addSuffix: true })}
                </Badge>
              </div>
              {canEdit ? (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => detachMutation.mutate(doc.document_id)}
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
          ))}
        </div>
      )}
    </div>
  );
};
