import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildInitiative, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { useGuilds } from "@/hooks/useGuilds";

// Two communities, so the first step is one somebody actually walks — with a
// single one the wizard walks past it on its own.
const guilds = [buildGuild({ name: "Anvil Club" }), buildGuild({ name: "Bellwether" })];
// Two initiatives, so the second step does not auto-advance either.
const initiativesResult = {
  initiatives: [buildInitiative({ name: "Spring Play" }), buildInitiative({ name: "Summer Play" })],
  isLoading: false,
};

const guildsValue: ReturnType<typeof useGuilds> = {
  guilds: guilds,
  activeGuildId: null,
  activeGuild: null,
  activeGuildReadOnly: false,
  loading: false,
  error: null,
  refreshGuilds: vi.fn(),
  switchGuild: vi.fn(),
  syncGuildFromUrl: vi.fn(),
  createGuild: vi.fn(),
  updateGuildInState: vi.fn(),
  reorderGuilds: vi.fn(),
  canCreateGuilds: true,
};

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => guildsValue,
}));

vi.mock("@/hooks/useInitiativeAccess", () => ({
  guildMayAuthorTools: () => true,
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

import { CreateDocumentWizard, getOpenCreateDocumentWizard } from "./CreateDocumentWizard";

const openWizard = async () => {
  renderWithProviders(<CreateDocumentWizard />, { auth: { user: buildUser() } });
  await waitFor(() => expect(getOpenCreateDocumentWizard()).not.toBeNull());
  getOpenCreateDocumentWizard()?.();
  return screen.findByRole("dialog");
};

describe("CreateDocumentWizard", () => {
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
    guildsValue.guilds = guilds.slice(0, 1);
    try {
      await openWizard();
      // The only community is walked past on the way in.
      expect(await screen.findByText("Select an initiative")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Back" }));

      expect(await screen.findByText("Select a community")).toBeInTheDocument();
      expect(screen.getByText("Anvil Club")).toBeInTheDocument();
    } finally {
      guildsValue.guilds = guilds;
    }
  });
});
