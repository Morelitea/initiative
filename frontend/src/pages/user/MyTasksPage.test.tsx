import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";

import { MyTasksPage } from "./MyTasksPage";

/** Serve one page of assigned tasks; the list has to be non-empty to render. */
function stubTasks() {
  server.use(
    http.get("/api/v1/me/tasks", () =>
      HttpResponse.json({
        items: [buildTask({ title: "Write the thing" })],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_next: false,
      })
    )
  );
}

function renderMyTasks() {
  const queryClient = createTestQueryClient();
  // Skip the preferences fetch so the table mounts with its defaults.
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, { items: {} });
  return renderPage(MyTasksPage, { queryClient });
}

/** Serve saved preferences, optionally after the tasks request has resolved. */
function stubPreferences(prefs: unknown, { delayMs = 0 } = {}) {
  server.use(
    http.get("/api/v1/user-view-preferences", async () => {
      if (delayMs > 0) await delay(delayMs);
      return HttpResponse.json({ items: { "initiative-my-tasks-filters": prefs } });
    })
  );
}

const groupSelect = () => screen.getByRole("combobox", { name: /group by/i });

describe("MyTasksPage saved sort", () => {
  it("waits for the saved sort before mounting the table", async () => {
    stubTasks();
    // Preferences land after the tasks request, which is the case that used to
    // freeze the headers on the default sort.
    stubPreferences({ sorting: [{ field: "priority", dir: "desc" }] }, { delayMs: 50 });
    renderPage(MyTasksPage, { queryClient: createTestQueryClient() });

    // Nothing is drawn on the defaults in the meantime.
    expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();

    // Once the saved sort is in hand the table mounts seeded with it — the
    // header carries a direction arrow rather than the unsorted glyph, so it
    // agrees with the order the rows came back in.
    const priorityHeader = await screen.findByRole("columnheader", { name: /priority/i });
    const icon = within(priorityHeader).getByRole("button").querySelector("svg");
    expect(icon).toHaveClass("lucide-arrow-down");
  });
});

describe("MyTasksPage grouping", () => {
  it("remembers the grouping choice for the next visit", async () => {
    const user = userEvent.setup();
    stubTasks();
    const first = renderMyTasks();

    // Opens grouped by date window, as it always has.
    await waitFor(() => expect(groupSelect()).toHaveTextContent(/date/i));

    await user.click(groupSelect());
    await user.click(screen.getByRole("option", { name: "None" }));
    await waitFor(() => expect(groupSelect()).toHaveTextContent(/none/i));

    first.unmount();
    renderMyTasks();
    await waitFor(() => expect(groupSelect()).toHaveTextContent(/none/i));
  });
});
