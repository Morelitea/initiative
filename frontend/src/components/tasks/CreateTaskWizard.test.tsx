import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { useCommunities } from "@/hooks/useCommunities";

// Two of each, so no step auto-advances past somebody.
const communities = [
  buildCommunity({ name: "Anvil Club" }),
  buildCommunity({ name: "Bellwether" }),
];

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

// Both of these are held still across renders on purpose: the component keys
// effects off the identity of what the query returns, so a fresh object each
// render would have it chasing its own tail.
const initiativesResult = {
  initiatives: [buildInitiative({ name: "Spring Play" }), buildInitiative({ name: "Summer Play" })],
  isLoading: false,
};
const projectsResult = { data: { items: [], has_next: false } };

vi.mock("@/hooks/useInitiativeAccess", () => ({
  communityMayWriteContent: () => true,
  useCreatableInitiatives: () => initiativesResult,
}));

vi.mock("@/hooks/useProjects", () => ({
  useGlobalProjects: () => projectsResult,
}));

vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ navigate: vi.fn() }),
}));

vi.mock("@/lib/storage", () => ({
  getItem: () => null,
  setItem: vi.fn(),
  removeItem: vi.fn(),
}));

import { CreateTaskWizard, getOpenCreateTaskWizard } from "./CreateTaskWizard";

const openWizard = async () => {
  renderWithProviders(<CreateTaskWizard />, { auth: { user: buildUser() } });
  await waitFor(() => expect(getOpenCreateTaskWizard()).not.toBeNull());
  getOpenCreateTaskWizard()?.();
  return screen.findByRole("dialog");
};

describe("CreateTaskWizard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("opens on the community step with nowhere to go back to", async () => {
    await openWizard();

    expect(await screen.findByText("Select a community")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("walks forward through all three steps and back out again", async () => {
    const user = userEvent.setup();
    await openWizard();

    await user.click(await screen.findByText("Bellwether"));
    expect(await screen.findByText("Select an initiative")).toBeInTheDocument();
    expect(await screen.findByText("Step 2 of 3")).toBeInTheDocument();

    await user.click(await screen.findByText("Summer Play"));
    expect(await screen.findByText("Select a project")).toBeInTheDocument();
    expect(await screen.findByText("Step 3 of 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Select an initiative")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Select a community")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });
});
