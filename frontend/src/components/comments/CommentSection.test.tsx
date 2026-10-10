import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildComment } from "@/__tests__/factories/comment.factory";
import { buildUser } from "@/__tests__/factories/user.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommentCreate, SubjectReadRequest } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { CommentSection } from "./CommentSection";

/** Registers the create handler and resolves the body it received. */
const captureCreate = (): { body: () => CommentCreate | null } => {
  let received: CommentCreate | null = null;
  server.use(
    communityHttp.post("/comments/", async ({ request }) => {
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
      communityHttp.delete("/comments/:commentId", ({ params }) => {
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

  it("offers no mention suggestions for a community-level entity", async () => {
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

  it("keeps replies to a comment the reader can't see under a placeholder", async () => {
    const visible = buildComment({ content: "Still here", created_at: "2026-01-10T09:00:00Z" });
    const replyA = buildComment({
      content: "Answering the hidden one",
      parent_comment_id: 9999,
      created_at: "2026-01-11T09:00:00Z",
    });
    const replyB = buildComment({
      content: "Me too",
      parent_comment_id: 9999,
      created_at: "2026-01-12T09:00:00Z",
    });

    renderPage(() => (
      <CommentSection
        entityType="task"
        entityId={3}
        comments={[visible, replyA, replyB]}
        initiativeId={7}
      />
    ));

    const placeholder = await screen.findByText("Unavailable");
    // One placeholder for the hidden comment, and its replies after it, in order.
    expect(screen.getAllByText("Unavailable")).toHaveLength(1);
    const said = [
      placeholder,
      screen.getByText("Answering the hidden one"),
      screen.getByText("Me too"),
    ];
    for (let i = 1; i < said.length; i++) {
      expect(said[i - 1].compareDocumentPosition(said[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING
      );
    }
    // The newer conversation (the placeholder's) comes first.
    expect(
      placeholder.compareDocumentPosition(screen.getByText("Still here")) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("shows a tombstone where a comment was, saying who took it out and never what it said", async () => {
    const removed = buildComment({
      id: 1,
      task_id: 3,
      content: "",
      author: null,
      created_by: null,
      removed: { by: "moderator", reason: "harassment" },
    });
    const legal = buildComment({
      id: 2,
      task_id: 3,
      content: "",
      author: null,
      created_by: null,
      removed: { by: "moderator", reason: "illegal" },
    });
    const deleted = buildComment({
      id: 3,
      task_id: 3,
      content: "",
      author: null,
      created_by: null,
      removed: { by: "author", reason: null },
    });
    const reply = buildComment({
      id: 4,
      task_id: 3,
      parent_comment_id: 3,
      content: "Still answering it",
      created_by: 99,
      author: {
        id: 99,
        username: "someone-else",
        discriminator: 1002,
        display_name: "Someone Else",
        avatar_url: null,
        presence: "offline",
      },
    });

    renderPage(() => (
      <CommentSection
        entityType="task"
        entityId={3}
        comments={[removed, legal, deleted, reply]}
        initiativeId={7}
      />
    ));

    expect(await screen.findByText("Removed by a moderator · Harassment")).toBeInTheDocument();
    expect(screen.getByText("Removed for legal reasons")).toBeInTheDocument();
    expect(screen.getByText("Deleted by its author")).toBeInTheDocument();
    // The reply reads under the tombstone, where it was said.
    expect(screen.getByText("Still answering it")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    // Nothing on a tombstone to report: only the reply offers it.
    expect(await screen.findAllByRole("button", { name: "Report" })).toHaveLength(1);
  });

  it("keeps the composer from members while a moderator has the thread locked", async () => {
    renderPage(() => (
      <CommentSection entityType="task" entityId={3} comments={[]} initiativeId={7} locked />
    ));

    expect(await screen.findByText("A moderator locked comments here.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /post comment/i })).not.toBeInTheDocument();
  });

  it("lets a moderator write in a locked thread and act on comments", async () => {
    const theirs = buildComment({ id: 7, task_id: 3, content: "Out of line" });
    renderPage(() => (
      <CommentSection
        entityType="task"
        entityId={3}
        comments={[theirs]}
        initiativeId={7}
        locked
        canModerate
      />
    ));

    expect(await screen.findByRole("button", { name: /post comment/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Moderate" }));
    expect(await screen.findByRole("menuitem", { name: "Remove…" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Clear reactions" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Hold for the platform…" })).toBeInTheDocument();
    // A comment has no thread of its own to lock.
    expect(screen.queryByRole("menuitem", { name: "Lock comments" })).not.toBeInTheDocument();
  });

  it("offers members no moderation", async () => {
    const theirs = buildComment({ id: 7, task_id: 3, content: "Out of line" });
    renderPage(() => (
      <CommentSection entityType="task" entityId={3} comments={[theirs]} initiativeId={7} />
    ));

    await screen.findByText("Out of line");
    expect(screen.queryByRole("button", { name: "Moderate" })).not.toBeInTheDocument();
  });
});
