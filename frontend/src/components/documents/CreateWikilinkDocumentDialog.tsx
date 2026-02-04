import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import { useGuilds } from "@/hooks/useGuilds";
import type { DocumentRead } from "@/types/api";

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

  const createDocument = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<DocumentRead>("/documents/", {
        title: title.trim(),
        initiative_id: initiativeId,
      });
      return response.data;
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
    <AlertDialog open={open} onOpenChange={onOpenChange}>
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
