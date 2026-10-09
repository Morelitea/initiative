/**
 * Which of a card's fields a reader has turned off (`taskFields` lists them).
 *
 * The table calls these "columns" because they are columns. On a board there
 * is no column to hide — the columns are the statuses — so the same idea is
 * called **fields**.
 *
 * Keyed by field id — the same shape TanStack uses for column visibility, so
 * `usePersistedColumnVisibility` stores it as-is.
 *
 * **Absent means shown.** A card that has never been configured shows
 * everything it has, which is what it did before this menu existed, and a
 * field added in a later release appears without anybody re-enabling it.
 */
export type KanbanFieldVisibility = Record<string, boolean>;

/** Whether a field should be rendered. Anything not explicitly off is on. */
export const isKanbanFieldVisible = (visibility: KanbanFieldVisibility, field: string): boolean =>
  visibility[field] !== false;

/** Where a project's choices live. Per project, because the fields that earn
 *  their place on a card differ from one board to the next. */
export const kanbanFieldsStorageKey = (projectId: number): string =>
  `initiative-project-${projectId}-kanban-fields`;
