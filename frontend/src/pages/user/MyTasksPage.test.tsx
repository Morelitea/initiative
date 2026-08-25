import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
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

const groupSelect = () => screen.getByRole("combobox", { name: /group by/i });

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
