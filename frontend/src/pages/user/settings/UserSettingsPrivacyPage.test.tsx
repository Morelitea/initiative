/**
 * The Privacy tab.
 *
 * The two worth keeping are about the age question, which gates every one of
 * these controls on every deployment: an account that has not answered it can
 * choose no policy, and is told why rather than left with a dead radio group.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { UserSettingsPrivacyPage } from "./UserSettingsPrivacyPage";

const mocks = vi.hoisted(() => ({
  settings: vi.fn(),
  update: vi.fn(),
  connections: vi.fn(),
  messages: vi.fn(),
  ignored: vi.fn(),
  noop: vi.fn(),
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useDirectMessages")>()),
  useDmSettings: () => mocks.settings(),
  useUpdateDmSettings: () => ({ mutate: mocks.update, isPending: false }),
  useConnections: () => mocks.connections(),
  useMessageRequests: () => mocks.messages(),
  useIgnoredAccounts: () => mocks.ignored(),
  useRequestConnection: () => ({ mutate: mocks.noop, isPending: false }),
  useRemoveConnection: () => ({ mutate: mocks.noop, isPending: false }),
  useAcceptConnection: () => ({ mutate: mocks.noop, isPending: false }),
  useAcceptMessageRequest: () => ({ mutate: mocks.noop, isPending: false }),
  useRemoveMessageRequest: () => ({ mutate: mocks.noop, isPending: false }),
  useStopIgnoring: () => ({ mutate: mocks.noop, isPending: false }),
}));

const dmSettings = (overrides: Record<string, unknown> = {}) => ({
  data: {
    dm_policy: "private",
    age_confirmed_at: "2026-01-01T00:00:00Z",
    communities: [{ guild_id: 1, name: "Ravenloft Table", icon_url: null, enabled: true }],
    ...overrides,
  },
  isLoading: false,
});

describe("UserSettingsPrivacyPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.settings.mockReturnValue(dmSettings());
    mocks.connections.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
    mocks.messages.mockReturnValue({ data: { accepted: [], incoming: [], outgoing: [] } });
    mocks.ignored.mockReturnValue({ data: { items: [], total: 0 } });
  });

  it("offers the three options the rule has, and nothing else", async () => {
    renderPage(UserSettingsPrivacyPage);

    expect(await screen.findByRole("radio", { name: /private/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /communities/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /anyone/i })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("locks the policy and says why until the age question is answered", async () => {
    mocks.settings.mockReturnValue(dmSettings({ age_confirmed_at: null }));

    renderPage(UserSettingsPrivacyPage);

    expect(await screen.findByText(/13 and over/i)).toBeInTheDocument();
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toBeDisabled();
    }
  });

  it("shows the community toggles only under My communities", async () => {
    renderPage(UserSettingsPrivacyPage);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();

    mocks.settings.mockReturnValue(dmSettings({ dm_policy: "community" }));
    renderPage(UserSettingsPrivacyPage);

    expect(await screen.findByRole("switch", { name: /ravenloft/i })).toBeInTheDocument();
  });

  it("writes only the half that changed", async () => {
    renderPage(UserSettingsPrivacyPage);

    await userEvent.click(await screen.findByRole("radio", { name: /anyone/i }));

    expect(mocks.update).toHaveBeenCalledWith({ data: { dm_policy: "public" } }, expect.anything());
  });

  it("says nothing about who ignored whom", async () => {
    mocks.ignored.mockReturnValue({
      data: {
        items: [
          {
            user_id: 7,
            username: "bram",
            discriminator: 4410,
            avatar_url: null,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
      },
    });

    renderPage(UserSettingsPrivacyPage);

    // The list is the holder's own, and the copy stays on what it does for
    // them — never on what the other account can tell.
    const ignored = await screen.findByText(/bram/i);
    expect(ignored).toBeInTheDocument();
    expect(screen.queryByText(/they will not know/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/notified that/i)).not.toBeInTheDocument();
  });
});
