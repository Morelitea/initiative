import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

// Two communities, so the first step is one somebody actually walks — with a
// single one the wizard walks past it on its own.
const guilds = [
  { id: 1, name: "Anvil Club" },
  { id: 2, name: "Bellwether" },
];

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({ guilds }),
}));

vi.mock("@/hooks/useInitiativeAccess", () => ({
  guildMayAuthorTools: () => true,
  useCreatableInitiatives: () => ({
    // Two, so the second step does not auto-advance either.
    initiatives: [
      { id: 10, name: "Spring Play" },
      { id: 11, name: "Summer Play" },
    ],
    isLoading: false,
  }),
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
});
