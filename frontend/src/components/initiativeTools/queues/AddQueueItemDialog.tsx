import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import {
  ENTITY_PICKER_PAGE_SIZE,
  type LinkedEntity,
  LinkedEntityPicker,
} from "@/components/initiativeTools/queues/LinkedEntityPicker";
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
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useDocumentAutocomplete } from "@/hooks/useDocuments";
import { useInitiativeMembers } from "@/hooks/useInitiatives";
import { useCreateQueueItem } from "@/hooks/useQueues";
import { useTasks } from "@/hooks/useTasks";
import { toast } from "@/lib/chesterToast";
import { useGuildPath } from "@/lib/guildUrl";
import { getUserDisplayName } from "@/lib/userDisplay";
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

  const [label, setLabel] = useState("");
  const [position, setPosition] = useState("");
  const [color, setColor] = useState("#6366F1");
  const [notes, setNotes] = useState("");
  const [isVisible, setIsVisible] = useState(true);
  const [selectedTags, setSelectedTags] = useState<TagSummary[]>([]);
  const [userId, setUserId] = useState<number | null>(null);
  // Selections carry their titles: the typeahead only returns rows matching
  // the live query, so a chip's label can't be looked up from the results.
  const [selectedDocs, setSelectedDocs] = useState<LinkedEntity[]>([]);
  const [selectedTasks, setSelectedTasks] = useState<LinkedEntity[]>([]);

  const [docSearch, setDocSearch] = useState("");
  const [docPickerOpen, setDocPickerOpen] = useState(false);
  const [taskSearch, setTaskSearch] = useState("");
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);

  // Reset form when dialog closes
  useEffect(() => {
    if (!open) {
      setLabel("");
      setPosition("");
      setColor("#6366F1");
      setNotes("");
      setIsVisible(true);
      setSelectedTags([]);
      setUserId(null);
      setSelectedDocs([]);
      setSelectedTasks([]);
    }
  }, [open]);

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
              <SearchableCombobox
                items={memberItems}
                value={userId !== null ? String(userId) : null}
                onValueChange={(val) => setUserId(val ? Number(val) : null)}
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
            loading={docsQuery.isFetching}
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
            loading={tasksQuery.isFetching}
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
