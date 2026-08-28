/**
 * The feed clamps every comment to two lines, so a long one needs a way out.
 * jsdom lays nothing out — `scrollHeight`/`clientHeight` are always 0 — so the
 * clamp is simulated by making scrollHeight exceed clientHeight only while the
 * element still carries the clamp class.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { RecentActivityEntry } from "@/api/generated/initiativeAPI.schemas";

import { GuildRecentComments } from "./GuildRecentComments";

const buildEntry = (overrides: Partial<RecentActivityEntry> = {}): RecentActivityEntry =>
  ({
    comment_id: 1,
    content: "Looks good to me.",
    created_at: "2026-08-27T10:00:00Z",
    entity_type: "task",
    entity_id: 5,
    task_id: 5,
    task_title: "Fix login",
    project_id: 2,
    project_name: "Apollo",
    initiative_id: 1,
    author: { id: 9, full_name: "Ada Lovelace", email: "ada@example.com" },
    ...overrides,
  }) as RecentActivityEntry;

/** Makes clamped elements report overflow, the way a browser would. */
const simulateClamping = () => {
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() {
      return 40;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return String(this.className).includes("line-clamp") ? 400 : 40;
    },
  });
};

const showFeed = (entries: RecentActivityEntry[]) => {
  server.use(guildHttp.get("/comments/recent", () => HttpResponse.json(entries)));
  return renderPage(GuildRecentComments);
};

afterEach(() => {
  // @ts-expect-error — restoring jsdom's own (absent) definitions
  delete HTMLElement.prototype.clientHeight;
  // @ts-expect-error — restoring jsdom's own (absent) definitions
  delete HTMLElement.prototype.scrollHeight;
});

describe("GuildRecentComments read more", () => {
  it("offers read more on a comment that overflows its clamp", async () => {
    simulateClamping();
    showFeed([buildEntry({ content: "A very long comment. ".repeat(50) })]);

    expect(await screen.findByRole("button", { name: /read more/i })).toBeInTheDocument();
  });

  it("expands and collapses the comment", async () => {
    simulateClamping();
    const { container } = showFeed([buildEntry({ content: "A very long comment. ".repeat(50) })]);

    await userEvent.click(await screen.findByRole("button", { name: /read more/i }));

    expect(container.querySelector(".line-clamp-2")).toBeNull();
    const collapse = screen.getByRole("button", { name: /show less/i });

    await userEvent.click(collapse);

    expect(container.querySelector(".line-clamp-2")).not.toBeNull();
    expect(screen.getByRole("button", { name: /read more/i })).toBeInTheDocument();
  });

  it("leaves a comment that fits alone", async () => {
    showFeed([buildEntry({ content: "Short." })]);

    expect(await screen.findByText("Short.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /read more/i })).toBeNull();
  });

  it("renders a preview mention without nesting a link inside the entry link", async () => {
    showFeed([buildEntry({ content: "ping #task[Fix login](5)" })]);

    expect(await screen.findByText(/Task: Fix login/)).toBeInTheDocument();
    // One link for the entry itself; the mention must not add another.
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });
});
