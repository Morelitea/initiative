import { useMemo, useState } from "react";

import type { QueueItemRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  ENTITY_PICKER_PAGE_SIZE,
  type LinkedEntity,
} from "@/components/initiativeTools/queues/LinkedEntityPicker";
import { useGuildPickerSuggestions } from "@/hooks/useSearch";
import { useServerForm } from "@/hooks/useServerForm";

const DEFAULT_COLOR = "#6366F1";

/** The linked rows are rebuilt on every read, so they are compared by id. */
const serializeItem = (value: {
  label: string;
  position: string;
  color: string;
  notes: string;
  isVisible: boolean;
  selectedTags: { id: number }[];
  userId: number | null;
  selectedDocs: LinkedEntity[];
  selectedTasks: LinkedEntity[];
}): string =>
  JSON.stringify([
    value.label,
    value.position,
    value.color,
    value.notes,
    value.isVisible,
    value.userId,
    value.selectedTags.map((tag) => tag.id),
    value.selectedDocs.map((doc) => doc.id),
    value.selectedTasks.map((task) => task.id),
  ]);

interface UseQueueItemFormArgs {
  /** Whether the owning dialog is open (gates the picker typeaheads + reset). */
  open: boolean;
  /** Initiative the queue belongs to — scopes the member/doc/task pickers. */
  initiativeId: number;
  /**
   * When provided, the form edits an existing item: fields initialize from it
   * and re-sync whenever the dialog reopens. When omitted, the form is in
   * "add" mode: fields start empty and reset to defaults on close.
   */
  item?: QueueItemRead;
}

/**
 * Shared field state and picker option lists for the add/edit queue-item
 * dialogs, which duplicated ~90% of their form wiring. The submit payload and
 * any edit-only concerns (delete, change detection) stay in each dialog.
 *
 * The document and task pickers are server typeaheads (issue #857): they fetch
 * only while the dialog is open and the picker is expanded, and never fetch the
 * full list.
 */
export const useQueueItemForm = ({ open, initiativeId, item }: UseQueueItemFormArgs) => {
  // Selections carry their titles: the typeahead only returns rows matching
  // the live query, so a chip's label can't be looked up from the results.
  // An edited item's own links already ship theirs.
  const form = useServerForm(
    item,
    (loaded) => ({
      label: loaded?.label ?? "",
      position: loaded ? String(loaded.position) : "",
      color: loaded?.color ?? DEFAULT_COLOR,
      notes: loaded?.notes ?? "",
      isVisible: loaded?.is_visible ?? true,
      selectedTags: loaded?.tags ?? ([] as TagSummary[]),
      userId: loaded?.user_id ?? null,
      selectedDocs: (loaded?.documents.map((d) => ({ id: d.document_id, title: d.name })) ??
        []) as LinkedEntity[],
      selectedTasks: (loaded?.tasks.map((tk) => ({ id: tk.task_id, title: tk.title })) ??
        []) as LinkedEntity[],
    }),
    [open, item?.id],
    (a, b) => serializeItem(a) === serializeItem(b)
  );
  const { label, position, color, notes, isVisible, selectedTags, userId } = form.values;
  const { selectedDocs, selectedTasks } = form.values;
  const setLabel = (next: string) => form.set({ label: next });
  const setPosition = (next: string) => form.set({ position: next });
  const setColor = (next: string) => form.set({ color: next });
  const setNotes = (next: string) => form.set({ notes: next });
  const setIsVisible = (next: boolean) => form.set({ isVisible: next });
  const setSelectedTags = (next: TagSummary[]) => form.set({ selectedTags: next });
  const setUserId = (next: number | null) => form.set({ userId: next });
  const setSelectedDocs = (next: LinkedEntity[]) => form.set({ selectedDocs: next });
  const setSelectedTasks = (next: LinkedEntity[]) => form.set({ selectedTasks: next });

  const [docSearch, setDocSearch] = useState("");
  const [docPickerOpen, setDocPickerOpen] = useState(false);
  const [taskSearch, setTaskSearch] = useState("");
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);

  // The user picker is a server typeahead over the initiative's members
  // (`MemberSelect`), so the form no longer pulls the full roster. An edited
  // item ships its own linked user, which saves the picker a lookup.
  const selectedUser = item?.user ?? null;

  // Both pickers ask the one lookup the whole app searches through, narrowed
  // to this initiative and to live work — a queue item links to something
  // being done, not to a blueprint or something already put away. Each opens on
  // what was most recently worked on, so neither starts as an empty box.
  const docsPicker = useGuildPickerSuggestions(docSearch, {
    types: [SearchEntityType.document],
    initiative_id: initiativeId,
    template: false,
    limit: ENTITY_PICKER_PAGE_SIZE,
    enabled: open && docPickerOpen,
  });
  const docResults = useMemo(
    () => docsPicker.items.map((doc) => ({ id: doc.entity_id, title: doc.title })),
    [docsPicker.items]
  );

  const tasksPicker = useGuildPickerSuggestions(taskSearch, {
    types: [SearchEntityType.task],
    initiative_id: initiativeId,
    limit: ENTITY_PICKER_PAGE_SIZE,
    enabled: open && taskPickerOpen,
  });
  const taskResults = useMemo(
    () => tasksPicker.items.map((task) => ({ id: task.entity_id, title: task.title })),
    [tasksPicker.items]
  );

  return {
    // Field state
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
    // Picker search/open setters
    setDocSearch,
    setDocPickerOpen,
    setTaskSearch,
    setTaskPickerOpen,
    // Picker option lists
    selectedUser,
    docResults,
    docsLoading: docsPicker.isFetching,
    taskResults,
    tasksLoading: tasksPicker.isFetching,
  };
};
