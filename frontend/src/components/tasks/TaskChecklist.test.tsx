import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import type { ChecklistItem } from "@/api/generated/initiativeAPI.schemas";

import { TaskChecklist } from "./TaskChecklist";

const TASK_ID = 12;

const items: ChecklistItem[] = [
  { id: "one", text: "Draft the copy", done: false },
  { id: "two", text: "Get it reviewed", done: false },
];

/** Record what each kind of write asked for, so the two can be told apart. */
function stubWrites() {
  const ticks: { itemId: string; body: unknown }[] = [];
  const listWrites: unknown[] = [];
  server.use(
    guildHttp.patch("/tasks/:taskId/checklist/:itemId", async ({ request, params }) => {
      const body = await request.json();
      ticks.push({ itemId: String(params.itemId), body });
      return HttpResponse.json(
        items.map((item) =>
          item.id === params.itemId ? { ...item, done: (body as { done: boolean }).done } : item
        )
      );
    }),
    guildHttp.patch("/tasks/:taskId", async ({ request }) => {
      const body = (await request.json()) as { checklist?: unknown };
      listWrites.push(body.checklist);
      return HttpResponse.json(buildTask({ id: TASK_ID }));
    })
  );
  return { ticks, listWrites };
}

const renderChecklist = (canEdit = true) =>
  renderPage(() => <TaskChecklist taskId={TASK_ID} items={items} canEdit={canEdit} />, {
    queryClient: createTestQueryClient(),
  });

describe("TaskChecklist", () => {
  it("ticks one item by id rather than rewriting the list", async () => {
    const user = userEvent.setup();
    const { ticks, listWrites } = stubWrites();
    renderChecklist();

    const boxes = await screen.findAllByLabelText("Mark checklist item as complete");
    await user.click(boxes[0]);

    await waitFor(() => expect(ticks).toHaveLength(1));
    expect(ticks[0]).toMatchObject({ itemId: "one", body: { done: true } });
    // The rest of the list is not part of a tick.
    expect(listWrites).toHaveLength(0);
  });

  it("shows how much is done", async () => {
    const { ticks } = stubWrites();
    const user = userEvent.setup();
    renderChecklist();

    expect(await screen.findByText("0/2 items")).toBeInTheDocument();

    await user.click(screen.getAllByLabelText("Mark checklist item as complete")[0]);

    await waitFor(() => expect(ticks).toHaveLength(1));
    expect(screen.getByText("1/2 items")).toBeInTheDocument();
  });

  it("sends the whole list when a line is added", async () => {
    const user = userEvent.setup();
    const { listWrites } = stubWrites();
    renderChecklist();

    await user.type(await screen.findByPlaceholderText("Add checklist item"), "Ship it{Enter}");

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect(listWrites[0]).toEqual([
      { id: "one", text: "Draft the copy", done: false },
      { id: "two", text: "Get it reviewed", done: false },
      { id: expect.any(String), text: "Ship it", done: false },
    ]);
  });

  it("splits a pasted block into one item per line", async () => {
    const user = userEvent.setup();
    const { listWrites } = stubWrites();
    renderChecklist();

    await user.click(await screen.findByPlaceholderText("Add checklist item"));
    await user.paste("- First thing\n- Second thing");

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect((listWrites[0] as { text: string }[]).map((item) => item.text)).toEqual([
      "Draft the copy",
      "Get it reviewed",
      "First thing",
      "Second thing",
    ]);
  });

  it("opens a fresh line on Enter without saving it until it says something", async () => {
    const user = userEvent.setup();
    const { listWrites } = stubWrites();
    renderChecklist();

    const first = await screen.findByDisplayValue("Draft the copy");
    await user.click(first);
    await user.keyboard("{Enter}");

    // A blank line is not a checklist item, so nothing has been sent.
    expect(listWrites).toHaveLength(0);
    expect(screen.getAllByPlaceholderText("Checklist item")).toHaveLength(3);

    await user.keyboard("Third thing");
    await user.tab();

    await waitFor(() => expect(listWrites).toHaveLength(1));
    expect((listWrites[0] as { text: string }[]).map((item) => item.text)).toEqual([
      "Draft the copy",
      "Third thing",
      "Get it reviewed",
    ]);
  });

  it("offers no edits without write access", async () => {
    stubWrites();
    renderChecklist(false);

    expect(await screen.findByPlaceholderText("Read-only")).toBeDisabled();
    expect(screen.queryByLabelText("Delete checklist item")).not.toBeInTheDocument();
  });
});
