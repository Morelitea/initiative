import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Loader2, Sparkles, SquareCheck, Trash2 } from "lucide-react";
import {
  type ClipboardEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type { ChecklistItem, ChecklistProgress } from "@/api/generated/initiativeAPI.schemas";
import { TaskChecklistProgress } from "@/components/tasks/TaskChecklistProgress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useGenerateChecklist, useToggleChecklistItem, useUpdateTask } from "@/hooks/useTasks";
import { newChecklistItemId } from "@/lib/checklist";
import { toast } from "@/lib/chesterToast";

/** A checklist as the server holds it, in one comparable string. */
const fingerprint = (items: ChecklistItem[]) =>
  JSON.stringify(items.map((item) => [item.id, item.text, item.done]));

/** The list as it would be saved: a line still being written is not one yet. */
const payloadOf = (items: ChecklistItem[]) =>
  items
    .filter((item) => item.text.trim())
    .map((item) => ({ id: item.id, text: item.text.trim(), done: item.done }));

const blankItem = (): ChecklistItem => ({ id: newChecklistItemId(), text: "", done: false });

type TaskChecklistProps = {
  taskId: number;
  /** ``task.checklist`` — the whole list, in order. */
  items: ChecklistItem[];
  canEdit: boolean;
};

export const TaskChecklist = ({ taskId, items: serverItems, canEdit }: TaskChecklistProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const addInputRef = useRef<HTMLInputElement | null>(null);
  const [newText, setNewText] = useState("");
  const { isEnabled: aiEnabled } = useAIEnabled();
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const [items, setItems] = useState<ChecklistItem[]>(serverItems);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  // What the server was last told. An edit that has not reached it yet is what
  // keeps an incoming refetch from overwriting what somebody is typing.
  const sent = useRef(fingerprint(serverItems));
  // The item to put the cursor in once it has rendered.
  const [focusId, setFocusId] = useState<string | null>(null);

  const updateTask = useUpdateTask(undefined, "tasks:checklist.updateError");
  const toggleItem = useToggleChecklistItem();

  useEffect(() => {
    const local = itemsRef.current;
    const unsent =
      fingerprint(payloadOf(local)) !== sent.current || local.some((item) => !item.text.trim());
    if (unsent) {
      return;
    }
    setItems(serverItems);
    sent.current = fingerprint(serverItems);
  }, [serverItems]);

  const progress: ChecklistProgress | null = useMemo(() => {
    const saved = payloadOf(items);
    return saved.length
      ? { completed: saved.filter((item) => item.done).length, total: saved.length }
      : null;
  }, [items]);

  /** Apply a local edit and send the whole list, unless it already says what
   *  the server holds. */
  const save = useCallback(
    (next: ChecklistItem[]) => {
      setItems(next);
      const payload = payloadOf(next);
      const stamp = fingerprint(payload);
      if (stamp === sent.current) {
        return;
      }
      sent.current = stamp;
      updateTask.mutate({ taskId, data: { checklist: payload } });
    },
    [taskId, updateTask]
  );

  const generateChecklist = useGenerateChecklist({
    onSuccess: (data) => {
      setSuggestions(data.items);
      setSelected(new Set(data.items.map((_, index) => index)));
      setAiDialogOpen(true);
    },
  });

  const handleAddSuggestions = () => {
    const chosen = suggestions.filter((_, index) => selected.has(index));
    setAiDialogOpen(false);
    setSuggestions([]);
    setSelected(new Set());
    if (chosen.length === 0) {
      return;
    }
    save([...items, ...chosen.map((text) => ({ id: newChecklistItemId(), text, done: false }))]);
    toast.success(t("checklist.batchAdded", { count: chosen.length }));
  };

  const toggleSuggestion = (index: number) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const handleAdd = () => {
    const trimmed = newText.trim();
    if (!canEdit || !trimmed) {
      return;
    }
    setNewText("");
    save([...items, { id: newChecklistItemId(), text: trimmed, done: false }]);
    addInputRef.current?.focus();
  };

  /** Pasting a block of lines makes one item per line. */
  const handleAddPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const lines = event.clipboardData
      .getData("text")
      .split("\n")
      .map((line) => line.replace(/^\s*[-*•]\s*/, "").trim())
      .filter(Boolean);
    if (!canEdit || lines.length < 2) {
      return;
    }
    event.preventDefault();
    setNewText("");
    save([...items, ...lines.map((text) => ({ id: newChecklistItemId(), text, done: false }))]);
  };

  const handleToggle = (item: ChecklistItem, done: boolean) => {
    if (!canEdit) {
      return;
    }
    setItems((previous) =>
      previous.map((entry) => (entry.id === item.id ? { ...entry, done } : entry))
    );
    // A tick names one item, so it neither carries nor overwrites the rest of
    // the list. What comes back is the list as it now stands.
    toggleItem.mutate(
      { taskId, itemId: item.id, done },
      {
        onSuccess: (updated) => {
          setItems(updated);
          sent.current = fingerprint(updated);
        },
      }
    );
  };

  const handleTextChange = (id: string, text: string) => {
    setItems((previous) => previous.map((entry) => (entry.id === id ? { ...entry, text } : entry)));
  };

  const handleTextBlur = (id: string) => {
    const current = itemsRef.current;
    const item = current.find((entry) => entry.id === id);
    if (!item) {
      return;
    }
    // An item left empty was never a line; drop it rather than saving nothing.
    save(item.text.trim() ? current : current.filter((entry) => entry.id !== id));
  };

  const handleItemKeyDown = (event: KeyboardEvent<HTMLInputElement>, index: number) => {
    const current = itemsRef.current;
    if (event.key === "Enter") {
      event.preventDefault();
      if (!current[index].text.trim()) {
        return;
      }
      const fresh = blankItem();
      setItems([...current.slice(0, index + 1), fresh, ...current.slice(index + 1)]);
      setFocusId(fresh.id);
      return;
    }
    if (event.key === "Backspace" && !current[index].text && current.length > 1) {
      event.preventDefault();
      setFocusId(current[Math.max(0, index - 1)].id);
      save(current.filter((_, position) => position !== index));
    }
  };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      if (!canEdit) {
        return;
      }
      const { active, over } = event;
      if (!over || active.id === over.id) {
        return;
      }
      const current = itemsRef.current;
      const from = current.findIndex((item) => item.id === active.id);
      const to = current.findIndex((item) => item.id === over.id);
      if (from === -1 || to === -1) {
        return;
      }
      save(arrayMove(current, from, to));
    },
    [canEdit, save]
  );

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <SquareCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            {t("checklist.title")}
          </CardTitle>
          {canEdit && aiEnabled ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => generateChecklist.mutate(taskId)}
              disabled={generateChecklist.isPending}
            >
              {generateChecklist.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              {t("checklist.aiGenerate")}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t("checklist.empty")} {canEdit ? t("checklist.emptyCanEdit") : ""}
          </p>
        ) : (
          <div className="space-y-3">
            <TaskChecklistProgress progress={progress} />
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={items.map((item) => item.id)}
                strategy={verticalListSortingStrategy}
              >
                <ul className="space-y-2">
                  {items.map((item, index) => (
                    <ChecklistItemRow
                      key={item.id}
                      item={item}
                      canEdit={canEdit}
                      shouldFocus={focusId === item.id}
                      onFocused={() => setFocusId(null)}
                      onTextChange={(value) => handleTextChange(item.id, value)}
                      onTextBlur={() => handleTextBlur(item.id)}
                      onKeyDown={(event) => handleItemKeyDown(event, index)}
                      onToggle={(value) => handleToggle(item, value)}
                      onDelete={() =>
                        save(itemsRef.current.filter((entry) => entry.id !== item.id))
                      }
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          </div>
        )}

        <div className="flex gap-2">
          <Input
            ref={addInputRef}
            placeholder={
              canEdit ? t("checklist.addPlaceholder") : t("checklist.readOnlyPlaceholder")
            }
            value={newText}
            onChange={(event) => setNewText(event.target.value)}
            onPaste={handleAddPaste}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleAdd();
              }
            }}
            disabled={!canEdit}
          />
          <Button type="button" onClick={handleAdd} disabled={!canEdit}>
            {t("checklist.addButton")}
          </Button>
        </div>
        {!canEdit ? (
          <p className="text-muted-foreground text-xs">{t("checklist.readOnlyMessage")}</p>
        ) : null}
      </CardContent>

      <Dialog open={aiDialogOpen} onOpenChange={setAiDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("checklist.aiDialogTitle")}</DialogTitle>
            <DialogDescription>{t("checklist.aiDialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-4">
            {suggestions.map((suggestion, index) => (
              <div key={suggestion} className="flex items-center gap-3 rounded-md border p-3">
                <Checkbox
                  id={`checklist-suggestion-${index}`}
                  checked={selected.has(index)}
                  onCheckedChange={() => toggleSuggestion(index)}
                />
                <label
                  htmlFor={`checklist-suggestion-${index}`}
                  className="flex-1 cursor-pointer text-sm"
                >
                  {suggestion}
                </label>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAiDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button onClick={handleAddSuggestions} disabled={selected.size === 0}>
              {t("checklist.addSelected", { count: selected.size })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
};

type ChecklistItemRowProps = {
  item: ChecklistItem;
  canEdit: boolean;
  shouldFocus: boolean;
  onFocused: () => void;
  onTextChange: (value: string) => void;
  onTextBlur: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
  onToggle: (done: boolean) => void;
  onDelete: () => void;
};

const ChecklistItemRow = ({
  item,
  canEdit,
  shouldFocus,
  onFocused,
  onTextChange,
  onTextBlur,
  onKeyDown,
  onToggle,
  onDelete,
}: ChecklistItemRowProps) => {
  const { t } = useTranslation("tasks");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id,
    disabled: !canEdit,
  });

  useEffect(() => {
    if (shouldFocus) {
      inputRef.current?.focus();
      onFocused();
    }
  }, [shouldFocus, onFocused]);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`flex flex-col gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm md:flex-row md:items-center md:gap-3 ${
        isDragging ? "opacity-80 shadow-sm" : ""
      }`}
    >
      <div className="flex flex-1 items-center gap-2">
        {canEdit ? (
          <button
            type="button"
            className="mt-1 text-muted-foreground"
            aria-label={t("checklist.reorderItem")}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="-mt-1 h-4 w-4" />
          </button>
        ) : null}
        <Checkbox
          checked={item.done}
          onCheckedChange={(value) => onToggle(Boolean(value))}
          disabled={!canEdit}
          aria-label={item.done ? t("checklist.markIncomplete") : t("checklist.markComplete")}
        />
        <Input
          ref={inputRef}
          value={item.text}
          placeholder={t("checklist.itemPlaceholder")}
          onChange={(event) => onTextChange(event.target.value)}
          onBlur={onTextBlur}
          onKeyDown={onKeyDown}
          disabled={!canEdit}
          className={item.done ? "line-through" : undefined}
        />
      </div>
      {canEdit ? (
        <div className="flex items-center gap-1 self-end md:self-auto">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive"
            aria-label={t("checklist.deleteItem")}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ) : null}
    </li>
  );
};
