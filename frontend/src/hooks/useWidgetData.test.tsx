/**
 * How a binding becomes a request.
 *
 * The load-bearing case is scope. A dashboard reads the initiative it lives on,
 * and the tasks endpoint narrows on exactly one thing — the filter DSL. Scope
 * expressed any other way is accepted by the type checker and ignored by the
 * server, and the difference is invisible on a canvas (a chart with
 * plausible-looking numbers), so it is pinned here on the request itself rather
 * than on what gets drawn.
 */
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWidgetData, type WidgetBinding } from "@/hooks/useWidgetData";

const idle = { data: undefined, isLoading: false };
const useTasks = vi.fn(() => idle);

vi.mock("@/hooks/useTasks", () => ({ useTasks: (...args: unknown[]) => useTasks(...args) }));
vi.mock("@/hooks/useProjects", () => ({ useProjects: () => idle }));
vi.mock("@/hooks/useCalendarEntries", () => ({ useCalendarEntries: () => idle }));
vi.mock("@/hooks/useCalendars", () => ({ useCalendarsList: () => idle }));
vi.mock("@/hooks/useCounters", () => ({ useCounterGroup: () => idle }));
vi.mock("@/hooks/useDocuments", () => ({ useDocument: () => idle }));

/** The conditions the tasks query was actually issued with. */
const conditions = (): unknown[] => {
  const params = useTasks.mock.calls.at(-1)?.[0] as { conditions?: string } | undefined;
  return params?.conditions ? JSON.parse(params.conditions) : [];
};

const run = (binding: WidgetBinding, initiativeId: number | undefined) =>
  renderHook(() => useWidgetData(binding, initiativeId));

beforeEach(() => useTasks.mockClear());

describe("useWidgetData task scoping", () => {
  it("narrows to the dashboard's initiative", () => {
    run({ source: "tasks" }, 4);
    expect(conditions()).toContainEqual({
      field: "initiative_ids",
      op: "in_",
      value: [4],
    });
  });

  it("sends no scope as a bare query parameter", () => {
    // The endpoint would ignore it, and ignoring it means guild-wide data.
    run({ source: "tasks", project_id: 9 }, 4);
    const params = useTasks.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(params.initiative_id).toBeUndefined();
    expect(params.project_id).toBeUndefined();
  });

  it("narrows to a bound project as well as the initiative", () => {
    run({ source: "tasks", project_id: 9 }, 4);
    expect(conditions()).toContainEqual({ field: "project_id", op: "eq", value: 9 });
    expect(conditions()).toHaveLength(2);
  });

  it("keeps the author's own filters alongside the scope", () => {
    const own = [{ field: "priority", op: "in_", value: ["high"] }];
    run({ source: "tasks", conditions: own }, 4);
    expect(conditions()).toEqual([{ field: "initiative_ids", op: "in_", value: [4] }, ...own]);
  });

  it("sends a single stored group as the list the endpoint expects", () => {
    // A definition may carry one group rather than a list; posting the group
    // itself would fail to parse and take the whole query with it.
    const group = { logic: "or", conditions: [{ field: "priority", op: "eq", value: "high" }] };
    run({ source: "tasks", conditions: group }, 4);
    const parsed = conditions();
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed).toContainEqual(group);
  });

  it("does not add a group level the author may still need", () => {
    // The DSL caps nesting; wrapping the author's conditions in a group of ours
    // would spend a level on an AND the top-level list already implies.
    run({ source: "tasks", conditions: [{ field: "priority", op: "eq", value: "high" }] }, 4);
    for (const condition of conditions()) {
      expect(condition).not.toHaveProperty("logic");
    }
  });

  it("asks for nothing extra when the dashboard has no initiative yet", () => {
    run({ source: "tasks" }, undefined);
    expect(conditions()).toEqual([]);
  });
});
