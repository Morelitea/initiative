/**
 * The profile tab shows you what you are about to be.
 *
 * The card at the top is the same one strangers see, so what is worth pinning
 * is that it is complete — the badges and the status are on it, not only the
 * picture — and that it follows the drafts below rather than what is saved.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildOwnedDecoration, buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

import { UserSettingsProfilePage } from "./UserSettingsProfilePage";

const mocks = vi.hoisted(() => ({ library: vi.fn(), update: vi.fn(), packs: vi.fn() }));

// The only router this page needs is the link out to the marketplace, and a
// real one would cost the test its `rerender`.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/hooks/useUsers", () => ({
  useMyDecorations: () => mocks.library(),
  useUpdateCurrentUser: (options: unknown) => mocks.update(options),
  useDecorationPacks: () => mocks.packs(),
  useRemoveDecorationPack: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}));

const user = buildUser({
  username: "jordan",
  discriminator: 1234,
  custom_status: { emoji: "🎲", text: "Rolling initiative" },
  profile_decorations: { banner: null, frame: "core.gold", badges: ["ttrpg.d20"] },
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.update.mockReturnValue({ mutate: vi.fn(), isPending: false });
  mocks.packs.mockReturnValue({ data: { items: [] }, isLoading: false });
  mocks.library.mockReturnValue({
    data: {
      items: [
        buildOwnedDecoration({ id: "ttrpg.d20", kind: "badge" }),
        buildOwnedDecoration({ id: "fungi.morel", kind: "badge" }),
        buildOwnedDecoration({ id: "core.aurora", kind: "banner" }),
      ],
    },
  });
});

const render = (current: UserRead = user) =>
  renderWithProviders(
    <UserSettingsProfilePage user={current} refreshUser={() => Promise.resolve()} />
  );

describe("the profile preview", () => {
  it("shows the whole profile, not just the picture", async () => {
    render();

    // The handle, the status and the badge a stranger would see.
    expect(await screen.findByText("jordan")).toBeInTheDocument();
    expect(screen.getByText("Rolling initiative")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "d20" })).toBeInTheDocument();
  });

  it("follows what is picked, before it is saved", async () => {
    render();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Morel" }));

    expect(screen.getByRole("img", { name: "Morel" })).toBeInTheDocument();
  });
});

describe("the two halves of the page", () => {
  it("keeps an unsaved pick when the account is refreshed for another reason", async () => {
    const { rerender } = render();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Morel" }));
    expect(screen.getByRole("img", { name: "Morel" })).toBeInTheDocument();

    // Saving the name above refetches the account. The look below it is
    // untouched on the server, so the pick has to survive.
    rerender(
      <UserSettingsProfilePage
        user={{ ...user, full_name: "Jordan Renamed" }}
        refreshUser={() => Promise.resolve()}
      />
    );

    expect(screen.getByRole("img", { name: "Morel" })).toBeInTheDocument();
  });

  it("drops a decoration the server has taken away", async () => {
    const { rerender } = render();

    await screen.findByRole("img", { name: "d20" });

    // Removing a pack strips its pieces server-side; the draft follows.
    rerender(
      <UserSettingsProfilePage
        user={{ ...user, profile_decorations: { banner: null, frame: null, badges: [] } }}
        refreshUser={() => Promise.resolve()}
      />
    );

    expect(screen.queryByRole("img", { name: "d20" })).not.toBeInTheDocument();
  });
});
