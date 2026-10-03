import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildComment } from "@/__tests__/factories/comment.factory";
import { buildUser } from "@/__tests__/factories/user.factory";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommentCreate, SubjectReadRequest } from "@/api/generated/initiativeAPI.schemas";
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
  // The composer arrives with the route, which mounts a tick after render.
  await userEvent.type(await screen.findByRole("textbox"), text);
  await userEvent.click(screen.getByRole("button", { name: /post comment/i }));
};

describe("CommentSection", () => {
  it("offers Delete only where the server says the reader may, and asks first", async () => {
    let deleted: string | null = null;
    server.use(
      guildHttp.delete("/comments/:commentId", ({ params }) => {
        deleted = String(params.commentId);
        return new HttpResponse(null, { status: 204 });
      })
    );
    const mine = buildComment({ content: "Removable", task_id: 3, can_remove: true });
    const theirs = buildComment({ content: "Not removable", task_id: 3, can_remove: false });

    renderPage(() => (
      <CommentSection entityType="task" entityId={3} comments={[mine, theirs]} initiativeId={7} />
    ));

    await screen.findByText("Removable");
    const deleteButtons = screen.getAllByRole("button", { name: /^delete$/i });
    expect(deleteButtons).toHaveLength(1);

    await userEvent.click(deleteButtons[0]);
    expect(deleted).toBeNull();
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Delete this comment?");
    await userEvent.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleted).toBe(String(mine.id)));
  });

  it("posts a queue comment under queue_id", async () => {
    const created = captureCreate();

    renderPage(() => (
      <CommentSection entityType={Tool.queue} entityId={42} comments={[]} initiativeId={7} />
    ));

    await postComment("Whose turn is it?");

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({ content: "Whose turn is it?", queue_id: 42 });
  });

  it("posts a counter-group comment under counter_group_id", async () => {
    const created = captureCreate();

    renderPage(() => (
      <CommentSection entityType={Tool.counter_group} entityId={9} comments={[]} initiativeId={7} />
    ));

    await postComment("Reset these before the next session.");

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({
      content: "Reset these before the next session.",
      counter_group_id: 9,
    });
  });

  it("posts a task comment under task_id", async () => {
    const created = captureCreate();

    renderPage(() => (
      <CommentSection entityType="task" entityId={3} comments={[]} initiativeId={7} />
    ));

    await postComment("Picking this up.");

    await waitFor(() => expect(created.body()).not.toBeNull());
    expect(created.body()).toEqual({ content: "Picking this up.", task_id: 3 });
  });

  it("carries the parent id when replying", async () => {
    const created = captureCreate();
    const parent = buildComment({ content: "Original", calendar_id: 5 });

    renderPage(() => (
      <CommentSection
        entityType={Tool.calendar}
        entityId={5}
        comments={[parent]}
        initiativeId={7}
      />
    ));

    await userEvent.click(await screen.findByRole("button", { name: /^reply$/i }));
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

  it("reads the thread on opening and marks what was unread", async () => {
    const me = buildUser();
    const other = buildUser();
    const named = buildComment({ content: "Named by a line", created_by: me.id });
    const olderByOther = buildComment({
      content: "Before the roll-up",
      created_by: other.id,
      created_at: "2026-01-01T00:00:00Z",
    });
    const newerByOther = buildComment({
      content: "After the roll-up",
      created_by: other.id,
      created_at: "2026-01-03T00:00:00Z",
    });
    const newerByMe = buildComment({
      content: "My own reply",
      created_by: me.id,
      created_at: "2026-01-03T00:00:00Z",
    });
    let read: SubjectReadRequest | null = null;
    server.use(
      http.post("/api/v1/notifications/read-subject", async ({ request }) => {
        read = (await request.json()) as SubjectReadRequest;
        return HttpResponse.json({ comment_ids: [named.id], since: "2026-01-02T00:00:00Z" });
      })
    );

    renderPage(
      () => (
        <CommentSection
          entityType="task"
          entityId={3}
          comments={[named, olderByOther, newerByOther, newerByMe]}
          initiativeId={7}
        />
      ),
      { auth: { user: me } }
    );

    const marked = (text: string) => screen.getByText(text).closest("[data-unread]") !== null;
    await waitFor(() => expect(marked("Named by a line")).toBe(true));
    expect(read).toEqual({ community_id: 1, subject_type: "task", subject_id: 3 });
    expect(marked("After the roll-up")).toBe(true);
    expect(marked("Before the roll-up")).toBe(false);
    expect(marked("My own reply")).toBe(false);
  });

  it("offers no mention suggestions for a guild-level entity", async () => {
    renderPage(() => (
      <CommentSection entityType={Tool.calendar} entityId={5} comments={[]} initiativeId={0} />
    ));

    await userEvent.type(await screen.findByRole("textbox"), "@al");

    // The suggestion lookup is an initiative search, so it stays off and the
    // popover reports an empty list rather than failing.
    expect(await screen.findByText(/no one by that name/i)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("@al");
  });

  it("puts the newest conversation first and keeps each one's replies in order", async () => {
    const older = buildComment({ content: "Older thread", created_at: "2026-01-10T09:00:00Z" });
    const newer = buildComment({ content: "Newer thread", created_at: "2026-01-12T09:00:00Z" });
    const firstReply = buildComment({
      content: "First reply",
      parent_comment_id: older.id,
      created_at: "2026-01-13T09:00:00Z",
    });
    const secondReply = buildComment({
      content: "Second reply",
      parent_comment_id: older.id,
      created_at: "2026-01-14T09:00:00Z",
    });

    renderPage(() => (
      <CommentSection
        entityType={Tool.queue}
        entityId={42}
        comments={[older, firstReply, newer, secondReply]}
        initiativeId={7}
      />
    ));

    await screen.findByText("Newer thread");
    const said = ["Newer thread", "Older thread", "First reply", "Second reply"].map((text) =>
      screen.getByText(text)
    );
    for (let i = 1; i < said.length; i++) {
      expect(said[i - 1].compareDocumentPosition(said[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING
      );
    }
  });
});
