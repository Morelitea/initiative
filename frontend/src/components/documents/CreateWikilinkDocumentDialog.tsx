import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import type { DocumentRead, DocumentSummary } from "@/types/api";

interface CreateWikilinkDocumentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Title of the document to create */
  title: string;
  /** Initiative ID where the document will be created */
  initiativeId: number;
  /** Whether the user has permission to create documents */
  canCreate: boolean;
  /** Called after successful creation with the new document ID */
  onCreated?: (documentId: number) => void;
}

export function CreateWikilinkDocumentDialog({
  open,
  onOpenChange,
  title,
  initiativeId,
  canCreate,
  onCreated,
}: CreateWikilinkDocumentDialogProps) {
  const queryClient = useQueryClient();
  const { activeGuildId } = useGuilds();
  const { user } = useAuth();

  const [selectedTemplateId, setSelectedTemplateId] = useState("");

  // Query templates
  const templateDocumentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<DocumentSummary[]>("/documents/");
      return response.data;
    },
    enabled: open && canCreate,
  });

  // Filter templates user can access
  const manageableTemplates = useMemo(() => {
    if (!templateDocumentsQuery.data || !user) return [];
    return templateDocumentsQuery.data.filter((doc) => {
      if (!doc.is_template) return false;
      const permission = (doc.permissions ?? []).find((p) => p.user_id === user.id);
      return Boolean(permission);
    });
  }, [templateDocumentsQuery.data, user]);

  // Reset template selection when dialog closes
  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      setSelectedTemplateId("");
    }
    onOpenChange(newOpen);
  };

  const createDocument = useMutation({
    mutationFn: async () => {
      // Use template if selected and not "blank"
      if (selectedTemplateId && selectedTemplateId !== "blank") {
        const response = await apiClient.post<DocumentRead>(
          `/documents/${selectedTemplateId}/copy`,
          { target_initiative_id: initiativeId, title: title.trim() }
        );
        return response.data;
      } else {
        const response = await apiClient.post<DocumentRead>("/documents/", {
          title: title.trim(),
          initiative_id: initiativeId,
        });
        return response.data;
      }
    },
    onSuccess: (document) => {
      toast.success("Document created");
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", activeGuildId] });
      void queryClient.invalidateQueries({
        queryKey: ["documents", "initiative", initiativeId],
      });
      onCreated?.(document.id);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to create document.";
      // Check for axios error response
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const detail = axiosError.response?.data?.detail;
      toast.error(detail || message);
    },
  });

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Create document</AlertDialogTitle>
          <AlertDialogDescription>
            {canCreate ? (
              <>
                The document &ldquo;{title}&rdquo; doesn&apos;t exist yet. Would you like to create
                it?
              </>
            ) : (
              <>
                The document &ldquo;{title}&rdquo; doesn&apos;t exist. You don&apos;t have
                permission to create documents in this initiative.
              </>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {canCreate && (
          <div className="space-y-2 py-2">
            <Label htmlFor="wikilink-template">Template (optional)</Label>
            <Select
              value={selectedTemplateId || undefined}
              onValueChange={setSelectedTemplateId}
              disabled={templateDocumentsQuery.isLoading || manageableTemplates.length === 0}
            >
              <SelectTrigger id="wikilink-template">
                <SelectValue
                  placeholder={
                    templateDocumentsQuery.isLoading
                      ? "Loading templates…"
                      : manageableTemplates.length > 0
                        ? "Blank document"
                        : "No templates available"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="blank">Blank document</SelectItem>
                {manageableTemplates.map((template) => (
                  <SelectItem key={template.id} value={String(template.id)}>
                    {template.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          {canCreate && (
            <Button onClick={() => createDocument.mutate()} disabled={createDocument.isPending}>
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                "Create document"
              )}
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
