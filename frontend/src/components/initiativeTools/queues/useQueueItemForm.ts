import { useEffect, useMemo, useState } from "react";

import type { QueueItemRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  ENTITY_PICKER_PAGE_SIZE,
  type LinkedEntity,
} from "@/components/initiativeTools/queues/LinkedEntityPicker";
import { useGuildSearchSuggest } from "@/hooks/useSearch";

const DEFAULT_COLOR = "#6366F1";

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
  const [label, setLabel] = useState(item?.label ?? "");
  const [position, setPosition] = useState(item ? String(item.position) : "");
  const [color, setColor] = useState(item?.color ?? DEFAULT_COLOR);
  const [notes, setNotes] = useState(item?.notes ?? "");
  const [isVisible, setIsVisible] = useState(item?.is_visible ?? true);
  const [selectedTags, setSelectedTags] = useState<TagSummary[]>(item?.tags ?? []);
  const [userId, setUserId] = useState<number | null>(item?.user_id ?? null);
  // Selections carry their titles: the typeahead only returns rows matching
  // the live query, so a chip's label can't be looked up from the results.
  // An edited item's own links already ship theirs.
  const [selectedDocs, setSelectedDocs] = useState<LinkedEntity[]>(() =>
    item ? item.documents.map((d) => ({ id: d.document_id, title: d.name })) : []
  );
  const [selectedTasks, setSelectedTasks] = useState<LinkedEntity[]>(() =>
    item ? item.tasks.map((tk) => ({ id: tk.task_id, title: tk.title })) : []
  );

  const [docSearch, setDocSearch] = useState("");
  const [docPickerOpen, setDocPickerOpen] = useState(false);
  const [taskSearch, setTaskSearch] = useState("");
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);

  // Edit mode: re-sync from the item on (re)open. Add mode: reset to defaults on
  // close. In add mode `item` is always undefined, so the effect fires only on
  // `open` changes — matching each dialog's original behavior.
  useEffect(() => {
    if (item) {
      if (open) {
        setLabel(item.label);
        setPosition(String(item.position));
        setColor(item.color ?? DEFAULT_COLOR);
        setNotes(item.notes ?? "");
        setIsVisible(item.is_visible);
        setSelectedTags(item.tags);
        setUserId(item.user_id);
        setSelectedDocs(item.documents.map((d) => ({ id: d.document_id, title: d.name })));
        setSelectedTasks(item.tasks.map((tk) => ({ id: tk.task_id, title: tk.title })));
      }
    } else if (!open) {
      setLabel("");
      setPosition("");
      setColor(DEFAULT_COLOR);
      setNotes("");
      setIsVisible(true);
      setSelectedTags([]);
      setUserId(null);
      setSelectedDocs([]);
      setSelectedTasks([]);
    }
  }, [open, item]);

  // The user picker is a server typeahead over the initiative's members
  // (`MemberSelect`), so the form no longer pulls the full roster. An edited
  // item ships its own linked user, which saves the picker a lookup.
  const selectedUser = item?.user ?? null;

  // Both pickers ask the one lookup the whole app searches through, narrowed
  // to this initiative and to live work — a queue item links to something
  // being done, not to a blueprint or something already put away.
  const docsQuery = useGuildSearchSuggest(docSearch, {
    types: [SearchEntityType.document],
    initiative_id: initiativeId,
    template: false,
    limit: ENTITY_PICKER_PAGE_SIZE,
    enabled: open && docPickerOpen,
  });
  const docResults = useMemo(
    () => (docsQuery.data ?? []).map((doc) => ({ id: doc.entity_id, title: doc.title })),
    [docsQuery.data]
  );

  const tasksQuery = useGuildSearchSuggest(taskSearch, {
    types: [SearchEntityType.task],
    initiative_id: initiativeId,
    limit: ENTITY_PICKER_PAGE_SIZE,
    enabled: open && taskPickerOpen,
  });
  const taskResults = useMemo(
    () => (tasksQuery.data ?? []).map((task) => ({ id: task.entity_id, title: task.title })),
    [tasksQuery.data]
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
    docsLoading: docsQuery.isFetching,
    taskResults,
    tasksLoading: tasksQuery.isFetching,
  };
};
