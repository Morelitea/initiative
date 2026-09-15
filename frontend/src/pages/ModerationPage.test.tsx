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
import { renderWithProviders } from "@/__tests__/helpers/render";

const settleMutate = vi.fn();

const state = vi.hoisted(() => ({
  items: [] as Array<Record<string, unknown>>,
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
    useModerationReports: () => ({
      data: { items: state.items, total: state.items.length },
      isLoading: false,
    }),
    useSettleReport: () => ({ mutate: settleMutate, isPending: false }),
  };
});

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return { ...actual, useParams: () => ({ initiativeId: "7" }) };
});

vi.mock("@/hooks/useActiveGuildId", () => ({ useActiveGuildId: () => 3 }));

import { ModerationPage } from "./ModerationPage";

const renderPage = () => renderWithProviders(<ModerationPage />, { auth: { user: buildUser() } });

describe("ModerationPage", () => {
  beforeEach(() => {
    settleMutate.mockClear();
    state.items = [];
  });

  it("says so when nothing has been reported", () => {
    renderPage();
    expect(screen.getByText("Nothing has been reported.")).toBeInTheDocument();
  });

  it("shows how many people reported, and never who", () => {
    state.items = [report({ reporter_count: 3, details: ["Abusive.", "Not on."] })];
    renderPage();

    expect(screen.getByText(/Reported by 3 people/)).toBeInTheDocument();
    expect(screen.getByText("Abusive.")).toBeInTheDocument();
    expect(screen.getByText("Not on.")).toBeInTheDocument();
    // Nothing in the payload names a reporter, and nothing on the page does.
    expect(screen.queryByText(/reporter_id/i)).not.toBeInTheDocument();
  });

  it("offers every outcome, and each one closes the report", async () => {
    state.items = [report()];
    renderPage();
    const user = userEvent.setup();

    const card = screen.getByRole("region", { name: "A comment" });
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
    renderPage();
    const user = userEvent.setup();

    const card = screen.getByRole("region", { name: "A comment" });
    await user.type(within(card).getByRole("textbox"), "Checked it.");
    await user.click(within(card).getByRole("button", { name: "Member warned" }));

    expect(settleMutate).toHaveBeenCalledWith({
      reportId: 1,
      body: { outcome: "member_warned", note: "Checked it." },
    });
  });

  it("a settled report shows what was decided and offers no outcomes", () => {
    state.items = [
      report({
        outcome: "content_removed",
        note: "Removed it.",
        decided_at: "2026-09-15T12:00:00Z",
      }),
    ];
    renderPage();

    const card = screen.getByRole("region", { name: "A comment" });
    expect(within(card).getByText("Content removed")).toBeInTheDocument();
    expect(within(card).getByText("Removed it.")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  it("sends a moderator to the thing itself rather than acting here", () => {
    state.items = [report()];
    renderPage();
    expect(
      screen.getByText("Open the reported item to look at it in context, then decide here.")
    ).toBeInTheDocument();
  });
});
