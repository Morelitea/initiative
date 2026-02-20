import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { setTaskTagsApiV1TasksTaskIdTagsPut } from "@/api/generated/tasks/tasks";
import { invalidateAllTasks } from "@/api/query-keys";
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
import type { TagSummary, TaskListRead } from "@/api/generated/initiativeAPI.schemas";

interface BulkEditTaskTagsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tasks: TaskListRead[];
  onSuccess: () => void;
}

export function BulkEditTaskTagsDialog({
  open,
  onOpenChange,
  tasks,
  onSuccess,
}: BulkEditTaskTagsDialogProps) {
  const { t } = useTranslation(["tasks", "common"]);
  const [mode, setMode] = useState<"add" | "remove">("add");
  const [tagsToAdd, setTagsToAdd] = useState<TagSummary[]>([]);
  const [tagsToRemove, setTagsToRemove] = useState<TagSummary[]>([]);
  const [isPending, setIsPending] = useState(false);

  // Collect all tags that appear on at least one selected task (for remove mode)
  const existingTags = useMemo(() => {
    const tagMap = new Map<number, TagSummary>();
    for (const task of tasks) {
      for (const tag of task.tags ?? []) {
        if (!tagMap.has(tag.id)) {
          tagMap.set(tag.id, tag);
        }
      }
    }
    return Array.from(tagMap.values());
  }, [tasks]);

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
          tasks.map((task) => {
            const currentIds = new Set((task.tags ?? []).map((t) => t.id));
            const merged = [...currentIds, ...addIds];
            const uniqueIds = [...new Set(merged)];
            return setTaskTagsApiV1TasksTaskIdTagsPut(task.id, { tag_ids: uniqueIds });
          })
        );
        const count = tasks.length;
        toast.success(t("bulkEditTags.tagsAdded", { count }));
      } else {
        const removeIds = new Set(tagsToRemove.map((t) => t.id));
        await Promise.all(
          tasks.map((task) => {
            const filtered = (task.tags ?? []).filter((t) => !removeIds.has(t.id)).map((t) => t.id);
            return setTaskTagsApiV1TasksTaskIdTagsPut(task.id, { tag_ids: filtered });
          })
        );
        const count = tasks.length;
        toast.success(t("bulkEditTags.tagsRemoved", { count }));
      }

      void invalidateAllTasks();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("bulkEditTags.updateError");
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  }, [mode, tagsToAdd, tagsToRemove, tasks, resetState, onOpenChange, onSuccess, t]);

  const canApply = mode === "add" ? tagsToAdd.length > 0 : tagsToRemove.length > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("bulkEditTags.title")}</DialogTitle>
          <DialogDescription>
            {mode === "add"
              ? t("bulkEditTags.descriptionAdd", { count: tasks.length })
              : t("bulkEditTags.descriptionRemove", { count: tasks.length })}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={mode} onValueChange={(v) => setMode(v as "add" | "remove")}>
          <TabsList className="w-full">
            <TabsTrigger value="add" className="flex-1">
              {t("bulkEditTags.tabAdd")}
            </TabsTrigger>
            <TabsTrigger value="remove" className="flex-1">
              {t("bulkEditTags.tabRemove")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="add" className="mt-4">
            <TagPicker
              selectedTags={tagsToAdd}
              onChange={setTagsToAdd}
              placeholder={t("bulkEditTags.addPlaceholder")}
            />
          </TabsContent>

          <TabsContent value="remove" className="mt-4">
            {existingTags.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("bulkEditTags.noTags")}</p>
            ) : (
              <TagPicker
                selectedTags={tagsToRemove}
                onChange={(tags) =>
                  setTagsToRemove(tags.filter((t) => existingTags.some((e) => e.id === t.id)))
                }
                placeholder={t("bulkEditTags.removePlaceholder")}
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
                {t("bulkEditTags.applying")}
              </>
            ) : (
              t("bulkEditTags.apply")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
