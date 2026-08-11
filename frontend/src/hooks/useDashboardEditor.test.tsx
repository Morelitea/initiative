/**
 * Editing state, and specifically what happens to a draft while a save is in
 * flight.
 *
 * Drags land faster than requests return, so "the save succeeded" and "the
 * draft is still what we saved" are different questions. Conflating them loses
 * whatever the user did in between — silently, since the canvas just snaps back
 * to the server's older arrangement.
 *
 * The fake below *stores* what it is given and the test re-renders with the new
 * dashboard, because that is what the real flow does (mutate → invalidate →
 * refetch). A fake that acknowledged saves without keeping them would make a
 * re-added widget byte-identical to an older save's payload, and the test would
 * then be measuring the fake rather than the hook.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardRead, WidgetCatalog } from "@/api/generated/initiativeAPI.schemas";
import { useDashboardEditor } from "@/hooks/useDashboardEditor";
import { type DashboardDefinition, EMPTY_DEFINITION } from "@/lib/widgets/definition";

interface SavePayload {
  definition: DashboardDefinition;
}

/** Server-side state, plus a resolver per in-flight save so a test can land
 *  them in whatever order it likes. */
let server: DashboardDefinition = EMPTY_DEFINITION;
const settlers: (() => void)[] = [];

const mutate = vi.fn((body: unknown, options?: { onSuccess?: () => void }) => {
  const { definition } = body as SavePayload;
  settlers.push(() => {
    server = definition;
    options?.onSuccess?.();
  });
});

vi.mock("@/hooks/useDashboards", () => ({
  useUpdateDashboard: () => ({ mutate, isPending: false }),
}));

const catalog = {
  widgets: [
    {
      type: "kpi",
      min_w: 2,
      min_h: 2,
      default_w: 3,
      default_h: 2,
      sources: ["counter"],
      options: [],
    },
  ],
  presets: [],
} as unknown as WidgetCatalog;

const asDashboard = (definition: DashboardDefinition) =>
  ({ id: 7, definition, config: { widgets: {} } }) as unknown as DashboardRead;

const SAVE_DEBOUNCE_MS = 600;

beforeEach(() => {
  server = EMPTY_DEFINITION;
  settlers.length = 0;
  mutate.mockClear();
  // No shouldAdvanceTime: the debounce is the thing under test, so only an
  // explicit advance may fire it.
  vi.useFakeTimers();
});

const setup = (canEdit = true) => {
  const rendered = renderHook(({ dashboard }) => useDashboardEditor(dashboard, catalog, canEdit), {
    initialProps: { dashboard: asDashboard(server) },
  });
  return {
    ...rendered,
    /** What a refetch after a successful save does. */
    refetch: () => rendered.rerender({ dashboard: asDashboard(server) }),
    settle: () => act(() => vi.advanceTimersByTime(SAVE_DEBOUNCE_MS)),
    add: () => act(() => rendered.result.current.addWidget("kpi", "counter")),
    widgets: () => rendered.result.current.definition.widgets,
  };
};

describe("useDashboardEditor", () => {
  it("debounces a burst of edits into one save", () => {
    const editor = setup();

    editor.add();
    editor.add();
    editor.add();
    expect(mutate).not.toHaveBeenCalled();

    editor.settle();
    expect(mutate).toHaveBeenCalledTimes(1);
    // The last state wins, not the first.
    expect((mutate.mock.calls[0][0] as SavePayload).definition.widgets).toHaveLength(3);
  });

  it("shows the edit immediately, before the save lands", () => {
    const editor = setup();
    editor.add();
    expect(editor.widgets()).toHaveLength(1);
  });

  it("hands control back to the server once the draft matches what was saved", () => {
    const editor = setup();
    editor.add();
    editor.settle();

    act(() => settlers[0]());
    editor.refetch();

    // The draft is gone and the server's own copy is what renders — same
    // arrangement, now authoritative.
    expect(editor.widgets()).toHaveLength(1);
  });

  it("does not discard work done while a save was in flight", () => {
    const editor = setup();

    editor.add();
    editor.settle();
    expect(mutate).toHaveBeenCalledTimes(1);

    // A second edit before the first save returns.
    editor.add();
    expect(editor.widgets()).toHaveLength(2);

    act(() => settlers[0]());
    editor.refetch();

    // The older save must not reset the canvas to its one-widget state.
    expect(editor.widgets()).toHaveLength(2);
  });

  it("ignores a stale response that lands after a newer edit", () => {
    const editor = setup();

    editor.add();
    editor.settle();
    editor.add();
    editor.settle();
    expect(mutate).toHaveBeenCalledTimes(2);

    // The newer save returns and correctly hands control back to the server.
    act(() => settlers[1]());
    editor.refetch();
    expect(editor.widgets()).toHaveLength(2);

    // The user carries on editing...
    editor.add();
    expect(editor.widgets()).toHaveLength(3);

    // ...and the first save's response finally arrives. It belongs to an
    // arrangement two edits ago and must not clear what is on screen now.
    act(() => settlers[0]());
    expect(editor.widgets()).toHaveLength(3);
  });

  it("saves nothing without write access", () => {
    const editor = setup(false);
    editor.add();
    editor.settle();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("flushes a pending edit rather than losing it on unmount", () => {
    const editor = setup();
    editor.add();
    expect(mutate).not.toHaveBeenCalled();

    editor.unmount();
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("does not save on an ordinary re-render", () => {
    // The unmount-flush effect must not re-run on every render: its cleanup
    // would fire mid-edit and turn the debounce into a save per drag frame.
    const editor = setup();
    editor.add();
    editor.refetch();
    editor.refetch();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("ignores a layout that did not actually change", () => {
    const editor = setup();
    act(() => editor.result.current.replaceDefinition(editor.result.current.definition));
    editor.settle();
    expect(mutate).not.toHaveBeenCalled();
  });
});
