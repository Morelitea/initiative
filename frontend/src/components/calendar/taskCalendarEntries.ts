import { isSameDay, parseISO } from "date-fns";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";

import type { CalendarEntry } from "./CalendarView";

/**
 * Build the calendar entries for a single task.
 *
 * - Both start & due on the *same day* with different times → ONE timed entry
 *   spanning the slot (`allDay: false`).
 * - Both on the same day at the same instant → ONE all-day entry (can't
 *   meaningfully span a time slot).
 * - Both on *different days* → TWO labeled markers (`kind: "start" | "due"`) so
 *   the user can tell them apart and drag each independently.
 * - Only one of start/due → a single marker.
 *
 * `meta.kind` (`"start" | "due" | "span"`) drives reschedule routing; the
 * top-level `kind` drives the start/due visual treatment. `draggable` gates
 * whether the entry can be dragged to reschedule (callers pass the relevant
 * permission; the backend remains authoritative).
 */
export function buildTaskCalendarEntries(
  task: TaskListRead,
  color: string,
  draggable = true
): CalendarEntry[] {
  const attendees = task.assignees
    .filter((a) => a.full_name)
    .map((a) => ({
      name: a.full_name as string,
      avatarUrl: a.avatar_url,
      avatarBase64: a.avatar_base64,
      userId: a.id,
    }));

  const base = {
    title: task.title,
    color,
    attendees,
    properties: task.properties,
    tags: task.tags,
    draggable,
  };

  const start = task.start_date ? parseISO(task.start_date) : null;
  const due = task.due_date ? parseISO(task.due_date) : null;

  const startMarker = (): CalendarEntry => ({
    ...base,
    id: `task-${task.id}-start`,
    startAt: task.start_date as string,
    endAt: task.start_date as string,
    allDay: true,
    kind: "start",
    meta: { type: "task", taskId: task.id, kind: "start" },
  });
  const dueMarker = (): CalendarEntry => ({
    ...base,
    id: `task-${task.id}-due`,
    startAt: task.due_date as string,
    endAt: task.due_date as string,
    allDay: true,
    kind: "due",
    meta: { type: "task", taskId: task.id, kind: "due" },
  });

  if (start && due) {
    const degenerate = start.getTime() === due.getTime();
    if (isSameDay(start, due) && !degenerate) {
      return [
        {
          ...base,
          id: `task-${task.id}`,
          startAt: task.start_date as string,
          endAt: task.due_date as string,
          allDay: false,
          meta: { type: "task", taskId: task.id, kind: "span" },
        },
      ];
    }
    if (isSameDay(start, due)) {
      return [
        {
          ...base,
          id: `task-${task.id}`,
          startAt: task.start_date as string,
          endAt: task.due_date as string,
          allDay: true,
          meta: { type: "task", taskId: task.id, kind: "span" },
        },
      ];
    }
    return [startMarker(), dueMarker()];
  }
  if (start) return [startMarker()];
  if (due) return [dueMarker()];
  return [];
}
