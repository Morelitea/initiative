import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Loader2, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  useUpdateQueueItem,
  useDeleteQueueItem,
  useSetQueueItemTags,
  useSetQueueItemDocuments,
  useSetQueueItemTasks,
} from "@/hooks/useQueues";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import { useInitiativeDocuments } from "@/hooks/useDocuments";
import { useTasks } from "@/hooks/useTasks";
import { useGuildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
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
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { TagPicker } from "@/components/tags/TagPicker";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { QueueItemRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import type { DialogProps } from "@/types/dialog";

type EditQueueItemDialogProps = DialogProps & {
  queueId: number;
  initiativeId: number;
  item: QueueItemRead;
  readOnly?: boolean;
  onSuccess?: () => void;
};

export const EditQueueItemDialog = ({
  open,
  onOpenChange,
  queueId,
  initiativeId,
  item,
  readOnly = false,
  onSuccess,
}: EditQueueItemDialogProps) => {
  const { t } = useTranslation(["queues", "common"]);
  const gp = useGuildPath();

  const [label, setLabel] = useState(item.label);
  const [position, setPosition] = useState(String(item.position));
  const [color, setColor] = useState(item.color ?? "#6366F1");
  const [notes, setNotes] = useState(item.notes ?? "");
  const [isVisible, setIsVisible] = useState(item.is_visible);
  const [selectedTags, setSelectedTags] = useState<TagSummary[]>(item.tags);
  const [userId, setUserId] = useState<number | null>(item.user_id);
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>(
    item.documents.map((d) => d.document_id)
  );
  const [selectedTaskIds, setSelectedTaskIds] = useState<number[]>(
    item.tasks.map((t) => t.task_id)
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // Sync state when item prop changes
  useEffect(() => {
    if (open) {
      setLabel(item.label);
      setPosition(String(item.position));
      setColor(item.color ?? "#6366F1");
      setNotes(item.notes ?? "");
      setIsVisible(item.is_visible);
      setSelectedTags(item.tags);
      setUserId(item.user_id);
      setSelectedDocIds(item.documents.map((d) => d.document_id));
      setSelectedTaskIds(item.tasks.map((tk) => tk.task_id));
    }
  }, [open, item]);

  // Fetch initiative members for user picker
  const membersQuery = useInitiativeMembers(initiativeId);
  const memberItems = useMemo(
    () =>
      (membersQuery.data ?? []).map((member) => ({
        value: String(member.id),
        label: member.full_name || member.email,
      })),
    [membersQuery.data]
  );

  // Fetch initiative documents for document picker
  const docsQuery = useInitiativeDocuments(initiativeId);
  const docItems = useMemo(
    () =>
      (docsQuery.data ?? [])
        .filter((doc) => !selectedDocIds.includes(doc.id))
        .map((doc) => ({
          value: String(doc.id),
          label: doc.title,
        })),
    [docsQuery.data, selectedDocIds]
  );
  const docLookup = useMemo(() => {
    const map = new Map<number, string>();
    for (const doc of docsQuery.data ?? []) {
      map.set(doc.id, doc.title);
    }
    // Also include labels from item.documents for docs not yet loaded
    for (const doc of item.documents) {
      if (!map.has(doc.document_id) && doc.title) {
        map.set(doc.document_id, doc.title);
      }
    }
    return map;
  }, [docsQuery.data, item.documents]);

  // Fetch initiative tasks for task picker
  const tasksQuery = useTasks({
    conditions: [{ field: "initiative_ids", op: "in_", value: [initiativeId] }],
    page_size: 0,
  });
  const taskItems = useMemo(
    () =>
      (tasksQuery.data?.items ?? [])
        .filter((task) => !selectedTaskIds.includes(task.id))
        .map((task) => ({
          value: String(task.id),
          label: task.title,
        })),
    [tasksQuery.data, selectedTaskIds]
  );
  const taskLookup = useMemo(() => {
    const map = new Map<number, string>();
    for (const task of tasksQuery.data?.items ?? []) {
      map.set(task.id, task.title);
    }
    // Also include labels from item.tasks for tasks not yet loaded
    for (const task of item.tasks) {
      if (!map.has(task.task_id) && task.title) {
        map.set(task.task_id, task.title);
      }
    }
    return map;
  }, [tasksQuery.data, item.tasks]);

  const setTags = useSetQueueItemTags(queueId);
  const setDocuments = useSetQueueItemDocuments(queueId);
  const setTasksMutation = useSetQueueItemTasks(queueId);

  const updateItem = useUpdateQueueItem(queueId, {
    onSuccess: (_data, vars) => {
      // Sync tags
      const newTagIds = selectedTags.map((tg) => tg.id);
      const currentTagIds = item.tags.map((tg) => tg.id);
      const tagsChanged =
        newTagIds.length !== currentTagIds.length ||
        newTagIds.some((id, i) => id !== currentTagIds[i]);

      if (tagsChanged) {
        setTags.mutate({ itemId: vars.itemId, tagIds: newTagIds });
      }

      // Sync documents
      const currentDocIds = item.documents.map((d) => d.document_id);
      const docsChanged =
        selectedDocIds.length !== currentDocIds.length ||
        selectedDocIds.some((id, i) => id !== currentDocIds[i]);

      if (docsChanged) {
        setDocuments.mutate({ itemId: vars.itemId, documentIds: selectedDocIds });
      }

      // Sync tasks
      const currentTaskIds = item.tasks.map((tk) => tk.task_id);
      const tasksChanged =
        selectedTaskIds.length !== currentTaskIds.length ||
        selectedTaskIds.some((id, i) => id !== currentTaskIds[i]);

      if (tasksChanged) {
        setTasksMutation.mutate({ itemId: vars.itemId, taskIds: selectedTaskIds });
      }

      toast.success(t("itemUpdated"));
      onOpenChange(false);
      onSuccess?.();
    },
  });

  const deleteItem = useDeleteQueueItem(queueId, {
    onSuccess: () => {
      toast.success(t("itemRemoved"));
      setDeleteConfirmOpen(false);
      onOpenChange(false);
      onSuccess?.();
    },
  });

  const isSaving = updateItem.isPending;
  const isDeleting = deleteItem.isPending;
  const canSubmit = !readOnly && label.trim() && !isSaving && !isDeleting;

  const handleSubmit = () => {
    const trimmedLabel = label.trim();
    if (!trimmedLabel) return;
    updateItem.mutate({
      itemId: item.id,
      data: {
        label: trimmedLabel,
        position: position ? Number(position) : undefined,
        color: color || undefined,
        notes: notes.trim() || undefined,
        is_visible: isVisible,
        user_id: userId,
      },
    });
  };

  const handleDelete = () => {
    deleteItem.mutate(item.id);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
          <DialogHeader>
            <DialogTitle>{t("editItem")}</DialogTitle>
            <DialogDescription>{item.label}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Label */}
            <div className="space-y-2">
              <Label htmlFor="edit-item-label">{t("label")}</Label>
              <Input
                id="edit-item-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t("labelPlaceholder")}
                disabled={readOnly}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canSubmit) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
              />
            </div>

            {/* Position (Initiative Roll) */}
            <div className="space-y-2">
              <Label htmlFor="edit-item-position">{t("position")}</Label>
              <Input
                id="edit-item-position"
                type="number"
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                placeholder="0"
                disabled={readOnly}
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
                disabled={readOnly}
              />
            </div>

            {/* Notes */}
            <div className="space-y-2">
              <Label htmlFor="edit-item-notes">{t("notes")}</Label>
              <Textarea
                id="edit-item-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t("notesPlaceholder")}
                rows={2}
                disabled={readOnly}
              />
            </div>

            {/* Visible toggle */}
            <div className="bg-muted/40 flex items-center justify-between rounded-lg border p-3">
              <div>
                <p className="text-sm font-medium">{t("visible")}</p>
                <p className="text-muted-foreground text-xs">
                  {isVisible ? t("visible") : t("hidden")}
                </p>
              </div>
              <Switch
                checked={isVisible}
                onCheckedChange={setIsVisible}
                aria-label={t("visible")}
                disabled={readOnly}
              />
            </div>

            {/* Tags */}
            <div className="space-y-2">
              <Label>{t("tags")}</Label>
              <TagPicker
                selectedTags={selectedTags}
                onChange={setSelectedTags}
                placeholder={t("tags")}
                disabled={readOnly}
              />
            </div>

            {/* Linked User */}
            <div className="space-y-2">
              <Label>{t("linkedUser")}</Label>
              <div className="flex items-center gap-2">
                <SearchableCombobox
                  items={memberItems}
                  value={userId !== null ? String(userId) : null}
                  onValueChange={(val) => setUserId(val ? Number(val) : null)}
                  placeholder={t("selectUser")}
                  emptyMessage={t("noUser")}
                  disabled={readOnly}
                />
                {userId !== null && !readOnly && (
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

            {/* Linked Documents */}
            <div className="space-y-2">
              <Label>{t("linkedDocuments")}</Label>
              {!readOnly && (
                <SearchableCombobox
                  items={docItems}
                  value={null}
                  onValueChange={(val) => {
                    const docId = Number(val);
                    if (docId && !selectedDocIds.includes(docId)) {
                      setSelectedDocIds((prev) => [...prev, docId]);
                    }
                  }}
                  placeholder={t("selectDocument")}
                  emptyMessage={t("noDocuments")}
                />
              )}
              {selectedDocIds.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selectedDocIds.map((docId) => (
                    <span
                      key={docId}
                      className="bg-muted inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs"
                    >
                      <Link
                        to={gp(`/documents/${docId}`)}
                        className="hover:text-primary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {docLookup.get(docId) ?? `#${docId}`}
                      </Link>
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedDocIds((prev) => prev.filter((id) => id !== docId))
                          }
                          className="text-muted-foreground hover:text-foreground"
                          aria-label={t("removeLink")}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Linked Tasks */}
            <div className="space-y-2">
              <Label>{t("linkedTasks")}</Label>
              {!readOnly && (
                <SearchableCombobox
                  items={taskItems}
                  value={null}
                  onValueChange={(val) => {
                    const taskId = Number(val);
                    if (taskId && !selectedTaskIds.includes(taskId)) {
                      setSelectedTaskIds((prev) => [...prev, taskId]);
                    }
                  }}
                  placeholder={t("selectTask")}
                  emptyMessage={t("noTasks")}
                />
              )}
              {selectedTaskIds.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selectedTaskIds.map((taskId) => (
                    <span
                      key={taskId}
                      className="bg-muted inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs"
                    >
                      <Link
                        to={gp(`/tasks/${taskId}`)}
                        className="hover:text-primary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {taskLookup.get(taskId) ?? `#${taskId}`}
                      </Link>
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedTaskIds((prev) => prev.filter((id) => id !== taskId))
                          }
                          className="text-muted-foreground hover:text-foreground"
                          aria-label={t("removeLink")}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {!readOnly && (
            <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => setDeleteConfirmOpen(true)}
                disabled={isSaving || isDeleting}
              >
                <Trash2 className="mr-1 h-4 w-4" />
                {t("removeItem")}
              </Button>
              <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
                {isSaving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t("saving")}
                  </>
                ) : (
                  t("common:save")
                )}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t("removeItem")}
        description={t("removeItemConfirm")}
        confirmLabel={t("removeItem")}
        cancelLabel={t("common:cancel")}
        onConfirm={handleDelete}
        isLoading={isDeleting}
        destructive
      />
    </>
  );
};
