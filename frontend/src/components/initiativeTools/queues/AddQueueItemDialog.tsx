import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LinkedEntityPicker } from "@/components/initiativeTools/queues/LinkedEntityPicker";
import { useQueueItemForm } from "@/components/initiativeTools/queues/useQueueItemForm";
import { MemberSelect } from "@/components/members/MemberSearchSelect";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useCreateQueueItem } from "@/hooks/useQueues";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import type { DialogProps } from "@/types/dialog";

type AddQueueItemDialogProps = DialogProps & {
  queueId: number;
  initiativeId: number;
  onSuccess?: () => void;
};

export const AddQueueItemDialog = ({
  open,
  onOpenChange,
  queueId,
  initiativeId,
  onSuccess,
}: AddQueueItemDialogProps) => {
  const { t } = useTranslation(["queues", "common"]);
  const gp = useGuildPath();

  const {
    label,
    setLabel,
    position,
    setPosition,
    color,
    setColor,
    notes,
    setNotes,
    isVisible,
    setIsVisible,
    selectedTags,
    setSelectedTags,
    userId,
    setUserId,
    selectedDocs,
    setSelectedDocs,
    selectedTasks,
    setSelectedTasks,
    setDocSearch,
    setDocPickerOpen,
    setTaskSearch,
    setTaskPickerOpen,
    docResults,
    docsLoading,
    taskResults,
    tasksLoading,
  } = useQueueItemForm({ open, initiativeId });

  const createItem = useCreateQueueItem(queueId, {
    onSuccess: () => {
      toast.success(t("itemAdded"));
      onOpenChange(false);
      onSuccess?.();
    },
  });

  const isAdding = createItem.isPending;
  const canSubmit = label.trim() && !isAdding;

  const handleSubmit = () => {
    const trimmedLabel = label.trim();
    if (!trimmedLabel) return;
    createItem.mutate({
      label: trimmedLabel,
      position: position ? Number(position) : undefined,
      color: color || undefined,
      notes: notes.trim() || undefined,
      is_visible: isVisible,
      tag_ids: selectedTags.length > 0 ? selectedTags.map((tg) => tg.id) : undefined,
      user_id: userId ?? undefined,
      document_ids: selectedDocs.length > 0 ? selectedDocs.map((doc) => doc.id) : undefined,
      task_ids: selectedTasks.length > 0 ? selectedTasks.map((task) => task.id) : undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border bg-card shadow-2xl">
        <DialogHeader>
          <DialogTitle>{t("addItem")}</DialogTitle>
          <DialogDescription>{t("noItemsDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Label */}
          <div className="space-y-2">
            <Label htmlFor="add-item-label">{t("label")}</Label>
            <Input
              id="add-item-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t("labelPlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              autoFocus
            />
          </div>

          {/* Position (Initiative Roll) */}
          <div className="space-y-2">
            <Label htmlFor="add-item-position">{t("position")}</Label>
            <Input
              id="add-item-position"
              type="number"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              placeholder="0"
            />
            <p className="text-muted-foreground text-xs">{t("positionHelp")}</p>
          </div>

          {/* Color */}
          <div className="space-y-2">
            <Label>{t("color")}</Label>
            <ColorPickerPopover
              value={color}
              onChange={setColor}
              triggerLabel={t("color")}
              className="h-9"
            />
          </div>

          {/* Notes */}
          <div className="space-y-2">
            <Label htmlFor="add-item-notes">{t("notes")}</Label>
            <Textarea
              id="add-item-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t("notesPlaceholder")}
              rows={2}
            />
          </div>

          {/* Visible toggle */}
          <div className="flex items-center justify-between rounded-lg border bg-muted/40 p-3">
            <div>
              <p className="font-medium text-sm">{t("visible")}</p>
              <p className="text-muted-foreground text-xs">
                {isVisible ? t("visible") : t("hidden")}
              </p>
            </div>
            <Switch checked={isVisible} onCheckedChange={setIsVisible} aria-label={t("visible")} />
          </div>

          {/* Tags */}
          <div className="space-y-2">
            <Label>{t("tags")}</Label>
            <TagPicker
              selectedTags={selectedTags}
              onChange={setSelectedTags}
              placeholder={t("tags")}
            />
          </div>

          {/* Linked User */}
          <div className="space-y-2">
            <Label>{t("linkedUser")}</Label>
            <div className="flex items-center gap-2">
              <MemberSelect
                scope={{ type: "initiative", initiativeId }}
                value={userId}
                onChange={setUserId}
                placeholder={t("selectUser")}
                emptyMessage={t("noUser")}
              />
              {userId !== null && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setUserId(null)}
                  className="shrink-0"
                >
                  {t("clearUser")}
                </Button>
              )}
            </div>
          </div>

          <LinkedEntityPicker
            label={t("linkedDocuments")}
            selected={selectedDocs}
            onChange={setSelectedDocs}
            results={docResults}
            loading={docsLoading}
            onSearchChange={setDocSearch}
            onOpenChange={setDocPickerOpen}
            hrefFor={(id) => gp(`/documents/${id}`)}
            placeholder={t("selectDocument")}
            emptyMessage={t("noDocuments")}
          />

          <LinkedEntityPicker
            label={t("linkedTasks")}
            selected={selectedTasks}
            onChange={setSelectedTasks}
            results={taskResults}
            loading={tasksLoading}
            onSearchChange={setTaskSearch}
            onOpenChange={setTaskPickerOpen}
            hrefFor={(id) => gp(`/tasks/${id}`)}
            placeholder={t("selectTask")}
            emptyMessage={t("noTasks")}
          />
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isAdding ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("adding")}
              </>
            ) : (
              t("addItem")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
