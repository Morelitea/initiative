import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation("documents");
  const queryClient = useQueryClient();
  const { activeGuildId } = useGuilds();
  const { user } = useAuth();

  const [selectedTemplateId, setSelectedTemplateId] = useState("");

  // Query templates
  const templateDocumentsQuery = useQuery<DocumentSummary[]>({
    queryKey: ["documents", "templates"],
    queryFn: async () => {
      const response = await apiClient.get<{ items: DocumentSummary[] }>("/documents/", {
        params: { page_size: "0" },
      });
      return response.data.items;
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
      toast.success(t("wikilink.created"));
      onOpenChange(false);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["documents", activeGuildId] });
      void queryClient.invalidateQueries({
        queryKey: ["documents", "initiative", initiativeId],
      });
      onCreated?.(document.id);
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("wikilink.createError");
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
          <AlertDialogTitle>{t("wikilink.title")}</AlertDialogTitle>
          <AlertDialogDescription>
            {canCreate
              ? t("wikilink.descriptionCanCreate", { title })
              : t("wikilink.descriptionNoPermission", { title })}
          </AlertDialogDescription>
        </AlertDialogHeader>

        {canCreate && (
          <div className="space-y-2 py-2">
            <Label htmlFor="wikilink-template">{t("wikilink.templateLabel")}</Label>
            <Select
              value={selectedTemplateId || undefined}
              onValueChange={setSelectedTemplateId}
              disabled={templateDocumentsQuery.isLoading || manageableTemplates.length === 0}
            >
              <SelectTrigger id="wikilink-template">
                <SelectValue
                  placeholder={
                    templateDocumentsQuery.isLoading
                      ? t("wikilink.loadingTemplates")
                      : manageableTemplates.length > 0
                        ? t("wikilink.blankDocument")
                        : t("wikilink.noTemplates")
                  }
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="blank">{t("wikilink.blankDocument")}</SelectItem>
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
          <AlertDialogCancel>{t("common:cancel")}</AlertDialogCancel>
          {canCreate && (
            <Button onClick={() => createDocument.mutate()} disabled={createDocument.isPending}>
              {createDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("wikilink.creating")}
                </>
              ) : (
                t("wikilink.createDocument")
              )}
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
