import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";

import { TagTasksTable } from "./TagTasksTable";

const TAG_ID = 7;

/** Capture every tasks request so the sort the table asked for is visible. */
function stubTasks() {
  const requests: URLSearchParams[] = [];
  server.use(
    guildHttp.get("/tasks/", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json({
        items: [buildTask({ title: "Water the plants" })],
        total_count: 1,
        page: 1,
        page_size: 20,
        has_next: false,
      });
    })
  );
  return requests;
}

const renderTagTasks = () =>
  renderPage(() => <TagTasksTable tagId={TAG_ID} />, { queryClient: createTestQueryClient() });

const latest = (requests: URLSearchParams[]) => requests[requests.length - 1];
const sortOf = (requests: URLSearchParams[]) => JSON.parse(latest(requests).get("sorting") ?? "[]");

describe("TagTasksTable remembered sort", () => {
  it("opens sorted by due date and remembers a different sort for the next visit", async () => {
    const user = userEvent.setup();
    const requests = stubTasks();
    const first = renderTagTasks();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(sortOf(requests)).toEqual([{ field: "due_date", dir: "asc" }]);

    // The priority column header, not the "All priorities" filter beside it.
    const priorityHeader = await screen.findByRole("columnheader", { name: /priority/i });
    await user.click(within(priorityHeader).getByRole("button"));
    await waitFor(() => expect(sortOf(requests)).toEqual([{ field: "priority", dir: "asc" }]));

    first.unmount();
    requests.length = 0;
    renderTagTasks();
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(sortOf(requests)).toEqual([{ field: "priority", dir: "asc" }]);
  });
});
