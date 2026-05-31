/**
 * Fractional midpoint position for a task being inserted at ``targetIndex`` of
 * ``tasks`` (the project's tasks in global order, WITHOUT the moved task).
 *
 * The backend stores task positions as NUMERIC(20, 10) and rebalances the
 * project when a gap is exhausted, so a drag-reorder only ever sends this one
 * computed value for the moved task — never the whole list. Mirrors the counter
 * reorder helper in CounterGroupDetailPage.
 *
 * - Between two neighbors: their midpoint.
 * - At the top (only a task after it): one less than that neighbor.
 * - At the bottom (only a task before it): one more than that neighbor.
 * - Empty list: 0.
 */
export const computeMidpoint = (
  tasks: readonly { position: number }[],
  targetIndex: number
): number => {
  const before = tasks[targetIndex - 1];
  const after = tasks[targetIndex];
  if (before && after) {
    return Number(((before.position + after.position) / 2).toFixed(10));
  }
  if (before) {
    return Number((before.position + 1).toFixed(10));
  }
  if (after) {
    return Number((after.position - 1).toFixed(10));
  }
  return 0;
};

type RectLike = { top: number; height: number };

/**
 * Whether a dragged card should land AFTER the card it was released over, based
 * on their vertical centers. A flat-array index comparison can't tell which
 * side of the target the pointer released on, which made the first slot of a
 * kanban column unreachable (drops always snapped to the second slot).
 *
 * Returns false when either rect is missing (insert before — the safe default).
 */
export const shouldInsertAfter = (
  activeRect: RectLike | null | undefined,
  overRect: RectLike | null | undefined
): boolean => {
  if (!activeRect || !overRect) {
    return false;
  }
  const activeCenter = activeRect.top + activeRect.height / 2;
  const overCenter = overRect.top + overRect.height / 2;
  return activeCenter > overCenter;
};

/**
 * Reorder ``base`` (the project's tasks in global order) for a drag-and-drop
 * move of ``movedTask`` — which already carries its new ``task_status_id`` for
 * cross-column moves. The moved task is removed and re-inserted:
 *
 * - Over a specific card (``overTaskId``): before it, or after it when
 *   ``insertAfter`` is set (decided by {@link shouldInsertAfter}).
 * - On empty column body (``overTaskId === null``): appended after the last
 *   card already in ``targetStatusId``.
 *
 * Positions are a single project-wide order, so this operates on the flat list;
 * kanban columns are filtered slices of the result.
 */
export const reorderTaskList = <T extends { id: number; task_status_id: number }>(
  base: readonly T[],
  movedTask: T,
  overTaskId: number | null,
  insertAfter: boolean,
  targetStatusId: number
): T[] => {
  const next = base.filter((task) => task.id !== movedTask.id);

  if (overTaskId !== null) {
    const overIndex = next.findIndex((task) => task.id === overTaskId);
    if (overIndex !== -1) {
      next.splice(insertAfter ? overIndex + 1 : overIndex, 0, movedTask);
      return next;
    }
  }

  let lastIndex = -1;
  next.forEach((task, index) => {
    if (task.task_status_id === targetStatusId) {
      lastIndex = index;
    }
  });
  next.splice(lastIndex + 1, 0, movedTask);
  return next;
};
