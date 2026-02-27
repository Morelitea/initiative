import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useCreateQueueItem } from "@/hooks/useQueues";
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
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
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
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([]);
  const [selectedTaskIds, setSelectedTaskIds] = useState<number[]>([]);

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
      setSelectedDocIds([]);
      setSelectedTaskIds([]);
    }
  }, [open]);

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
    return map;
  }, [docsQuery.data]);

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
    return map;
  }, [tasksQuery.data]);

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
      document_ids: selectedDocIds.length > 0 ? selectedDocIds : undefined,
      task_ids: selectedTaskIds.length > 0 ? selectedTaskIds : undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card max-h-screen w-full max-w-lg overflow-y-auto rounded-2xl border shadow-2xl">
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
          <div className="bg-muted/40 flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">{t("visible")}</p>
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

          {/* Linked Documents */}
          <div className="space-y-2">
            <Label>{t("linkedDocuments")}</Label>
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
                    <button
                      type="button"
                      onClick={() => setSelectedDocIds((prev) => prev.filter((id) => id !== docId))}
                      className="text-muted-foreground hover:text-foreground"
                      aria-label={t("removeLink")}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Linked Tasks */}
          <div className="space-y-2">
            <Label>{t("linkedTasks")}</Label>
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
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {isAdding ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
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
