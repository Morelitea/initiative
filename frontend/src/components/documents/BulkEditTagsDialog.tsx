import { useCallback, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
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
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TagPicker } from "@/components/tags/TagPicker";
import type { DocumentSummary, TagSummary } from "@/types/api";

interface BulkEditTagsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documents: DocumentSummary[];
  onSuccess: () => void;
}

export function BulkEditTagsDialog({
  open,
  onOpenChange,
  documents,
  onSuccess,
}: BulkEditTagsDialogProps) {
  const { t } = useTranslation("documents");
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"add" | "remove">("add");
  const [tagsToAdd, setTagsToAdd] = useState<TagSummary[]>([]);
  const [tagsToRemove, setTagsToRemove] = useState<TagSummary[]>([]);
  const [isPending, setIsPending] = useState(false);

  // Collect all tags that appear on at least one selected document (for remove mode)
  const existingTags = useMemo(() => {
    const tagMap = new Map<number, TagSummary>();
    for (const doc of documents) {
      for (const tag of doc.tags ?? []) {
        if (!tagMap.has(tag.id)) {
          tagMap.set(tag.id, tag);
        }
      }
    }
    return Array.from(tagMap.values());
  }, [documents]);

  const resetState = useCallback(() => {
    setTagsToAdd([]);
    setTagsToRemove([]);
    setMode("add");
  }, []);

  const handleOpenChange = useCallback(
    (value: boolean) => {
      if (!value) {
        resetState();
      }
      onOpenChange(value);
    },
    [onOpenChange, resetState]
  );

  const handleApply = useCallback(async () => {
    if (mode === "add" && tagsToAdd.length === 0) return;
    if (mode === "remove" && tagsToRemove.length === 0) return;

    setIsPending(true);
    try {
      if (mode === "add") {
        const addIds = new Set(tagsToAdd.map((t) => t.id));
        await Promise.all(
          documents.map((doc) => {
            const currentIds = new Set((doc.tags ?? []).map((t) => t.id));
            const merged = [...currentIds, ...addIds];
            const uniqueIds = [...new Set(merged)];
            return apiClient.put(`/documents/${doc.id}/tags`, { tag_ids: uniqueIds });
          })
        );
        toast.success(t("bulkTags.tagsAdded", { count: documents.length }));
      } else {
        const removeIds = new Set(tagsToRemove.map((tag) => tag.id));
        await Promise.all(
          documents.map((doc) => {
            const filtered = (doc.tags ?? [])
              .filter((tag) => !removeIds.has(tag.id))
              .map((tag) => tag.id);
            return apiClient.put(`/documents/${doc.id}/tags`, { tag_ids: filtered });
          })
        );
        toast.success(t("bulkTags.tagsRemoved", { count: documents.length }));
      }

      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("bulkTags.updateError");
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  }, [
    mode,
    tagsToAdd,
    tagsToRemove,
    documents,
    queryClient,
    resetState,
    onOpenChange,
    onSuccess,
    t,
  ]);

  const canApply = mode === "add" ? tagsToAdd.length > 0 : tagsToRemove.length > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("bulkTags.title")}</DialogTitle>
          <DialogDescription>
            {mode === "add"
              ? t("bulkTags.descriptionAdd", { count: documents.length })
              : t("bulkTags.descriptionRemove", { count: documents.length })}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={mode} onValueChange={(v) => setMode(v as "add" | "remove")}>
          <TabsList className="w-full">
            <TabsTrigger value="add" className="flex-1">
              {t("bulkTags.tabAdd")}
            </TabsTrigger>
            <TabsTrigger value="remove" className="flex-1">
              {t("bulkTags.tabRemove")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="add" className="mt-4">
            <TagPicker
              selectedTags={tagsToAdd}
              onChange={setTagsToAdd}
              placeholder={t("bulkTags.addPlaceholder")}
            />
          </TabsContent>

          <TabsContent value="remove" className="mt-4">
            {existingTags.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("bulkTags.noTags")}</p>
            ) : (
              <TagPicker
                selectedTags={tagsToRemove}
                onChange={(tags) =>
                  setTagsToRemove(tags.filter((tag) => existingTags.some((e) => e.id === tag.id)))
                }
                placeholder={t("bulkTags.removePlaceholder")}
              />
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isPending}>
            {t("common:cancel")}
          </Button>
          <Button onClick={() => void handleApply()} disabled={isPending || !canApply}>
            {isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {t("bulkTags.applying")}
              </>
            ) : (
              t("bulkTags.apply")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
