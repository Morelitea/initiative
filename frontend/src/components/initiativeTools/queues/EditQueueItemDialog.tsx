import { Loader2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { QueueItemRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import {
  ENTITY_PICKER_PAGE_SIZE,
  type LinkedEntity,
  LinkedEntityPicker,
} from "@/components/initiativeTools/queues/LinkedEntityPicker";
import { TagPicker } from "@/components/tags/TagPicker";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useDocumentAutocomplete } from "@/hooks/useDocuments";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import {
  useDeleteQueueItem,
  useSetQueueItemDocuments,
  useSetQueueItemTags,
  useSetQueueItemTasks,
  useUpdateQueueItem,
} from "@/hooks/useQueues";
import { useTasks } from "@/hooks/useTasks";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { getUserDisplayName } from "@/lib/userDisplay";
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
  // Selections carry their titles: the typeahead only returns rows matching
  // the live query, so a chip's label can't be looked up from the results.
  // The item's own links already ship theirs.
  const [selectedDocs, setSelectedDocs] = useState<LinkedEntity[]>(() =>
    item.documents.map((d) => ({ id: d.document_id, title: d.title }))
  );
  const [selectedTasks, setSelectedTasks] = useState<LinkedEntity[]>(() =>
    item.tasks.map((t) => ({ id: t.task_id, title: t.title }))
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const [docSearch, setDocSearch] = useState("");
  const [docPickerOpen, setDocPickerOpen] = useState(false);
  const [taskSearch, setTaskSearch] = useState("");
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);

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
      setSelectedDocs(item.documents.map((d) => ({ id: d.document_id, title: d.title })));
      setSelectedTasks(item.tasks.map((tk) => ({ id: tk.task_id, title: tk.title })));
    }
  }, [open, item]);

  // Fetch initiative members for user picker
  const membersQuery = useInitiativeMembers(initiativeId);
  const memberItems = useMemo(
    () =>
      (membersQuery.data ?? []).map((member) => ({
        value: String(member.id),
        label: getUserDisplayName(member),
      })),
    [membersQuery.data]
  );

  // Document picker — server typeahead, only while the picker is open.
  const docsQuery = useDocumentAutocomplete(initiativeId, docSearch, {
    enabled: open && docPickerOpen,
    limit: ENTITY_PICKER_PAGE_SIZE,
  });
  const docResults = useMemo(
    () => (docsQuery.data ?? []).map((doc) => ({ id: doc.id, title: doc.title })),
    [docsQuery.data]
  );

  // Task picker — server typeahead over titles within this initiative.
  const tasksQuery = useTasks(
    {
      conditions: [
        { field: "initiative_ids", op: "in_", value: [initiativeId] },
        ...(taskSearch ? [{ field: "title", op: "ilike" as const, value: taskSearch }] : []),
      ],
      page_size: ENTITY_PICKER_PAGE_SIZE,
    },
    { enabled: open && taskPickerOpen }
  );
  const taskResults = useMemo(
    () => (tasksQuery.data?.items ?? []).map((task) => ({ id: task.id, title: task.title })),
    [tasksQuery.data]
  );

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
      const selectedDocIds = selectedDocs.map((doc) => doc.id);
      const currentDocIds = item.documents.map((d) => d.document_id);
      const docsChanged =
        selectedDocIds.length !== currentDocIds.length ||
        selectedDocIds.some((id, i) => id !== currentDocIds[i]);

      if (docsChanged) {
        setDocuments.mutate({ itemId: vars.itemId, documentIds: selectedDocIds });
      }

      // Sync tasks
      const selectedTaskIds = selectedTasks.map((task) => task.id);
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
        <DialogContent className="max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border bg-card shadow-2xl">
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
            <div className="flex items-center justify-between rounded-lg border bg-muted/40 p-3">
              <div>
                <p className="font-medium text-sm">{t("visible")}</p>
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

            <LinkedEntityPicker
              label={t("linkedDocuments")}
              selected={selectedDocs}
              onChange={setSelectedDocs}
              results={docResults}
              loading={docsQuery.isFetching}
              onSearchChange={setDocSearch}
              onOpenChange={setDocPickerOpen}
              hrefFor={(id) => gp(`/documents/${id}`)}
              placeholder={t("selectDocument")}
              emptyMessage={t("noDocuments")}
              readOnly={readOnly}
            />

            <LinkedEntityPicker
              label={t("linkedTasks")}
              selected={selectedTasks}
              onChange={setSelectedTasks}
              results={taskResults}
              loading={tasksQuery.isFetching}
              onSearchChange={setTaskSearch}
              onOpenChange={setTaskPickerOpen}
              hrefFor={(id) => gp(`/tasks/${id}`)}
              placeholder={t("selectTask")}
              emptyMessage={t("noTasks")}
              readOnly={readOnly}
            />
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
