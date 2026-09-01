import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildComment } from "@/__tests__/factories/comment.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommentCreate } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { CommentSection } from "./CommentSection";

/** Registers the create handler and resolves the body it received. */
const captureCreate = (): { body: () => CommentCreate | null } => {
  let received: CommentCreate | null = null;
  server.use(
    guildHttp.post("/comments/", async ({ request }) => {
      received = (await request.json()) as CommentCreate;
      return HttpResponse.json(buildComment({ content: received.content }), { status: 201 });
    })
  );
  return { body: () => received };
};

const postComment = async (text: string) => {
  await userEvent.type(screen.getByRole("textbox"), text);
  await userEvent.click(screen.getByRole("button", { name: /post comment/i }));
};

describe("CommentSection", () => {
  it("posts a queue comment under queue_id", async () => {
    const created = captureCreate();

    renderWithProviders(
      <CommentSection entityType={Tool.queue} entityId={42} comments={[]} initiativeId={7} />
    );

    await postComment("Whose turn is it?");

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({ content: "Whose turn is it?", queue_id: 42 });
  });

  it("posts a counter-group comment under counter_group_id", async () => {
    const created = captureCreate();

    renderWithProviders(
      <CommentSection entityType={Tool.counter_group} entityId={9} comments={[]} initiativeId={7} />
    );

    await postComment("Reset these before the next session.");

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({
      content: "Reset these before the next session.",
      counter_group_id: 9,
    });
  });

  it("posts a task comment under task_id", async () => {
    const created = captureCreate();

    renderWithProviders(
      <CommentSection entityType="task" entityId={3} comments={[]} initiativeId={7} />
    );

    await postComment("Picking this up.");

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({ content: "Picking this up.", task_id: 3 });
  });

  it("carries the parent id when replying", async () => {
    const created = captureCreate();
    const parent = buildComment({ content: "Original", calendar_id: 5 });

    renderWithProviders(
      <CommentSection
        entityType={Tool.calendar}
        entityId={5}
        comments={[parent]}
        initiativeId={7}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: /^reply$/i }));
    const replyBox = screen.getAllByRole("textbox")[1];
    await userEvent.type(replyBox, "Sounds right.");
    await userEvent.click(screen.getAllByRole("button", { name: /^reply$/i })[1]);

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({
      content: "Sounds right.",
      calendar_id: 5,
      parent_comment_id: parent.id,
    });
  });

  it("offers no mention suggestions for a guild-level entity", async () => {
    renderWithProviders(
      <CommentSection entityType={Tool.calendar} entityId={5} comments={[]} initiativeId={0} />
    );

    await userEvent.type(screen.getByRole("textbox"), "@al");

    // The suggestion lookup is an initiative search, so it stays off and the
    // popover reports an empty list rather than failing.
    expect(await screen.findByText(/no one by that name/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("@al");
  });
});
