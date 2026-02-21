import { useCallback, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

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
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import type { DialogWithSuccessProps } from "@/types/dialog";

/** Any entity that has an `id` and optional `tags`. */
interface TaggableItem {
  id: number;
  tags?: TagSummary[] | null;
}

interface BulkEditTagsDialogProps<T extends TaggableItem> extends DialogWithSuccessProps {
  items: T[];
  /** API call to set the full tag list for a single item. */
  setTags: (itemId: number, tagIds: number[]) => Promise<unknown>;
  /** Called after all API calls succeed to invalidate relevant caches. */
  onInvalidate: () => void;
  /** i18n labels — each dialog can provide its own strings. */
  labels: {
    title: string;
    descriptionAdd: string;
    descriptionRemove: string;
    tabAdd: string;
    tabRemove: string;
    addPlaceholder: string;
    removePlaceholder: string;
    noTags: string;
    tagsAdded: string;
    tagsRemoved: string;
    applying: string;
    apply: string;
    cancel: string;
    updateError: string;
  };
}

export function BulkEditTagsDialog<T extends TaggableItem>({
  open,
  onOpenChange,
  items,
  setTags,
  onInvalidate,
  onSuccess,
  labels,
}: BulkEditTagsDialogProps<T>) {
  const [mode, setMode] = useState<"add" | "remove">("add");
  const [tagsToAdd, setTagsToAdd] = useState<TagSummary[]>([]);
  const [tagsToRemove, setTagsToRemove] = useState<TagSummary[]>([]);
  const [isPending, setIsPending] = useState(false);

  const existingTags = useMemo(() => {
    const tagMap = new Map<number, TagSummary>();
    for (const item of items) {
      for (const tag of item.tags ?? []) {
        if (!tagMap.has(tag.id)) {
          tagMap.set(tag.id, tag);
        }
      }
    }
    return Array.from(tagMap.values());
  }, [items]);

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
          items.map((item) => {
            const currentIds = new Set((item.tags ?? []).map((t) => t.id));
            const merged = [...currentIds, ...addIds];
            const uniqueIds = [...new Set(merged)];
            return setTags(item.id, uniqueIds);
          })
        );
        toast.success(labels.tagsAdded);
      } else {
        const removeIds = new Set(tagsToRemove.map((t) => t.id));
        await Promise.all(
          items.map((item) => {
            const filtered = (item.tags ?? []).filter((t) => !removeIds.has(t.id)).map((t) => t.id);
            return setTags(item.id, filtered);
          })
        );
        toast.success(labels.tagsRemoved);
      }

      onInvalidate();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      const message = error instanceof Error ? error.message : labels.updateError;
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  }, [
    mode,
    tagsToAdd,
    tagsToRemove,
    items,
    setTags,
    onInvalidate,
    resetState,
    onOpenChange,
    onSuccess,
    labels,
  ]);

  const canApply = mode === "add" ? tagsToAdd.length > 0 : tagsToRemove.length > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{labels.title}</DialogTitle>
          <DialogDescription>
            {mode === "add" ? labels.descriptionAdd : labels.descriptionRemove}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={mode} onValueChange={(v) => setMode(v as "add" | "remove")}>
          <TabsList className="w-full">
            <TabsTrigger value="add" className="flex-1">
              {labels.tabAdd}
            </TabsTrigger>
            <TabsTrigger value="remove" className="flex-1">
              {labels.tabRemove}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="add" className="mt-4">
            <TagPicker
              selectedTags={tagsToAdd}
              onChange={setTagsToAdd}
              placeholder={labels.addPlaceholder}
            />
          </TabsContent>

          <TabsContent value="remove" className="mt-4">
            {existingTags.length === 0 ? (
              <p className="text-muted-foreground text-sm">{labels.noTags}</p>
            ) : (
              <TagPicker
                selectedTags={tagsToRemove}
                onChange={(tags) =>
                  setTagsToRemove(tags.filter((t) => existingTags.some((e) => e.id === t.id)))
                }
                placeholder={labels.removePlaceholder}
              />
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isPending}>
            {labels.cancel}
          </Button>
          <Button onClick={() => void handleApply()} disabled={isPending || !canApply}>
            {isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {labels.applying}
              </>
            ) : (
              labels.apply
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
