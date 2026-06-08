import { describe, expect, it } from "vitest";

import { buildTag } from "@/__tests__/factories";
import { buildTask, buildTaskAssignee } from "@/__tests__/factories/task.factory";

import { buildTaskCalendarEntries } from "./taskCalendarEntries";

// Local-time ISO strings (no trailing "Z") so parseISO / isSameDay don't shift
// the day across timezones in CI.
const COLOR = "#3b82f6";

describe("buildTaskCalendarEntries", () => {
  it("renders one timed span for same-day start & due with real times", () => {
    const task = buildTask({
      id: 7,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-01-15T17:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(1);
    const [entry] = entries;
    expect(entry.id).toBe("task-7");
    expect(entry.allDay).toBe(false);
    expect(entry.startAt).toBe("2026-01-15T09:00:00");
    expect(entry.endAt).toBe("2026-01-15T17:00:00");
    expect(entry.kind).toBeUndefined();
    expect(entry.meta).toMatchObject({ type: "task", taskId: 7, kind: "span" });
  });

  it("renders one all-day entry when same-day start & due are both midnight", () => {
    const task = buildTask({
      id: 8,
      start_date: "2026-01-15T00:00:00",
      due_date: "2026-01-15T00:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(1);
    expect(entries[0].allDay).toBe(true);
    expect(entries[0].meta).toMatchObject({ kind: "span" });
  });

  it("renders two labeled markers when start & due fall on different days", () => {
    const task = buildTask({
      id: 9,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-01-18T17:00:00",
    });

    const entries = buildTaskCalendarEntries(task, COLOR);

    expect(entries).toHaveLength(2);
    const start = entries.find((e) => e.kind === "start");
    const due = entries.find((e) => e.kind === "due");
    expect(start?.id).toBe("task-9-start");
    expect(start?.allDay).toBe(true);
    expect(start?.startAt).toBe("2026-01-15T09:00:00");
    expect(start?.meta).toMatchObject({ type: "task", taskId: 9, kind: "start" });
    expect(due?.id).toBe("task-9-due");
    expect(due?.startAt).toBe("2026-01-18T17:00:00");
    expect(due?.meta).toMatchObject({ type: "task", taskId: 9, kind: "due" });
  });

  it("renders a single start marker when only start_date is set", () => {
    const task = buildTask({ id: 10, start_date: "2026-01-15T09:00:00", due_date: undefined });
    const entries = buildTaskCalendarEntries(task, COLOR);
    expect(entries).toHaveLength(1);
    expect(entries[0].kind).toBe("start");
    expect(entries[0].meta).toMatchObject({ kind: "start" });
  });

  it("renders a single due marker when only due_date is set", () => {
    const task = buildTask({ id: 11, start_date: undefined, due_date: "2026-01-15T17:00:00" });
    const entries = buildTaskCalendarEntries(task, COLOR);
    expect(entries).toHaveLength(1);
    expect(entries[0].kind).toBe("due");
    expect(entries[0].meta).toMatchObject({ kind: "due" });
  });

  it("renders nothing when the task has no dates", () => {
    const task = buildTask({ id: 12, start_date: undefined, due_date: undefined });
    expect(buildTaskCalendarEntries(task, COLOR)).toHaveLength(0);
  });

  it("propagates the draggable flag onto entries (defaults to true)", () => {
    const task = buildTask({
      id: 14,
      start_date: "2026-01-15T09:00:00",
      due_date: "2026-01-18T17:00:00",
    });
    expect(buildTaskCalendarEntries(task, COLOR).every((e) => e.draggable === true)).toBe(true);
    expect(buildTaskCalendarEntries(task, COLOR, false).every((e) => e.draggable === false)).toBe(
      true
    );
  });

  it("propagates color, tags, and assignees onto entries", () => {
    const tag = buildTag({ name: "urgent" });
    const task = buildTask({
      id: 13,
      start_date: "2026-01-15T09:00:00",
      tags: [tag],
      assignees: [buildTaskAssignee({ id: 42, full_name: "Alice" })],
    });

    const [entry] = buildTaskCalendarEntries(task, COLOR);

    expect(entry.color).toBe(COLOR);
    expect(entry.tags).toEqual([tag]);
    expect(entry.attendees).toEqual([
      { name: "Alice", avatarUrl: null, avatarBase64: null, userId: 42 },
    ]);
  });
});
