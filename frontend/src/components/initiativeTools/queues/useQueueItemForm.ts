import { useEffect, useMemo, useState } from "react";

import {
  type QueueItemRead,
  type RelationshipRead,
  RelationshipType,
  SearchEntityType,
  type TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { useRelationshipsFor } from "@/hooks/useRelationships";
import { useServerForm } from "@/hooks/useServerForm";
import type { LinkedRef } from "@/lib/relationships";

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
}): string =>
  JSON.stringify([
    value.label,
    value.position,
    value.color,
    value.notes,
    value.isVisible,
    value.userId,
    value.selectedTags.map((tag) => tag.id),
  ]);

/**
 * What an item is linked to right now, as one list of mixed kinds.
 *
 * Read from the graph rather than from the item, because the item serialises a
 * `documents` array and a `tasks` array and nothing else — the two kinds that
 * used to have junction tables of their own. An item may be pinned to any of the
 * fourteen, and reading it from the two lists made everything else disappear the
 * moment the dialog was reopened.
 */
const attachmentsOf = (rows: RelationshipRead[]): LinkedRef[] =>
  rows
    .filter((row) => row.relationship_type === RelationshipType.attached)
    .map((row) => ({
      type: row.other.type,
      id: row.other.id,
      title: row.other.title,
      toolTitle: row.other.tool_title,
    }));

interface UseQueueItemFormArgs {
  /** Whether the owning dialog is open (gates the picker typeaheads + reset). */
  open: boolean;
  /** Initiative the queue belongs to — scopes the member and link pickers. */
  initiativeId: number;
  /**
   * When provided, the form edits an existing item: fields initialize from it
   * and re-sync whenever the dialog reopens. When omitted, the form is in
   * "add" mode: fields start empty and reset to defaults on close.
   */
  item?: QueueItemRead;
}

/**
 * Shared field state for the add/edit queue-item dialogs, which duplicated ~90%
 * of their form wiring. The submit payload and any edit-only concerns (delete,
 * change detection) stay in each dialog.
 *
 * What an item is linked to is one list of mixed kinds rather than a list of
 * documents and a list of tasks, and the picker that searches for them owns its
 * own typeahead — so the two narrowed lookups that used to live here are gone.
 */
export const useQueueItemForm = ({ open, initiativeId, item }: UseQueueItemFormArgs) => {
  // Asked for only while the dialog is open, and only for an item that exists:
  // the add dialog is composing one and has nothing to ask about yet.
  const linkQuery = useRelationshipsFor(
    { type: SearchEntityType.queue_item, id: item?.id ?? 0 },
    { enabled: open && Boolean(item?.id) }
  );
  const loadedLinks = useMemo(() => attachmentsOf(linkQuery.data ?? []), [linkQuery.data]);

  /**
   * Held apart from the rest of the form on purpose.
   *
   * `useServerForm` stops following the server the moment anything is typed —
   * which is what you want for a field somebody is filling in, and exactly wrong
   * for a list that has not arrived yet. Typing a label before the links landed
   * would have left this empty for good, and saving then compares an empty list
   * against the loaded one and takes every link off.
   *
   * So the links follow their own answer until somebody actually touches them.
   */
  const [editedLinks, setEditedLinks] = useState<LinkedRef[] | null>(null);
  // A new sitting starts from what the server says, the same way every other
  // field here does when the dialog reopens. Keyed on the sitting rather than on
  // the links: re-reading those must not throw away an edit in progress.
  useEffect(() => {
    setEditedLinks(null);
  }, [open, item?.id]);
  const links = editedLinks ?? loadedLinks;

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
    }),
    [open, item?.id],
    (a, b) => serializeItem(a) === serializeItem(b)
  );
  const { label, position, color, notes, isVisible, selectedTags, userId } = form.values;
  const setLabel = (next: string) => form.set({ label: next });
  const setPosition = (next: string) => form.set({ position: next });
  const setColor = (next: string) => form.set({ color: next });
  const setNotes = (next: string) => form.set({ notes: next });
  const setIsVisible = (next: boolean) => form.set({ isVisible: next });
  const setSelectedTags = (next: TagSummary[]) => form.set({ selectedTags: next });
  const setUserId = (next: number | null) => form.set({ userId: next });

  // The user picker is a server typeahead over the initiative's members
  // (`MemberSelect`), so the form no longer pulls the full roster. An edited
  // item ships its own linked user, which saves the picker a lookup.
  const selectedUser = item?.user ?? null;

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
    links,
    setLinks: setEditedLinks,
    /** The saved set, so a submit can work out what actually moved. */
    initialLinks: loadedLinks,
    linksLoading: linkQuery.isLoading,
    selectedUser,
  };
};
