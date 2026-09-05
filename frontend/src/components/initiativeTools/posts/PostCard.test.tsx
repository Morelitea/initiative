/**
 * One notice on the board.
 *
 * Two things are load-bearing. A pinned post says so, and says *until when*
 * when the pin has an end — a notice about a date that stops shouting is the
 * whole point of the expiry. And the pin control is offered on the reader's
 * authority over the initiative, not on their access to the post: an author
 * with owner-level access to their own notice still cannot lift it above
 * everyone else's, which is the rule the server enforces.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildPost } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { PostCard } from "./PostCard";

// The headline is a router Link, so the card needs a router around it.
const cardPage = (props: Parameters<typeof PostCard>[0]) => () => <PostCard {...props} />;

// The body is a Lexical editor; mounting one per card is the cost the board's
// small page size exists to bound, and none of it is what these cases are
// about.
vi.mock("@/components/initiativeTools/posts/PostBody", () => ({
  PostBody: ({ body }: { body: Record<string, unknown> }) => (
    <div data-testid="post-body">{JSON.stringify(body)}</div>
  ),
}));

describe("PostCard", () => {
  it("shows the headline and the body", async () => {
    const post = buildPost({ name: "Server maintenance Sunday" });
    renderPage(cardPage({ post }));

    expect(await screen.findByText("Server maintenance Sunday")).toBeInTheDocument();
    expect(screen.getByTestId("post-body")).toBeInTheDocument();
  });

  it("says a post is pinned, and until when if the pin ends", async () => {
    const post = buildPost({
      is_pinned: true,
      pinned_at: "2026-02-01T00:00:00.000Z",
      pin_expires_at: "2026-03-01T00:00:00.000Z",
    });
    renderPage(cardPage({ post }));

    expect(await screen.findByText(/pinned until/i)).toBeInTheDocument();
  });

  it("says only that it is pinned when the pin has no end", async () => {
    const post = buildPost({ is_pinned: true, pinned_at: "2026-02-01T00:00:00.000Z" });
    renderPage(cardPage({ post }));

    expect(await screen.findByText(/pinned to the top/i)).toBeInTheDocument();
  });

  // A lapsed pin still carries pinned_at; the server decides `is_pinned`, and
  // the card must believe it rather than re-deriving from the columns.
  it("treats a lapsed pin as not pinned", async () => {
    const post = buildPost({
      is_pinned: false,
      pinned_at: "2026-01-01T00:00:00.000Z",
      pin_expires_at: "2026-01-02T00:00:00.000Z",
    });
    const { container } = renderPage(cardPage({ post }));
    await screen.findByTestId("post-body");

    expect(screen.queryByText(/pinned/i)).not.toBeInTheDocument();
    expect(container.querySelector(".border-primary\\/40")).toBeNull();
  });

  it("offers the pin control only to a reader who may pin", async () => {
    const post = buildPost({ my_permission_level: "owner" });

    const { unmount } = renderPage(cardPage({ post, canPin: false }));
    await screen.findByTestId("post-body");
    expect(screen.queryByRole("button", { name: /pin/i })).not.toBeInTheDocument();
    unmount();

    renderPage(cardPage({ post, canPin: true }));
    expect(await screen.findByRole("button", { name: /pin to top/i })).toBeInTheDocument();
  });

  it("says how many comments a post has", async () => {
    renderPage(cardPage({ post: buildPost({ comment_count: 3 }) }));

    expect(await screen.findByText("3 comments")).toBeInTheDocument();
  });

  it("counts one comment as one", async () => {
    renderPage(cardPage({ post: buildPost({ comment_count: 1 }) }));

    expect(await screen.findByText("1 comment")).toBeInTheDocument();
  });

  // "0 comments" reads as an absence; an invitation reads as a way in.
  it("invites the first comment rather than counting none", async () => {
    renderPage(cardPage({ post: buildPost({ comment_count: 0 }) }));

    expect(await screen.findByText(/be the first to comment/i)).toBeInTheDocument();
    expect(screen.queryByText(/0 comments/)).not.toBeInTheDocument();
  });

  it("says nothing about a thread that is turned off", async () => {
    const post = buildPost({ comments_disabled: true, comment_count: 0 });
    renderPage(cardPage({ post }));
    await screen.findByTestId("post-body");

    expect(screen.queryByText(/be the first to comment/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/comment/i)).not.toBeInTheDocument();
  });

  it("offers unpinning on a post that is pinned", async () => {
    const post = buildPost({ is_pinned: true, pinned_at: "2026-02-01T00:00:00.000Z" });
    renderPage(cardPage({ post, canPin: true }));

    expect(await screen.findByRole("button", { name: /unpin/i })).toBeInTheDocument();
  });
});
