import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { type CalendarEntry, CalendarView } from "./CalendarView";

// Focus date + entries live in the same month so the list view keeps them.
const FOCUS = new Date("2026-06-15T12:00:00Z");

const eventEntry: CalendarEntry = {
  id: "event-1",
  title: "Launch party",
  startAt: "2026-06-15T10:00:00Z",
  endAt: "2026-06-15T11:00:00Z",
  meta: { type: "event", eventId: 1 },
};

const taskEntry: CalendarEntry = {
  id: "task-9",
  title: "Do the thing",
  startAt: "2026-06-16T10:00:00Z",
  endAt: "2026-06-16T11:00:00Z",
  meta: { type: "task" },
};

function renderList(onToggle = vi.fn()) {
  renderWithProviders(
    <CalendarView
      entries={[eventEntry, taskEntry]}
      viewMode="list"
      onViewModeChange={vi.fn()}
      focusDate={FOCUS}
      onFocusDateChange={vi.fn()}
      selectionActive
      selectedEntryIds={new Set()}
      isEntrySelectable={(e) => (e.meta as { type?: string } | undefined)?.type === "event"}
      onToggleEntrySelection={onToggle}
    />
  );
  return onToggle;
}

describe("CalendarView list-view selection", () => {
  it("shows only selectable (event) rows and toggles them", async () => {
    const user = userEvent.setup();
    const onToggle = renderList();

    // Tasks can't be shared, so they're hidden entirely while selecting — the
    // list is a picker for events only.
    expect(screen.queryByRole("button", { name: /Do the thing/i })).toBeNull();

    const eventRow = screen.getByRole("button", { name: /Launch party/i });
    expect(eventRow).not.toBeDisabled();

    await user.click(eventRow);
    expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ id: "event-1" }));
  });
});
