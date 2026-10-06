import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { useCommunities } from "@/hooks/useCommunities";

// Two communities, so the first step is one somebody actually walks — with a
// single one the wizard walks past it on its own.
const communities = [
  buildCommunity({ name: "Anvil Club" }),
  buildCommunity({ name: "Bellwether" }),
];
// Two initiatives, so the second step does not auto-advance either.
const initiativesResult = {
  initiatives: [buildInitiative({ name: "Spring Play" }), buildInitiative({ name: "Summer Play" })],
  isLoading: false,
};

const communitiesValue: ReturnType<typeof useCommunities> = {
  communities: communities,
  activeCommunityId: null,
  activeCommunity: null,
  activeCommunityReadOnly: false,
  loading: false,
  error: null,
  refreshCommunities: vi.fn(),
  switchCommunity: vi.fn(),
  syncCommunityFromUrl: vi.fn(),
  createCommunity: vi.fn(),
  updateCommunityInState: vi.fn(),
  reorderCommunities: vi.fn(),
  canCreateCommunities: true,
};

// Partial: the render helper reaches for ``CommunityContext`` from this module.
vi.mock(import("@/hooks/useCommunities"), async (importOriginal) => ({
  ...(await importOriginal()),
  useCommunities: () => communitiesValue,
}));

vi.mock("@/hooks/useInitiativeAccess", () => ({
  communityMayAuthorTools: () => true,
  useCreatableInitiatives: () => initiativesResult,
}));

vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ navigate: vi.fn() }),
}));

vi.mock("@/lib/storage", () => ({
  getItem: () => null,
  setItem: vi.fn(),
  removeItem: vi.fn(),
}));

import { CreateToolWizard, getOpenCreateToolWizard } from "./CreateToolWizard";

const openWizard = async () => {
  renderWithProviders(<CreateToolWizard tool={Tool.document} />, { auth: { user: buildUser() } });
  await waitFor(() => expect(getOpenCreateToolWizard(Tool.document)).not.toBeNull());
  getOpenCreateToolWizard(Tool.document)?.();
  return screen.findByRole("dialog");
};

describe("CreateToolWizard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("opens on the community step with nowhere to go back to", async () => {
    await openWizard();

    expect(await screen.findByText("Select a community")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("walks to the initiative step and back again", async () => {
    const user = userEvent.setup();
    await openWizard();

    await user.click(await screen.findByText("Bellwether"));
    expect(await screen.findByText("Select an initiative")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(await screen.findByText("Select a community")).toBeInTheDocument();
    expect(screen.getByText("Bellwether")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("says which step of how many for a screen reader", async () => {
    const user = userEvent.setup();
    await openWizard();

    expect(await screen.findByText("Step 1 of 2")).toBeInTheDocument();

    await user.click(await screen.findByText("Bellwether"));

    expect(await screen.findByText("Step 2 of 2")).toBeInTheDocument();
  });

  it("stays on a step it walked past when Back returns to it", async () => {
    const user = userEvent.setup();
    communitiesValue.communities = communities.slice(0, 1);
    try {
      await openWizard();
      // The only community is walked past on the way in.
      expect(await screen.findByText("Select an initiative")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Back" }));

      expect(await screen.findByText("Select a community")).toBeInTheDocument();
      expect(screen.getByText("Anvil Club")).toBeInTheDocument();
    } finally {
      communitiesValue.communities = communities;
    }
  });
});
