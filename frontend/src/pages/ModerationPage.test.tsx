/**
 * The Moderation page.
 *
 * Two things matter and neither is cosmetic: a moderator is shown *how many*
 * people reported something and never who, and every outcome is a close — the
 * page has no state between "open" and "decided".
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const settleMutate = vi.fn();

const state = vi.hoisted(() => ({
  items: [] as Array<Record<string, unknown>>,
  offset: 0,
}));

const report = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  initiative_id: 7,
  target_type: "comment",
  target_id: 42,
  reason: "harassment",
  reported_at: "2026-09-15T10:00:00Z",
  reporter_count: 1,
  details: [],
  outcome: null,
  note: null,
  decided_by: null,
  decided_at: null,
  ...overrides,
});

vi.mock("@/hooks/useModeration", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useModeration")>();
  return {
    ...actual,
    useModerationReports: (params: { offset?: number }) => {
      state.offset = params.offset ?? 0;
      return {
        data: { items: state.items, total: state.items.length },
        isLoading: false,
      };
    },
    useSettleReport: () => ({ mutate: settleMutate, isPending: false }),
  };
});

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 3 }));

import { ModerationPage } from "./ModerationPage";

// The real route tree, so `<Link>` has a router and the initiative comes from
// the path the way it does in the app.
const render = () =>
  renderPage(ModerationPage, {
    auth: { user: buildUser() },
    initialRoute: "/c/$guildId/i/$initiativeId/moderation",
    routeParams: { guildId: "3", initiativeId: "7" },
  });

describe("ModerationPage", () => {
  beforeEach(() => {
    settleMutate.mockClear();
    state.items = [];
    state.offset = 0;
  });

  it("says so when nothing has been reported", async () => {
    render();
    expect(await screen.findByText("Nothing has been reported.")).toBeInTheDocument();
  });

  it("shows how many people reported, and never who", async () => {
    state.items = [report({ reporter_count: 3, details: ["Abusive.", "Not on."] })];
    render();

    expect(await screen.findByText(/Reported by 3 people/)).toBeInTheDocument();
    expect(screen.getByText("Abusive.")).toBeInTheDocument();
    expect(screen.getByText("Not on.")).toBeInTheDocument();
    // Nothing in the payload names a reporter, and nothing on the page does.
    expect(screen.queryByText(/reporter_id/i)).not.toBeInTheDocument();
  });

  it("offers every outcome, and each one closes the report", async () => {
    state.items = [report()];
    render();
    const user = userEvent.setup();

    const card = await screen.findByRole("region", { name: "A comment" });
    for (const label of ["Dismiss", "Content removed", "Member warned", "Escalate"]) {
      expect(within(card).getByRole("button", { name: label })).toBeInTheDocument();
    }

    await user.click(within(card).getByRole("button", { name: "Dismiss" }));
    expect(settleMutate).toHaveBeenCalledWith({
      reportId: 1,
      body: { outcome: "dismissed", note: null },
    });
  });

  it("carries the moderator's note with the decision", async () => {
    state.items = [report()];
    render();
    const user = userEvent.setup();

    const card = await screen.findByRole("region", { name: "A comment" });
    await user.type(within(card).getByRole("textbox"), "Checked it.");
    await user.click(within(card).getByRole("button", { name: "Member warned" }));

    expect(settleMutate).toHaveBeenCalledWith({
      reportId: 1,
      body: { outcome: "member_warned", note: "Checked it." },
    });
  });

  it("a settled report shows what was decided and offers no outcomes", async () => {
    state.items = [
      report({
        outcome: "content_removed",
        note: "Removed it.",
        decided_at: "2026-09-15T12:00:00Z",
      }),
    ];
    render();

    const card = await screen.findByRole("region", { name: "A comment" });
    expect(within(card).getByText("Content removed")).toBeInTheDocument();
    expect(within(card).getByText("Removed it.")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  it("sends a moderator to the thing itself rather than acting here", async () => {
    state.items = [report()];
    render();
    expect(
      await screen.findByText("Open the reported item to look at it in context, then decide here.")
    ).toBeInTheDocument();
  });

  it("links the reported item through the resolver", async () => {
    state.items = [report({ target_type: "task", target_id: 88 })];
    render();

    const link = await screen.findByRole("link", { name: "A task" });
    expect(link).toHaveAttribute("href", expect.stringContaining("/go/task/88"));
  });

  it("leaves a kind with no page of its own as plain text", async () => {
    // A queue item is reached through its queue, so there is nowhere to link.
    state.items = [report({ target_type: "queue_item", target_id: 5 })];
    render();

    expect(await screen.findByText("A queue item")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "A queue item" })).not.toBeInTheDocument();
  });

  it("offers a further page once one is full", async () => {
    state.items = Array.from({ length: 50 }, (_, i) => report({ id: i + 1 }));
    render();
    const user = userEvent.setup();

    const older = await screen.findByRole("button", { name: "Older" });
    expect(screen.getByRole("button", { name: "Newer" })).toBeDisabled();

    await user.click(older);
    expect(state.offset).toBe(50);
  });

  it("offers no paging when one page holds everything", async () => {
    state.items = [report()];
    render();
    await screen.findByRole("region", { name: "A comment" });
    expect(screen.queryByRole("button", { name: "Older" })).not.toBeInTheDocument();
  });
});
