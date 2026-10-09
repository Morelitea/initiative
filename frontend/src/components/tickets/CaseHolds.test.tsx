/**
 * What is held on a case: read under the reader's grant on the community the
 * content is in, released from here, and the reported content held from here.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { ContentHoldRead } from "@/api/generated/initiativeAPI.schemas";

const state = vi.hoisted(() => ({
  holds: [] as ContentHoldRead[],
  refused: false,
}));
const release = vi.fn();

vi.mock("@/hooks/useHolds", () => ({
  useCaseHolds: () => ({
    data: state.refused ? undefined : state.holds,
    isLoading: false,
    isError: state.refused,
    isSuccess: !state.refused,
  }),
  useReleaseHold: () => ({ mutate: release, isPending: false }),
  usePlaceHold: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { CaseHolds } from "./CaseHolds";

const now = new Date().toISOString();
const hold = (overrides: Partial<ContentHoldRead> = {}): ContentHoldRead => ({
  id: 5,
  target_type: "comment",
  target_id: 42,
  label: null,
  case_task_id: 3,
  placed_via: "community",
  reason: "illegal_content",
  legal_basis: "privacy",
  note: "Court order 12",
  placed_at: now,
  released_at: null,
  release_outcome: null,
  ...overrides,
});

const show = () =>
  renderPage(
    () => <CaseHolds taskId={3} communityId={8} resourceType="comment" resourceId={42} />,
    { auth: { user: buildUser() } }
  );

describe("CaseHolds", () => {
  beforeEach(() => {
    state.holds = [];
    state.refused = false;
    release.mockReset();
  });

  it("says how to see them without a grant", async () => {
    state.refused = true;
    show();
    expect(await screen.findByText(/request moderation access/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request access" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hold the reported content" })).toBeNull();
  });

  it("shows a hold with its note, and releases it", async () => {
    state.holds = [hold()];
    show();
    expect(await screen.findByText("Court order 12")).toBeInTheDocument();
    expect(screen.getByText(/May be illegal · Privacy/)).toBeInTheDocument();
    // Already held: nothing more to hold.
    expect(screen.queryByRole("button", { name: "Hold the reported content" })).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(release).toHaveBeenCalledWith({ holdId: 5, outcome: "restore" });

    await user.click(screen.getByRole("button", { name: "Purge" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Purge" }));
    expect(release).toHaveBeenCalledWith({ holdId: 5, outcome: "purge" });
  });

  it("offers to hold what was reported when nothing is", async () => {
    show();
    expect(await screen.findByText("Nothing is held on this case.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hold the reported content" })).toBeInTheDocument();
  });

  it("says how a released hold ended", async () => {
    state.holds = [hold({ released_at: now, release_outcome: "remove" })];
    show();
    expect(await screen.findByText("Released: removed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
  });
});
